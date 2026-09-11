"""
KDDI Chatwork (rid445630230) からメッセージを取得し、
既存の指定スプレッドシートに書き出すスクリプト
"""

import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

from google.oauth2 import service_account
from googleapiclient.discovery import build

try:
    from config_auth import CW_EMAIL, CW_PASSWORD
except ImportError:
    CW_EMAIL = os.environ.get("CW_EMAIL", "")
    CW_PASSWORD = os.environ.get("CW_PASSWORD", "")

JST = timezone(timedelta(hours=9))
ROOM_ID = "445630230"
URL = f"https://kcw.kddi.ne.jp/#!rid{ROOM_ID}"
COOKIE_FILE = Path("chatwork_cookies.json")

SPREADSHEET_ID = "13cK3BhIxFot0cZilbDHa4dzZoH_tocmNYWEk-pTnkJo"
SHEET_NAME = "CW書き出し"

SA_PATH = Path("../../google-workspace-mcp/credentials.json")

def get_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_PATH),
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

def get_messages():
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    print(f"=== 本日 ({today_str}) のチャット取得を開始します ===")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        if COOKIE_FILE.exists():
            try:
                cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
                context.add_cookies(cookies)
            except Exception:
                pass

        page = context.new_page()
        page.goto(URL, wait_until="commit", timeout=30000)
        page.wait_for_timeout(5000)

        if "auth.chatwork.com" in page.url or page.locator("#username").is_visible():
            page.wait_for_selector("#username", timeout=15000)
            page.fill("#username", CW_EMAIL)
            page.click("button[type='submit']")
            page.wait_for_selector("input[type='password']", state="attached", timeout=30000)
            page.wait_for_timeout(2000)
            page.evaluate("document.querySelectorAll('input[type=\"password\"]').forEach(el => { el.classList.remove('hide'); el.style.display = ''; el.style.visibility = 'visible'; })")
            page.fill("input[type='password']", CW_PASSWORD)
            page.click("button[type='submit']")
            page.wait_for_timeout(8000)
            
            cookies = context.cookies()
            COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
            page.goto(URL, wait_until="commit", timeout=30000)
            page.wait_for_timeout(5000)

        page.wait_for_timeout(10000)

        # 全ての要素からテキストを取得
        messages = page.evaluate("""
            () => {
                const items = document.querySelectorAll('._message, .chatTimeLine__item, [data-testid*="message"], li[id*="message"]');
                let results = [];
                items.forEach(el => {
                    const text = el.innerText || '';
                    if (text.trim().length > 0 && !text.includes('Enterで送信') && !text.includes('検索')) {
                        results.push(text.trim());
                    }
                });
                if (results.length === 0) {
                    // フォールバック: ページ全体の段落やli
                    const allEls = document.querySelectorAll('p, li, div');
                    allEls.forEach(el => {
                        const t = el.innerText || '';
                        if (t.length > 10 && t.length < 500 && !results.includes(t)) {
                            results.push(t.trim());
                        }
                    });
                }
                return results;
            }
        """)

        browser.close()
        return messages

def main():
    print("チャットメッセージを取得中...")
    raw_messages = get_messages()
    print(f"取得したメッセージ数: {len(raw_messages)}")

    if not raw_messages:
        print("書き出すメッセージがありませんでした。")
        return

    service = get_sheets_service()
    
    values = [["No.", "メッセージ内容"]]
    for i, msg in enumerate(raw_messages[:100], start=1): # 上位100件
        values.append([str(i), msg])

    body = {
        'values': values
    }
    
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

    print(f"スプレッドシート（ID: {SPREADSHEET_ID}）の「{SHEET_NAME}」シートへの書き出しが完了しました！")

if __name__ == "__main__":
    main()
