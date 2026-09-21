"""Phase 1 only: conservative Cardrush HTML -> SQLite pilot (Python 3.10+).

No browser impersonation, challenge solving, proxy rotation or automatic retries.
HTML parsing has been tested against synthetic fixtures, NOT live shop HTML.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from contextlib import closing
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "www.cardrush-pokemon.jp"
BASE = "https://" + HOST
UA = "PokemonLocalCatalog/0.1 (personal collection; permission confirmed by user)"
ROBOT_NAME = "PokemonLocalCatalog"
KNOWN_RARITIES = {"C", "U", "R", "RR", "RRR", "SR", "HR", "UR", "AR", "SAR", "CHR", "CSR", "ACE", "A", "S", "SSR", "PR", "PROMO", "K"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def nfkc(value):
    return unicodedata.normalize("NFKC", value).strip()


def normalized_name(value):
    return "".join(c for c in nfkc(value).casefold()
                   if not c.isspace() and not unicodedata.category(c).startswith("P"))


def normalized_number(value):
    parts = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", nfkc(value))
    if not parts:
        raise ValueError("型番が数値/数値ではありません。手動確認が必要です")
    return f"{int(parts[1])}/{int(parts[2])}"


class PilotError(RuntimeError):
    pass


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    parent: Node | None = field(default=None, repr=False)
    children: list = field(default_factory=list)

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

    def text(self):
        if self.tag in {"script", "style", "noscript"}:
            return ""
        return " ".join(c.text() if isinstance(c, Node) else c for c in self.children)


class Tree(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.current = self.root
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def shop_url(url, base=BASE):
    p = urllib.parse.urlsplit(urllib.parse.urljoin(base, url))
    if p.scheme != "https" or p.hostname != HOST or p.port not in (None, 443) or p.username or p.password:
        raise PilotError("通販サイト以外のURLは取得しません")
    if "/phone/" in p.path:
        raise PilotError("モバイル版URLは使用しません")
    return urllib.parse.urlunsplit(("https", HOST, p.path, p.query, ""))


def product_url(href, base):
    try:
        url = shop_url(href or "", base)
    except (PilotError, ValueError):
        return None
    p = urllib.parse.urlsplit(url)
    return BASE + p.path if re.fullmatch(r"/product/\d+/?", p.path) else None


@dataclass
class Product:
    name: str
    card_number: str
    rarity: str
    rarity_raw: str
    set_code: str
    price: int
    stock: int | None
    source_url: str
    title_raw: str
    image_url: str | None = None


def parse_title(title):
    # Unknown decorations/variants are intentionally not merged with normal cards.
    text = nfkc(title)
    m = re.fullmatch(r"(.+?)【([^】]+)】\{([^}]+)\}\s*(?:\[([^\]]+)\])?", text)
    if not m:
        raise ValueError("タイトル形式不明（名前・レアリティ・型番を確認）")
    name, raw_rarity, number, code = m.groups()
    original_rarity = re.search(r"【([^】]+)】", title)
    if original_rarity:
        raw_rarity = original_rarity[1]
    if any(x in name for x in ("状態", "傷", "キズ", "ミラー", "エラー", "未開封", "PSA", "鑑定")):
        raise ValueError("状態違い・加工違い・鑑定品の可能性。手動確認が必要")
    # Only remove a final set abbreviation as described in the supplied prompt.
    name = re.sub(r"\([^()]+\)$", "", name).strip()
    rarity = re.sub(r"\s+", "", nfkc(raw_rarity)).upper()
    if rarity not in KNOWN_RARITIES:
        raise ValueError(f"未対応レアリティ: {raw_rarity}")
    if not name:
        raise ValueError("カード名がありません")
    return name, normalized_number(number), rarity, raw_rarity, (code or "").upper()


def parse_products(content, source_url):
    if "cf-chl" in content or "Just a moment..." in content:
        raise PilotError("アクセス確認ページです。取得は停止しました")
    root = Tree(content).root
    grouped = {}
    for node in root.walk():
        if node.tag == "a" and (url := product_url(node.attrs.get("href"), source_url)):
            grouped.setdefault(url, []).append(node)
    products, issues = [], []
    for url, anchors in grouped.items():
        title = ""
        for a in anchors:
            candidates = [a.text(), a.attrs.get("title", "")]
            candidates += [n.attrs.get("alt", "") for n in a.walk() if n.tag == "img"]
            title = next((re.sub(r"\s+", " ", x).strip() for x in candidates if "【" in x), title)
            if title:
                break
        try:
            parsed = parse_title(title)
        except ValueError as exc:
            issues.append({"url": url, "title": title, "reason": str(exc)})
            continue
        container = None
        for a in anchors:
            node = a.parent
            while node and node.tag != "root":
                links = {product_url(n.attrs.get("href"), source_url)
                         for n in node.walk() if n.tag == "a"}
                links.discard(None)
                if len(links) > 1:
                    break
                if re.search(r"[\d,]+\s*円", nfkc(node.text())):
                    container = node
                    break
                node = node.parent
            if container:
                break
        if container is None:
            issues.append({"url": url, "title": title, "reason": "商品の価格領域が見つかりません"})
            continue
        text = nfkc(container.text())
        prices = {int(x.replace(",", "")) for x in re.findall(r"([\d,]+)\s*円", text)}
        if len(prices) != 1:
            issues.append({"url": url, "title": title, "reason": "複数価格があり販売価格を確定できません"})
            continue
        stock_match = re.search(r"在庫(?:数)?\s*[:：]?\s*([\d,]+)\s*枚", text)
        stock = int(stock_match[1].replace(",", "")) if stock_match else None
        if stock is None and re.search(r"SOLD\s*OUT|在庫なし|売り切れ|品切れ", text, re.I):
            stock = 0
        if stock is None:
            issues.append({"url": url, "title": title, "reason": "在庫数欠損（価格は保存・在庫はNULL）"})
        imgs = [n for n in container.walk() if n.tag == "img"]
        image_url = None
        for im in imgs:
            raw = im.attrs.get("data-src") or im.attrs.get("src")
            if raw and not raw.startswith("data:"):
                image_url = urllib.parse.urljoin(source_url, raw)
                break
        products.append(Product(*parsed, prices.pop(), stock, url, title, image_url))
    if not grouped:
        issues.append({"reason": "商品リンクが0件。HTML構造またはアクセス制限を確認してください"})
    return products, issues


def discover_groups(content):
    groups = {}
    for n in Tree(content).root.walk():
        if n.tag != "a":
            continue
        try:
            url = shop_url(n.attrs.get("href", ""))
        except (PilotError, ValueError):
            continue
        match = re.fullmatch(r"/product-group/(\d+)/?", urllib.parse.urlsplit(url).path)
        if match:
            groups[match[1]] = {"group_id": match[1], "label": n.text().strip(), "url": BASE + "/product-group/" + match[1]}
    return list(groups.values())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    """Serial requests with fail-closed robots and a 2 second minimum gap."""
    def __init__(self, log_path, delay=2.0, limit=40):
        if not 1 <= delay <= 3:
            raise ValueError("リクエスト間隔は1〜3秒です")
        self.delay, self.limit = delay, limit
        self.last = None
        self.count = 0
        self.halted = False
        self.robots = {}
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.opener = urllib.request.build_opener(NoRedirect())

    def event(self, **values):
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now(), **values}, ensure_ascii=False) + "\n")

    def raw(self, url):
        if self.halted:
            raise PilotError("先行リクエストで停止しています。自動再試行はしません")
        if self.count >= self.limit:
            raise PilotError(f"パイロット上限 {self.limit} リクエストに到達しました")
        if self.last is not None:
            time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        self.count += 1
        self.last = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,text/plain,image/*"})
            with self.opener.open(req, timeout=30) as response:
                body = response.read(10 * 1024 * 1024 + 1)
                if len(body) > 10 * 1024 * 1024:
                    raise PilotError("レスポンスが10MBを超えたため停止")
                self.event(url=url, status=response.status, bytes=len(body), request=self.count)
                return body, response.headers.get_content_type(), response.headers.get_content_charset() or "utf-8"
        except urllib.error.HTTPError as exc:
            self.event(url=url, status=exc.code, request=self.count)
            self.halted = True
            raise PilotError(f"HTTP {exc.code}: {url}。取得を停止。自動再試行しません") from exc
        except (OSError, PilotError) as exc:
            self.event(url=url, error=str(exc), request=self.count)
            self.halted = True
            raise PilotError(f"通信停止: {exc}") from exc

    def get(self, url):
        p = urllib.parse.urlsplit(url)
        if p.scheme != "https" or p.hostname != HOST or p.port not in (None, 443) or p.username or p.password:
            raise PilotError("パイロットでは確認済み通販ホストのみ取得します。外部画像は保存しません")
        shop_url(url)
        origin = "https://" + HOST
        if origin not in self.robots:
            data, content_type, charset = self.raw(origin + "/robots.txt")
            robots_text = data.decode(charset, errors="strict")
            if "html" in content_type or "<html" in robots_text.lower():
                self.halted = True
                raise PilotError("robots.txtがHTMLでした。許可状態を確認できないため停止")
            robot = urllib.robotparser.RobotFileParser()
            robot.parse(robots_text.splitlines())
            self.robots[origin] = robot
        robot = self.robots[origin]
        if not robot.can_fetch(ROBOT_NAME, url):
            self.event(url=url, error="robots_disallow")
            raise PilotError("robots.txtで禁止されたパスです")
        crawl_delay = robot.crawl_delay(ROBOT_NAME)
        rate = robot.request_rate(ROBOT_NAME)
        if (crawl_delay and crawl_delay > self.delay) or (rate and rate.seconds / rate.requests > self.delay):
            raise PilotError("robots.txtのアクセス間隔が設定値より長いため停止")
        return self.raw(url)

    def text(self, url):
        data, content_type, charset = self.get(url)
        if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise PilotError("HTMLではない応答です")
        text = data.decode(charset, errors="strict")
        if "cf-chl" in text or "Just a moment..." in text:
            self.halted = True
            raise PilotError("アクセス確認ページを検出したため停止しました")
        return text


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS packs (
 pack_id TEXT PRIMARY KEY, name TEXT NOT NULL, series TEXT, set_code TEXT,
 release_date DATE, card_count INTEGER, source_url TEXT
);
CREATE TABLE IF NOT EXISTS cards (
 card_id TEXT PRIMARY KEY, pack_id TEXT NOT NULL REFERENCES packs(pack_id),
 name TEXT NOT NULL, card_number TEXT, rarity TEXT, rarity_raw TEXT,
 image_path TEXT, source_url TEXT, first_listed_at DATE,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
);
CREATE TABLE IF NOT EXISTS prices (
 id INTEGER PRIMARY KEY AUTOINCREMENT, card_id TEXT NOT NULL REFERENCES cards(card_id),
 market TEXT NOT NULL CHECK(market IN ('JP','US')), price_type TEXT NOT NULL,
 price INTEGER, price_original REAL, currency TEXT, fx_rate REAL, source TEXT,
 fetched_at DATETIME NOT NULL, available INTEGER NOT NULL DEFAULT 1,
 stock_count INTEGER, run_id TEXT, source_url TEXT
);
CREATE INDEX IF NOT EXISTS prices_latest ON prices(card_id, market, price_type, fetched_at);
CREATE TABLE IF NOT EXISTS collection (
 card_id TEXT PRIMARY KEY REFERENCES cards(card_id), owned_count INTEGER DEFAULT 0 CHECK(owned_count>=0),
 condition TEXT, note TEXT, updated_at DATETIME
);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, pack_id TEXT, started_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL, origin TEXT NOT NULL, report_json TEXT
);
"""


