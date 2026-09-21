"""Offline regressions for parsing, retention and safe network termination."""
import dataclasses
from contextlib import closing
import io
import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

import pilot


FIXTURE = (pilot.ROOT / "fixtures" / "synthetic.html").read_text(encoding="utf-8")
SOURCE = pilot.BASE + "/product-group/0"


class ParsingTests(unittest.TestCase):
    def test_prompt_example(self):
        self.assertEqual(pilot.parse_title("ピカチュウex(30th)【SAR】{126/103} [M6a]"),
                         ("ピカチュウex", "126/103", "SAR", "SAR", "M6A"))

    def test_width_case_and_leading_zeroes(self):
        self.assertEqual(pilot.normalized_number("０９０ / ０６６"), "90/66")
        self.assertEqual(pilot.normalized_name("Ｐｉｋａｃｈｕ EX！"), pilot.normalized_name("pikachu-ex"))
        self.assertEqual(pilot.parse_title("カード【ｓａｒ】{001/066}")[2:4], ("SAR", "ｓａｒ"))

    def test_unknown_number_and_rarity_require_review(self):
        for title in ["カード【R】{???}", "カード【???】{001/066}", "カード【R】", "カード【R】{001/066} 特殊仕様"]:
            with self.subTest(title=title), self.assertRaises(ValueError):
                pilot.parse_title(title)

    def test_variants_are_not_silently_merged(self):
        for name in ["カード(ミラー)", "〔状態B〕カード", "PSA10カード", "カード(未開封)"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                pilot.parse_title(name + "【R】{001/066}")

    def test_price_stock_and_review_issues(self):
        products, issues = pilot.parse_products(FIXTURE, SOURCE)
        self.assertEqual(len(products), 5)
        self.assertEqual(len(issues), 5)
        self.assertEqual((products[0].price, products[0].stock, products[0].card_number), (11400, 91, "90/66"))
        self.assertEqual(products[1].rarity, "R")
        self.assertEqual(products[1].stock, 0)
        self.assertEqual(products[3].stock, 0)
        self.assertIsNone(products[4].stock)

    def test_does_not_take_neighbour_price(self):
        content = '<ul><li><a href="/product/1">カード【R】{1/2}</a></li><li><a href="/product/2">別カード【R】{2/2}</a>100円</li></ul>'
        products, issues = pilot.parse_products(content, SOURCE)
        self.assertEqual([p.name for p in products], ["別カード"])
        self.assertTrue(any("価格領域" in i["reason"] for i in issues))

    def test_challenge_is_not_empty_success(self):
        with self.assertRaises(pilot.PilotError):
            pilot.parse_products('<title>Just a moment...</title>', SOURCE)

    def test_pagination_is_same_pack_pc_only(self):
        content = '<a href="?page=2">次へ</a><a href="?page=2">2</a><a href="/product-group/9?page=3">他</a><a href="/phone/product-group/0?page=4">携帯</a><a href="https://evil.test/product-group/0?page=5">外部</a>'
        self.assertEqual(pilot.paginated_urls(content, SOURCE, "0"), [SOURCE + "?page=2"])

    def test_discovery_never_invents_ids(self):
        groups = pilot.discover_groups('<a href="/product-group/123">検証パック</a><a href="/phone/product-group/456">携帯</a>')
        self.assertEqual(groups, [{"group_id": "123", "label": "検証パック", "url": pilot.BASE + "/product-group/123"}])


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.sqlite3"
        self.products, _ = pilot.parse_products(FIXTURE, SOURCE)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, products=None, run_id="one", when="2026-09-20T00:00:00+00:00"):
        return pilot.store(self.db, "DEMO", "架空パック", SOURCE,
                           self.products if products is None else products,
                           origin="synthetic", run_id=run_id, fetched_at=when, issues=[])

    def test_threshold_and_provenance(self):
        stats = self.write()
        self.assertEqual(stats["inserted"], 4)
        self.assertEqual(stats["below_threshold_new"], 1)
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cards").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT DISTINCT source FROM prices").fetchall(), [("demo",)])
            self.assertEqual(db.execute("SELECT price,stock_count FROM prices WHERE price=50").fetchone(), (50, 0))

    def test_fall_below_50_retains_card_and_collection_and_recovers(self):
        p = self.products[0]
        self.write([p])
        cid = pilot.card_id("DEMO", p)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("INSERT INTO collection(card_id,owned_count,note) VALUES(?,3,'保持')", (cid,))
        self.write([dataclasses.replace(p, price=30)], "two", "2026-09-21T00:00:00+00:00")
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute("SELECT is_active,first_listed_at FROM cards").fetchone(), (0, "2026-09-20"))
            self.assertEqual(db.execute("SELECT owned_count,note FROM collection").fetchone(), (3, "保持"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM prices").fetchone()[0], 2)
        self.write([p], "three")
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute("SELECT is_active FROM cards").fetchone()[0], 1)

    def test_absent_card_is_not_marked_inactive(self):
        self.write()
        self.write([self.products[0]], "two")
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cards WHERE is_active=1").fetchone()[0], 4)

    def test_zero_results_do_not_create_database(self):
        with self.assertRaises(pilot.PilotError):
            self.write([])
        self.assertFalse(self.db.exists())

    def test_conflicting_products_are_skipped(self):
        p = self.products[0]
        stats = self.write([p, dataclasses.replace(p, price=9), self.products[1]])
        self.assertEqual(stats["conflicts"], 1)
        self.assertEqual(stats["inserted"], 1)

    def test_mixed_set_category_is_rejected(self):
        with self.assertRaises(pilot.PilotError):
            self.write([self.products[0], dataclasses.replace(self.products[1], set_code="OTHER")])
        self.assertFalse(self.db.exists())


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = pilot.Client(Path(self.tmp.name) / "requests.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_403_and_429_stop_without_retries(self):
        for status in [403, 429]:
            with self.subTest(status=status):
                c = pilot.Client(Path(self.tmp.name) / f"{status}.jsonl")
                c.opener.open = Mock(side_effect=urllib.error.HTTPError(SOURCE, status, "blocked", {}, None))
                for _ in range(2):
                    with self.assertRaises(pilot.PilotError):
                        c.raw(SOURCE)
                self.assertEqual(c.opener.open.call_count, 1)
                self.assertEqual(c.count, 1)

    def test_robots_disallow_prevents_product_request(self):
        self.client.raw = Mock(return_value=(b"User-agent: *\nDisallow: /product-group/\n", "text/plain", "utf-8"))
        with self.assertRaises(pilot.PilotError):
            self.client.get(SOURCE)
        self.assertEqual(self.client.raw.call_count, 1)

    def test_robots_failure_does_not_default_to_allow(self):
        self.client.raw = Mock(side_effect=pilot.PilotError("HTTP 403"))
        with self.assertRaises(pilot.PilotError):
            self.client.get(SOURCE)
        self.assertEqual(self.client.raw.call_count, 1)

    def test_robots_html_is_rejected(self):
        self.client.raw = Mock(return_value=(b"<html>challenge</html>", "text/html", "utf-8"))
        with self.assertRaises(pilot.PilotError):
            self.client.get(SOURCE)
        self.assertEqual(self.client.raw.call_count, 1)

    def test_robot_identity_is_honest_and_specific(self):
        data = b"User-agent: GPTBot\nUser-agent: Bytespider\nDisallow: /\n"
        self.client.raw = Mock(side_effect=[(data, "text/plain", "utf-8"), (b"ok", "text/html", "utf-8")])
        self.assertEqual(self.client.get(SOURCE)[0], b"ok")
        self.assertIn(pilot.ROBOT_NAME, pilot.UA)

    def test_external_and_mobile_urls_never_requested(self):
        self.client.raw = Mock()
        for url in ["http://" + pilot.HOST + "/", "https://evil.test/", pilot.BASE + "/phone/product-group/1", "https://user:password@" + pilot.HOST]:
            with self.subTest(url=url), self.assertRaises(pilot.PilotError):
                self.client.get(url)
        self.client.raw.assert_not_called()

    def test_minimum_interval_and_hard_request_limit(self):
        c = self.client
        c.last, c.count, c.limit = 99.5, 1, 2
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.status = 200
        response.read.return_value = b"ok"
        response.headers.get_content_type.return_value = "text/plain"
        response.headers.get_content_charset.return_value = "utf-8"
        c.opener.open = Mock(return_value=response)
        with patch("pilot.time.monotonic", return_value=100), patch("pilot.time.sleep") as sleep:
            c.raw(SOURCE)
            sleep.assert_called_once_with(1.5)
            with self.assertRaises(pilot.PilotError):
                c.raw(SOURCE)
        self.assertEqual(c.opener.open.call_count, 1)


class ReportTests(unittest.TestCase):
    def test_report_escapes_html_and_has_no_remote_image(self):
        products, _ = pilot.parse_products(FIXTURE, SOURCE)
        products[0].name = '<script>alert("x")</script>'
        with tempfile.TemporaryDirectory() as tmp:
            pilot.report_files(tmp, {"origin": "synthetic"}, products)
            output = (Path(tmp) / "review.html").read_text(encoding="utf-8")
            self.assertNotIn("<script>", output)
            self.assertNotIn("<img", output)
            self.assertIn("&lt;script&gt;", output)
            self.assertIn("架空のテストデータ", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
