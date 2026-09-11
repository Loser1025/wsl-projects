"""
Playwright を用いて KDDI Chatwork (https://kcw.kddi.ne.jp/#!rid424170453) に
ログインし、本日分のチャットメッセージを取得するスクリプト
"""

import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

try:
    from config_auth import CW_EMAIL, CW_PASSWORD
except ImportError:
    CW_EMAIL = os.environ.get("CW_EMAIL", "")
    CW_PASSWORD = os.environ.get("CW_PASSWORD", "")

JST = timezone(timedelta(hours=9))
ROOM_ID = "424170453"
URL = f"https://kcw.kddi.ne.jp/#!rid{ROOM_ID}"
COOKIE_FILE = Path("chatwork_cookies.json")

def get_today_messages(email: str = CW_EMAIL, password: str = CW_PASSWORD, headless: bool = False):
    today_str = datetime.now(JST).strftime("%Y-%m-%d")
    print(f"=== 本日 ({today_str}) のチャット取得を開始します ===")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()

        # Cookieがあればロード
        if COOKIE_FILE.exists():
            try:
                cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
                context.add_cookies(cookies)
                print("保存されたCookieをロードしました。")
            except Exception as e:
                print(f"Cookieのロードに失敗しました: {e}")

        page = context.new_page()
        print(f"URLにアクセス中: {URL}")
        
        # タイムアウト対策として wait_until="commit" または "networkidle" に設定
        try:
            page.goto(URL, wait_until="commit", timeout=30000)
        except Exception as e:
            print(f"ページ移動時の例外 (続行します): {e}")

        page.wait_for_timeout(5000)

        # ログイン画面に飛ばされた場合
        if "auth.chatwork.com" in page.url or page.locator("#username").is_visible():
            print("ログインが必要です。認証を実行します...")
            if not email or email == "your_email@example.com" or not password or password == "your_password":
                raise RuntimeError("config_auth.py に正しいメールアドレスとパスワードを設定してください。")

            page.wait_for_selector("#username", timeout=15000)
            page.fill("#username", email)
            page.click("button[type='submit']")
            print("メールアドレス送信完了")
            
            page.wait_for_selector("input[type='password']", state="attached", timeout=30000)
            page.wait_for_timeout(2000)
            page.evaluate(
                "document.querySelectorAll('input[type=\"password\"]').forEach(el => { el.classList.remove('hide'); el.style.display = ''; el.style.visibility = 'visible'; })"
            )
            page.fill("input[type='password']", password)
            page.click("button[type='submit']")
            print("パスワード送信完了")
            
            # ログイン完了まで待機
            page.wait_for_timeout(8000)

            # Cookie保存
            cookies = context.cookies()
            COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Cookieを保存しました。")

            # 再度ルームへ移動
            page.goto(URL, wait_until="commit", timeout=30000)
            page.wait_for_timeout(5000)

        print(f"現在のURL: {page.url}")
        
        # チャットメッセージ要素の読み込み待ち
        try:
            page.wait_for_selector("._message, [data-testid*='message'], li[id*='message']", timeout=15000)
        except Exception:
            print("メッセージ要素の待機がタイムアウトしました。画面のスクリーンショットを保存します。")
            page.screenshot(path="debug_chatwork.png", full_page=True)
            browser.close()
            return []

        messages = []
        message_elements = page.locator("._message").all()
        print(f"取得したメッセージ要素数: {len(message_elements)}")

        for el in message_elements:
            try:
                text_content = el.inner_text()
                messages.append({
                    "raw_text": text_content.strip()
                })
            except Exception:
                continue

        browser.close()
        print(f"合計 {len(messages)} 件のメッセージを抽出しました。")
        return messages

if __name__ == "__main__":
    msgs = get_today_messages(headless=False)
    for m in msgs[-10:]:
        print(m['raw_text'])
