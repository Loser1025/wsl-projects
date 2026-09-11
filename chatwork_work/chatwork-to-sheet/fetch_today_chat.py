"""
Playwright (画面操作ブラウザ自動化) を用いて
https://kcw.kddi.ne.jp/#!rid424170453 にアクセスし、
本日分のチャットメッセージを取得するスクリプト
"""

import os
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))
ROOM_ID = "424170453"
URL = f"https://kcw.kddi.ne.jp/#!rid{ROOM_ID}"
COOKIE_FILE = Path("chatwork_cookies.json")

# ── ログイン情報の設定場所 ──────────────────────────────────────────
# 1. 以下の変数に直接記述するか、
# 2. 環境変数 (CW_EMAIL, CW_PASSWORD) に設定してください
CONFIG_EMAIL = os.environ.get("CW_EMAIL", "your_email@example.com")
CONFIG_PASSWORD = os.environ.get("CW_PASSWORD", "your_password")
# ──────────────────────────────────────────────────────────────────

def get_today_messages(email: str = CONFIG_EMAIL, password: str = CONFIG_PASSWORD, headless: bool = True):
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
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        # ログイン画面に飛ばされた場合の処理
        if "auth.chatwork.com" in page.url or page.locator("#username").is_visible():
            print("ログインが必要です。認証を実行します...")
            if not email or email == "your_email@example.com" or not password or password == "your_password":
                raise RuntimeError("正しいメールアドレスとパスワードを設定してください。")

            print("Chatworkにログイン中...")
            page.fill("#username", email)
            page.click("button[type='submit']")
            
            page.wait_for_selector("input[type='password']", timeout=30000)
            page.evaluate("""
                document.querySelectorAll('input[type=\'password\']').forEach(el => {
                    el.classList.remove('hide');
                    el.style.display = '';
                    el.style.visibility = 'visible';
                });
            """)
            page.fill("input[type='password']", password)
            page.click("button[type='submit']")
            
            # リダイレクト待機
            page.wait_for_function("() => window.location.hostname !== 'auth.chatwork.com'", timeout=60000)
            page.wait_for_timeout(3000)

            # 再度ルームへ
            page.goto(URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)

            # Cookie保存
            cookies = context.cookies()
            COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Cookieを保存しました。")

        print(f"現在のURL: {page.url}")
        
        # メッセージ要素の取得
        try:
            page.wait_for_selector("._message", timeout=15000)
        except Exception:
            print("メッセージ要素が見つかりませんでした。画面のスクリーンショットを保存します。")
            page.screenshot(path="debug_chatwork.png", full_page=True)
            browser.close()
            return []

        messages = []
        message_elements = page.locator("._message").all()
        print(f"取得したメッセージ要素数: {len(message_elements)}")

        for el in message_elements:
            try:
                sender = el.locator("._name, .chatTimeLine__name").inner_text(timeout=500) or "不明"
                text = el.locator("._messageText, .chatTimeLine__message").inner_text(timeout=500) or ""
                time_str = el.locator("._time, .chatTimeLine__time").inner_text(timeout=500) or ""
                
                messages.append({
                    "sender": sender.strip(),
                    "text": text.strip(),
                    "time": time_str.strip()
                })
            except Exception:
                continue

        browser.close()
        print(f"合計 {len(messages)} 件のメッセージを抽出しました。")
        return messages

if __name__ == "__main__":
    msgs = get_today_messages(headless=False)
    for m in msgs[-10:]: # 直近10件を表示
        print(f"[{m['time']}] {m['sender']}: {m['text']}")