def card_id(pack_id, p):
    key = "|".join((pack_id, normalized_name(p.name), p.rarity, p.card_number))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def store(db, pack_id, pack_name, source_url, products, *, origin, run_id, fetched_at, issues):
    if not products:
        raise PilotError("解析成功が0件のためDBは更新しません")
    # A category may combine variants or packs: do not choose an arbitrary price.
    by_id = {}
    conflicts = set()
    for p in products:
        cid = card_id(pack_id, p)
        if cid in by_id and by_id[cid] != p:
            conflicts.add(cid)
        by_id[cid] = p
    for cid in conflicts:
        issues.append({"title": by_id[cid].title_raw, "reason": "同一キーの複数商品。価格は保存せず手動確認"})
        del by_id[cid]
    if not by_id:
        raise PilotError("全商品で同一キー衝突。DBは更新しません")
    codes = {p.set_code for p in by_id.values() if p.set_code}
    if len(codes) > 1:
        raise PilotError("複数セットコードを検出。1パックのカテゴリか確認してください")
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    stats = {"parsed": len(products), "inserted": 0, "updated": 0, "below_threshold_new": 0, "conflicts": len(conflicts)}
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO packs(pack_id,name,set_code,source_url) VALUES(?,?,?,?) ON CONFLICT(pack_id) DO UPDATE SET name=excluded.name, set_code=COALESCE(excluded.set_code,packs.set_code), source_url=excluded.source_url",
                     (pack_id, pack_name, next(iter(codes), None), source_url))
        for cid, p in by_id.items():
            exists = conn.execute("SELECT 1 FROM cards WHERE card_id=?", (cid,)).fetchone()
            if not exists and p.price < 50:
                stats["below_threshold_new"] += 1
                continue
            conn.execute("""INSERT INTO cards(card_id,pack_id,name,card_number,rarity,rarity_raw,source_url,first_listed_at,is_active)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(card_id) DO UPDATE SET name=excluded.name,rarity_raw=excluded.rarity_raw,
              source_url=excluded.source_url,is_active=excluded.is_active""",
                         (cid, pack_id, p.name, p.card_number, p.rarity, p.rarity_raw, p.source_url, fetched_at[:10], int(p.price >= 50)))
            conn.execute("""INSERT INTO prices(card_id,market,price_type,price,price_original,currency,fx_rate,source,fetched_at,available,stock_count,run_id,source_url)
              VALUES(?,'JP','sell',?,?,'JPY',1,?,?,1,?,?,?)""",
                         (cid, p.price, p.price, "demo" if origin == "synthetic" else "cardrush", fetched_at, p.stock, run_id, p.source_url))
            stats["updated" if exists else "inserted"] += 1
        # Do not flag unseen products inactive: absent pages != a sub-50 price.
        conn.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run_id, pack_id, fetched_at, now(), "stored_with_issues" if issues else "stored", origin, json.dumps(stats, ensure_ascii=False)))
    return stats


