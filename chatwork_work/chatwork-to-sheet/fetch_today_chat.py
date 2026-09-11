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

def get_today_messages(email: str = None, password: str = None, headless: bool = False):
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
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        # ログイン画面に飛ばされた場合の処理
        if "auth.chatwork.com" in page.url or page.locator("#username").is_visible():
            if not email or not password:
                print("ログインが必要です。メールアドレスとパスワードを指定してください。")
                # 対話入力または環境変数から取得
                email = email or os.environ.get("CW_EMAIL")
                password = password or os.environ.get("CW_PASSWORD")
                if not email or not password:
                    raise RuntimeError("ログイン情報（CW_EMAIL, CW_PASSWORD）が設定されていません。")

            print("Chatworkにログイン中...")
            page.fill("#username", email)
            page.click("button[type='submit']")
            
            page.wait_for_selector("input[type='password']", timeout=30000)
            page.evaluate("""
                document.querySelectorAll('input[type='password']').forEach(el => {
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
        
        # メッセージ要素の取得（ChatworkのDOM構造に応じたセレクタ）
        # チャットメッセージアイテムのセレクタ例
        page.wait_for_selector("._message", timeout=15000)
        
        messages = []
        message_elements = page.locator("._message").all()
        print(f"取得したメッセージ要素数: {len(message_elements)}")

        for el in message_elements:
            try:
                # 担当者名 / 本文 / タイムスタンプの取得
                # ※ChatworkのUI構造に合わせたセレクタ
                sender = el.locator(".._name, .chatTimeLine__name").inner_text(timeout=1000) or "不明"
                text = el.locator(".._messageText, .chatTimeLine__message").inner_text(timeout=1000) or ""
                time_str = el.locator(".._time, .chatTimeLine__time").inner_text(timeout=1000) or ""
                
                messages.append({
                    "sender": sender.strip(),
                    "text": text.strip(),
                    "time": time_str.strip()
                })
            except Exception as ex:
                continue

        browser.close()
        print(f"合計 {len(messages)} 件のメッセージを抽出しました。")
        return messages

if __name__ == "__main__":
    # テスト実行用（必要に応じてメールアドレス・パスワードを渡すか環境変数に設定）
    # get_today_messages()
    print("スクリプトテンプレート作成完了しました。")
