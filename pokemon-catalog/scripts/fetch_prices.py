"""Fetch JP price ranges + a representative image for cards in a pack, from
Rakuten and Yahoo! Shopping, and write them into Firebase.

For each card, both marketplaces are searched (name + rarity + set hint).
Listings are accepted only if the title contains the card name, the rarity
token, the collection number, and none of EXCLUDE_TERMS (condition variants,
bundles, graded slabs). All accepted listings across both marketplaces
contribute to a min~max price range; the cheapest one supplies the image.

Usage: python3 fetch_prices.py <pack_id> [--query-suffix "30th"]
"""
import argparse
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from google.oauth2 import service_account
import google.auth.transport.requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
KEY_PATH = ROOT / "firebase-service-account.json"
DATABASE_URL = "https://pokemon-catalog-6c823-default-rtdb.asia-southeast1.firebasedatabase.app"

# Titles containing these are excluded even on a name/rarity/number match:
# condition variants, sets/bundles, or graded slabs are not the same product
# as a single raw card.
EXCLUDE_TERMS = ["状態", "傷", "キズ", "ミラー", "エラー", "未開封", "PSA", "鑑定",
                  "セット", "まとめ", "福袋", "複数", "BOX", "box"]


def load_env():
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def fb_creds():
    creds = service_account.Credentials.from_service_account_file(
        str(KEY_PATH),
        scopes=["https://www.googleapis.com/auth/firebase.database",
                "https://www.googleapis.com/auth/userinfo.email"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds


def fb_get(creds, path):
    req = urllib.request.Request(f"{DATABASE_URL}/{path}.json",
                                  headers={"Authorization": f"Bearer {creds.token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fb_patch(creds, path, data):
    req = urllib.request.Request(
        f"{DATABASE_URL}/{path}.json",
        data=json.dumps(data).encode("utf-8"),
        method="PATCH",
        headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def nfkc(s):
    return unicodedata.normalize("NFKC", s)


def rakuten_search(env, keyword):
    params = {
        "applicationId": env["RAKUTEN_APPLICATION_ID"],
        "accessKey": env["RAKUTEN_ACCESS_KEY"],
        "keyword": keyword,
        "hits": 10,
        "format": "json",
    }
    url = env["RAKUTEN_ITEM_SEARCH_ENDPOINT"] + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception:
        return []
    out = []
    for it in data.get("Items", []):
        item = it.get("Item", it)
        images = item.get("mediumImageUrls") or []
        out.append({
            "title": item.get("itemName", ""),
            "price": item.get("itemPrice"),
            "url": item.get("itemUrl"),
            "image": images[0].get("imageUrl") if images else None,
            "source": "rakuten",
        })
    return out


def yahoo_search(env, query):
    params = {"appid": env["YAHOO_CLIENT_ID"], "query": query, "results": 10}
    url = "https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
    except Exception:
        return []
    out = []
    for hit in data.get("hits", []):
        image = hit.get("image", {})
        out.append({
            "title": hit.get("name", ""),
            "price": hit.get("price"),
            "url": hit.get("url"),
            "image": image.get("medium") or image.get("small"),
            "source": "yahoo",
        })
    return out


def pick_matches(results, name, rarity, number):
    name_n = nfkc(name)
    rarity_n = nfkc(rarity)
    num_str = number.split("/")[0]
    num_int = str(int(num_str))
    # Sellers write the collection number un-padded ("9") or zero-padded
    # ("009"), and their own printed total often differs from ours, so match
    # the numerator only, as a standalone token (not part of a longer number).
    num_pattern = r"(?<!\d)(?:" + re.escape(num_str) + "|" + re.escape(num_int) + r")(?!\d)"

    candidates = []
    for r in results:
        if r["price"] is None:
            continue
        title_n = nfkc(r["title"])
        if name_n not in title_n:
            continue
        if any(term in title_n for term in EXCLUDE_TERMS):
            continue
        if not re.search(r"(^|[^A-Za-z])" + re.escape(rarity_n) + r"([^A-Za-z]|$)", title_n, re.IGNORECASE):
            continue
        if not re.search(num_pattern, title_n):
            continue
        candidates.append(r)
    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pack_id")
    parser.add_argument("--query-suffix", default="", help='extra keyword, e.g. "30th"')
    parser.add_argument("--delay", type=float, default=1.1)
    args = parser.parse_args()

    env = load_env()
    creds = fb_creds()

    cards = fb_get(creds, "cards") or {}
    pack_cards = {cid: c for cid, c in cards.items() if c.get("packId") == args.pack_id}
    if not pack_cards:
        print(f"No cards found with packId={args.pack_id!r}")
        return

    report = []
    for card_id, card in sorted(pack_cards.items()):
        name, rarity, number = card["name"], card["rarity"], card["cardNumber"]
        query = f"{name} {rarity} {args.query_suffix}".strip()

        candidates = pick_matches(rakuten_search(env, query), name, rarity, number)
        time.sleep(args.delay)
        candidates += pick_matches(yahoo_search(env, query), name, rarity, number)
        time.sleep(args.delay)

        if candidates:
            prices = [c["price"] for c in candidates]
            price_min, price_max = min(prices), max(prices)
            best = min(candidates, key=lambda c: c["price"])
            fb_patch(creds, f"cards/{card_id}", {
                "latestPriceJpyMin": price_min,
                "latestPriceJpyMax": price_max,
                "priceListingCount": len(candidates),
                "imageUrl": best["image"],
                "priceSource": best["source"],
                "priceSourceUrl": best["url"],
            })
            report.append((card_id, name, rarity, "OK", price_min, price_max, len(candidates)))
        else:
            report.append((card_id, name, rarity, "NO_MATCH", None, None, 0))

    print(f"{'card_id':14} {'name':14} {'rarity':6} {'status':9} {'min':7} {'max':7} n")
    matched = 0
    for card_id, name, rarity, status, pmin, pmax, n in report:
        if status == "OK":
            matched += 1
        print(f"{card_id:14} {name:14} {rarity:6} {status:9} {str(pmin):7} {str(pmax):7} {n}")
    print(f"\n{matched}/{len(report)} matched")


if __name__ == "__main__":
    main()
