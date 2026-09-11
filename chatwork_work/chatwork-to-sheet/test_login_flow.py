from playwright.sync_api import sync_playwright
from config_auth import CW_EMAIL, CW_PASSWORD

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto("https://kcw.kddi.ne.jp/")
    
    print("1. メール入力待機...")
    page.wait_for_selector("#username", timeout=15000)
    page.fill("#username", CW_EMAIL)
    page.click("button[type='submit']")
    print("メール送信完了")
    
    print("2. パスワード入力待機...")
    page.wait_for_selector("input[type='password']", state="attached", timeout=30000)
    page.wait_for_timeout(2000)
    
    # パスワード入力フィールドの表示状態を強制変更して入力
    page.evaluate("""
        document.querySelectorAll('input[type="password"]').forEach(el => {
            el.classList.remove('hide');
            el.style.display = '';
            el.style.visibility = 'visible';
        });
    """)
    page.fill("input[type='password']", CW_PASSWORD)
    page.click("button[type='submit']")
    print("パスワード送信完了")
    
    page.wait_for_timeout(10000)
    print("現在のURL:", page.url)
    browser.close()