def report_files(out, report, products):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    esc = lambda s: html.escape(str(s if s is not None else "欠損"))
    rows = "".join("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in
        (p.name, p.rarity_raw, p.rarity, p.card_number, p.set_code, f"{p.price:,}円", p.stock, p.title_raw)) + "</tr>" for p in products)
    (out / "review.html").write_text("""<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>フェーズ1・解析確認</title>
<style>body{font:15px/1.7 system-ui;background:#f5f6f8;color:#18293b;margin:36px}h1{font-size:26px}table{border-collapse:collapse;width:100%;background:white}th,td{padding:12px;border-bottom:1px solid #ddd;text-align:left}th{background:#e1eaf3}pre{white-space:pre-wrap;background:#fff;padding:20px;border-radius:10px}.notice{background:#fff0c2;padding:16px;border-radius:10px}</style>
<h1>フェーズ1 · 解析確認</h1><p class="notice">""" +
        ("架空のテストデータです。実際の相場・商品ではありません。" if report.get("origin") == "synthetic" else "取り込み結果です。実サイトとの一致は別途目視確認が必要です。") +
        "</p><p>画像の直リンク・外部通信はありません。</p><table><thead><tr>" +
        "".join(f"<th>{x}</th>" for x in ["名前", "元レアリティ", "正規化", "型番", "セット", "価格", "在庫", "元タイトル"]) +
        "</tr></thead><tbody>" + rows + "</tbody></table><h2>実行結果・要確認項目</h2><pre>" +
        esc(json.dumps(report, ensure_ascii=False, indent=2)) + "</pre></html>", encoding="utf-8")


