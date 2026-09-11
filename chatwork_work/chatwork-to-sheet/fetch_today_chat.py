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
ROOM_ID = "445630230"
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
        print(f"トップページにアクセス中...")
        page.goto("https://kcw.kddi.ne.jp/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

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

        # 目的のルームへ移動
        print(f"チャットルームへ移動中: {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        print(f"現在のURL: {page.url}")
        
        # チャットメッセージ要素が描画されるのを待つ (Chatworkのメッセージ表示用セレクタ)
        print("チャットメッセージの読み込みを待っています...")
        try:
            page.wait_for_selector("._message, .chatTimeLine__item, [data-testid*='message']", timeout=15000)
        except Exception:
            print("タイムラインの待機がタイムアウトしました。SPAのハッシュルーティングの反映を再試行します...")
            page.reload()
            page.wait_for_timeout(8000)

        # メッセージの抽出
        messages = page.evaluate("""
            () => {
                // Chatworkの個別メッセージブロックを広く検索
                const items = document.querySelectorAll('._message, .chatTimeLine__item, [data-testid*="message"], li[id*="message"]');
                if (items.length > 0) {
                    return Array.from(items).map(el => {
                        return {
                            text: el.innerText || ''
                        };
                    });
                }
                return [];
            }
        """)

        print(f"取得したメッセージ数: {len(messages)}")
        for m in messages[-10:]:
            print("---")
            print(m['text'])

        browser.close()
        return messages

if __name__ == "__main__":
    get_today_messages(headless=False)
