"""Fetch USD reference prices from billsarchive.com per-set gallery pages and
attach them to matching cards in Firebase, keyed by collection number.

billsarchive.com has no Terms of Service and an unrestricted robots.txt
(Allow: /, no crawl-delay); this script is deliberately low-volume (one
request per set, ~2s apart) and identifies itself with a real User-Agent.

Usage: python3 fetch_us_prices.py
"""
import json
import re
import time
import urllib.request
from pathlib import Path

from google.oauth2 import service_account
import google.auth.transport.requests

ROOT = Path(__file__).resolve().parent.parent
KEY_PATH = ROOT / "firebase-service-account.json"
DATABASE_URL = "https://pokemon-catalog-6c823-default-rtdb.asia-southeast1.firebasedatabase.app"

UA = "Mozilla/5.0 (compatible; pokemon-catalog personal price tracker)"

# Reference rate only (matches the rate billsarchive.com itself quotes on its
# pages as of this writing); not a live feed. Good enough for the JP/US
# reference-price comparison this app shows, not for financial use.
USD_JPY_RATE = 158.9

SET_PAGES = {
    "M3": "nihil-zero",
    "M4": "ninja-spinner",
    "M5": "abyss-eye",
    "M6": "storm-emeralda",
    "M6A": "30th-celebration",
}

PRICE_RE = re.compile(r'<span class="pc-tile-usd">\$([\d,.]+)</span>')
NAME_RE = re.compile(r'<div class="gallery-card-name">([^<]*)</div>')
NUMBER_RE = re.compile(r'<div class="gallery-card-number">(\d+)')


def fb_creds():
    creds = service_account.Credentials.from_service_account_file(
        str(KEY_PATH),
        scopes=["https://www.googleapis.com/auth/firebase.database",
                "https://www.googleapis.com/auth/userinfo.email"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    return creds


def fb_patch(creds, path, data):
    req = urllib.request.Request(
        f"{DATABASE_URL}/{path}.json",
        data=json.dumps(data).encode("utf-8"),
        method="PATCH",
        headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_set_page(slug):
    req = urllib.request.Request(f"https://billsarchive.com/{slug}.html", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_prices(html):
    # Split on each card block first so the per-field regexes only ever scan
    # a small bounded chunk -- avoids catastrophic backtracking on large pages.
    out = {}
    for chunk in html.split('<div class="gallery-card-img">')[1:]:
        head = chunk[:800]
        price_m = PRICE_RE.search(head)
        name_m = NAME_RE.search(head)
        number_m = NUMBER_RE.search(head)
        if price_m and name_m and number_m:
            out[number_m.group(1)] = {
                "usd": float(price_m.group(1).replace(",", "")),
                "nameEn": name_m.group(1).strip(),
            }
    return out


def main():
    creds = fb_creds()

    all_cards_req = urllib.request.Request(
        f"{DATABASE_URL}/cards.json",
        headers={"Authorization": f"Bearer {creds.token}"},
    )
    with urllib.request.urlopen(all_cards_req) as r:
        all_cards = json.loads(r.read()) or {}

    for pack_id, slug in SET_PAGES.items():
        html = fetch_set_page(slug)
        prices = parse_prices(html)
        print(f"{pack_id} ({slug}): parsed {len(prices)} priced cards from page")

        pack_cards = {cid: c for cid, c in all_cards.items() if c.get("packId") == pack_id}

        matched = 0
        for card_id, card in pack_cards.items():
            number = card["cardNumber"].split("/")[0]
            hit = prices.get(number) or prices.get(str(int(number)))
            if hit:
                fb_patch(creds, f"cards/{card_id}", {
                    "latestPriceUsd": hit["usd"],
                    "latestPriceUsdJpyEquiv": round(hit["usd"] * USD_JPY_RATE),
                    "priceUsdSource": "billsarchive",
                })
                matched += 1
        print(f"  -> matched {matched}/{len(pack_cards)} cards\n")
        time.sleep(2)


if __name__ == "__main__":
    main()