def paginated_urls(content, current, group_id):
    found = set()
    for n in Tree(content).root.walk():
        if n.tag != "a":
            continue
        try:
            url = shop_url(n.attrs.get("href", ""), current)
        except (PilotError, ValueError):
            continue
        p = urllib.parse.urlsplit(url)
        if p.path.rstrip("/") != f"/product-group/{group_id}":
            continue
        query = urllib.parse.parse_qs(p.query)
        if set(query) == {"page"} and len(query["page"]) == 1 and query["page"][0].isdigit():
            page = int(query["page"][0])
            if page > 1:
                found.add(f"{BASE}/product-group/{group_id}?page={page}")
    return sorted(found, key=lambda u: int(urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)["page"][0]))


def run(args):
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = now()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    report = {"run_id": run_id, "started_at": started, "phase": 1,
              "live_html_validated": False, "origin": "synthetic" if args.command == "demo" else args.command,
              "issues": []}
    products = []
    client = Client(out / "requests.jsonl")
    try:
        if args.command == "discover":
            groups = discover_groups(client.text(BASE + "/group"))
            if not groups:
                raise PilotError("product-group候補を取得できませんでした")
            report.update(status="discovered", groups=groups)
        else:
            if args.command == "demo":
                pack_id, pack_name = "DEMO", "検証用・架空パック（実相場ではありません）"
                source_url = BASE + "/product-group/0"
                contents = [(source_url, (ROOT / "fixtures" / "synthetic.html").read_text(encoding="utf-8"))]
                db = out / "demo.sqlite3"
            else:
                pack_id, pack_name = "cardrush-" + args.group_id, args.pack_name
                source_url = BASE + "/product-group/" + args.group_id
                db = out / "catalog.sqlite3"
                if args.command == "import-html":
                    contents = [(source_url, Path(f).read_text(encoding="utf-8-sig")) for f in args.files]
                    if any('data-synthetic="true"' in content for _, content in contents):
                        raise PilotError("架空データを本番DBに取り込めません。demoを使用してください")
                    report["note"] = "ユーザー提供HTMLの解析。実際の取得日時は不明。fetched_atは取り込み日時"
                else:
                    contents, queue, seen = [], [source_url], set()
                    while queue:
                        url = queue.pop(0)
                        if url in seen:
                            continue
                        if len(seen) >= 20:
                            raise PilotError("20ページ上限。全ページ未取得のため保存しません")
                        seen.add(url)
                        content = client.text(url)
                        (out / f"page-{len(seen):02}.html").write_text(content, encoding="utf-8")
                        contents.append((url, content))
                        queue.extend(u for u in paginated_urls(content, url, args.group_id) if u not in seen)
            for url, content in contents:
                parsed, issues = parse_products(content, url)
                report["issues"].extend(issues)
                if not parsed:
                    raise PilotError("解析0件のページがあるため、部分的な結果をDBに保存しません")
                products.extend(parsed)
            report["pages"] = len(contents)
            report["stats"] = store(db, pack_id, pack_name, source_url, products,
                origin=report["origin"], run_id=run_id, fetched_at=started, issues=report["issues"])
            report["database"] = str(db)
            report["status"] = "stored_with_issues" if report["issues"] else "stored"
            report["image_status"] = "未取得。パイロットでは外部画像を表示・直リンクしません"
            report["phase_1_passed"] = False
            report["remaining_checks"] = ["実HTMLとの目視照合", "許可された接続経路での連続アクセス検証", "画像ホスト・利用条件の確認"]
    except (PilotError, ValueError, OSError, sqlite3.Error) as exc:
        report.update(status="failed", error=str(exc), phase_1_passed=False)
    report.update(finished_at=now(), request_count=client.count)
    report_files(out, report, products)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "failed" else 0


def main():
    parser = argparse.ArgumentParser(description="ポケモンカード図鑑・フェーズ1検証ツール")
    subs = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [("demo", "架空HTMLでオフライン検証"), ("discover", "カテゴリ候補取得"),
                            ("fetch", "1パックの全ページ取得・保存"), ("import-html", "提供されたUTF-8 HTMLを解析・保存")]:
        sub = subs.add_parser(name, help=help_text)
        sub.add_argument("--out", default=str(ROOT / "data" / name), help="出力フォルダー")
        if name in {"fetch", "import-html"}:
            sub.add_argument("--group-id", required=True, type=lambda v: v if re.fullmatch(r"\d+", v) else parser.error("group-idは数字です"))
            sub.add_argument("--pack-name", required=True)
        if name == "import-html":
            sub.add_argument("files", nargs="+", help="保存済みHTML。ページが複数ならすべて指定")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
