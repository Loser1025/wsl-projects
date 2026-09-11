"""
KDDI Chatwork (rid445630230) からメッセージ・リアクションを取得し、
既存の指定スプレッドシートに書き出すスクリプト

本文・送信者・日時・メンバー名は公式API (api.chatwork.com) から取得。
リアクションは公式APIに存在しないため、Playwrightでログインし
Chatwork内部API (gateway/load_chat.php, load_old_chat.php) の
レスポンスを傍受して取得する（非公開API。Chatwork側のUI変更で
動かなくなる可能性がある点に注意）。

列構成: A=message_id(重複チェック用), B=日付, C=送信者, D=内容, E=リアクション
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
from google.oauth2 import service_account
from googleapiclient.discovery import build

try:
    from config_auth import CW_API_TOKEN, CW_EMAIL, CW_PASSWORD
except ImportError:
    CW_API_TOKEN = os.environ.get("CW_API_TOKEN", "")
    CW_EMAIL = os.environ.get("CW_EMAIL", "")
    CW_PASSWORD = os.environ.get("CW_PASSWORD", "")

CW_ROOM_ID = 445630230
ROOM_URL = f"https://kcw.kddi.ne.jp/#!rid{CW_ROOM_ID}"
COOKIE_FILE = Path(__file__).parent / "chatwork_cookies.json"

SPREADSHEET_ID = "11RAnfeZZPS8dF6llHV7T2FOd2shSdPgiBdmzeMU4sQo"
SHEET_NAME = "シート1"
SA_PATH = os.path.join(os.path.dirname(__file__), "../../google-workspace-mcp/credentials.json")
JST = timezone(timedelta(hours=9))

# Chatworkのプリセットリアクションのみ日本語キャプションが存在する。
# それ以外の絵文字リアクションは種別コードをそのまま表示する。
REACTION_CAPTIONS = {
    "roger": "了解",
    "bow": "ありがとう",
    "cracker": "おめでとう",
    "dance": "わーい",
    "clap": "すごい",
    "yes": "いいね",
}


def get_sheets_service():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=scopes
        )
    else:
        creds = service_account.Credentials.from_service_account_file(SA_PATH, scopes=scopes)
    return build("sheets", "v4", credentials=creds)


def fetch_cw_messages(force=1):
    """Chatwork公式APIからメッセージ取得（最新100件）"""
    url = f"https://api.chatwork.com/v2/rooms/{CW_ROOM_ID}/messages"
    headers = {"X-ChatWorkToken": CW_API_TOKEN}
    resp = requests.get(url, headers=headers, params={"force": force})
    resp.raise_for_status()
    return resp.json()


def fetch_room_members():
    """Chatwork公式APIでルームメンバーのaccount_id→名前を取得（リアクション表示用）"""
    url = f"https://api.chatwork.com/v2/rooms/{CW_ROOM_ID}/members"
    headers = {"X-ChatWorkToken": CW_API_TOKEN}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return {str(m["account_id"]): m["name"] for m in resp.json()}


def format_reactions(reactions, member_names):
    if not reactions:
        return ""
    parts = []
    for r in reactions:
        label = REACTION_CAPTIONS.get(r["reaction_type"], r["reaction_type"])
        names = [member_names.get(str(a["id"]), str(a["id"])) for a in r.get("accounts", [])]
        parts.append(f"{label}({len(names)}):{'/'.join(names)}")
    return "、".join(parts)


def _merge_reactions(reaction_map, chat_list):
    for item in chat_list:
        if item.get("reactions"):
            reaction_map[str(item["id"])] = item["reactions"]


def _find_scroll_target(page):
    return page.evaluate("""
        () => {
            const el = document.querySelector('._message');
            let node = el;
            while (node && node !== document.body) {
                const style = getComputedStyle(node);
                if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && node.scrollHeight > node.clientHeight) {
                    const r = node.getBoundingClientRect();
                    return { x: r.x + r.width / 2, y: r.y + 50 };
                }
                node = node.parentElement;
            }
            return null;
        }
    """)


def _login(page):
    page.wait_for_selector("#username", timeout=15000)
    page.fill("#username", CW_EMAIL)
    page.click("button[type='submit']")
    page.wait_for_selector("input[type='password']", state="attached", timeout=30000)
    page.wait_for_timeout(2000)
    page.evaluate(
        "document.querySelectorAll('input[type=\"password\"]').forEach(el => { el.classList.remove('hide'); el.style.display = ''; el.style.visibility = 'visible'; })"
    )
    page.fill("input[type='password']", CW_PASSWORD)
    page.click("button[type='submit']")
    page.wait_for_timeout(8000)


def fetch_reactions(min_message_id, headless=True, max_scroll_seconds=90):
    """Playwrightでログインし、内部API(load_chat.php/load_old_chat.php)の
    レスポンスからmessage_id単位のリアクションを収集する。
    min_message_id以前のメッセージに到達するまで画面を遡ってスクロールする。

    1回のスクロール操作（数千px）ではコンテナ上端の「過去メッセージ読み込み」
    トリガー地点に届かないことが多いため、レスポンスを都度待つのではなく
    バックグラウンドで収集しつつ、時間予算内はスクロールを継続する"""
    reaction_map = {}
    import time

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        # CI(Dockerコンテナ)のデフォルトviewportは1280x720で、狭いと
        # Chatwork側のレイアウトが変わりスクロール対象の検出に失敗することがあるため固定する
        context = browser.new_context(viewport={"width": 1920, "height": 1080})

        if COOKIE_FILE.exists():
            try:
                context.add_cookies(json.loads(COOKIE_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass

        page = context.new_page()

        # load_old_chat.phpのレスポンスはバックグラウンドで常時収集しておき、
        # スクロールのたびに逐一待ち受けない（1回のスクロールでは上端に届かず
        # 応答が来ないことが多いため、待ち受け式だと毎回無駄にタイムアウトする）
        old_chat_batches = []

        def _on_response(response):
            if "load_old_chat.php" in response.url:
                try:
                    old_chat_batches.append(response.json()["result"]["chat_list"])
                except Exception:
                    pass

        page.on("response", _on_response)

        resp = None
        try:
            with page.expect_response(lambda r: "load_chat.php" in r.url, timeout=45000) as resp_info:
                page.goto(ROOM_URL, wait_until="commit", timeout=30000)
            resp = resp_info.value
        except Exception as e:
            print(f"  [debug] 初回load_chat.php待ちタイムアウト: {e}")
            resp = None

        if "auth.chatwork.com" in page.url or page.locator("#username").is_visible():
            print("  [debug] Cookie無効のためログインします")
            _login(page)
            cookies = context.cookies()
            COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
            resp = None
            try:
                with page.expect_response(lambda r: "load_chat.php" in r.url, timeout=45000) as resp_info:
                    page.goto(ROOM_URL, wait_until="commit", timeout=30000)
                resp = resp_info.value
            except Exception as e:
                print(f"  [debug] ログイン後load_chat.php待ちタイムアウト: {e}")
                resp = None

        # 既にログイン済み(Cookie有効)なのにload_chat.phpが検知できなかった場合、
        # ページをリロードすると確実に再取得できることが多いため最後にもう一度試す
        if resp is None:
            print("  [debug] リロードで再試行します")
            try:
                with page.expect_response(lambda r: "load_chat.php" in r.url, timeout=30000) as resp_info:
                    page.reload(wait_until="commit", timeout=30000)
                resp = resp_info.value
            except Exception as e:
                print(f"  [debug] リロード後も取得できませんでした: {e}")
                resp = None

        if resp is None:
            browser.close()
            return reaction_map

        chat_list = resp.json()["result"]["chat_list"]
        _merge_reactions(reaction_map, chat_list)
        earliest_id = min((int(c["id"]) for c in chat_list), default=0)

        page.wait_for_selector("._message", timeout=15000)
        rect = _find_scroll_target(page)
        print(f"  [debug] scroll target: {rect}, 初回earliest_id={earliest_id}, 目標min_id={min_message_id}")

        start = time.time()
        batches_processed = 0
        scroll_batches = 0
        stalled_batches = 0
        page.mouse.move(rect["x"], rect["y"]) if rect else None

        while rect and earliest_id > min_message_id and (time.time() - start) < max_scroll_seconds:
            scroll_batches += 1
            for _ in range(5):
                page.mouse.wheel(0, -800)
                page.wait_for_timeout(200)

            while batches_processed < len(old_chat_batches):
                chat_list2 = old_chat_batches[batches_processed]
                batches_processed += 1
                if not chat_list2:
                    continue
                _merge_reactions(reaction_map, chat_list2)
                new_earliest = min(int(c["id"]) for c in chat_list2)
                if new_earliest < earliest_id:
                    earliest_id = new_earliest
                    stalled_batches = 0

            # コンテナの一番上まで到達したら、それ以上遡れるものがない
            scroll_top = page.evaluate("""
                () => {
                    const el = document.querySelector('._message');
                    let node = el;
                    while (node && node !== document.body) {
                        const style = getComputedStyle(node);
                        if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && node.scrollHeight > node.clientHeight) {
                            return node.scrollTop;
                        }
                        node = node.parentElement;
                    }
                    return null;
                }
            """)
            if scroll_top is not None and scroll_top <= 0:
                print("  [debug] コンテナの一番上まで到達（これ以上の履歴なし）")
                break

            stalled_batches += 1
            if stalled_batches > 30:
                print("  [debug] 一定回数スクロールしても進捗なし、打ち切り")
                break

        print(f"  [debug] スクロール{scroll_batches}回(応答{batches_processed}件処理)、"
              f"最終earliest_id={earliest_id}, 経過{time.time()-start:.1f}秒")
        browser.close()

    return reaction_map


def ensure_header(service):
    header = ["message_id", "日付", "送信者", "内容", "リアクション"]
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:E1"
    ).execute()
    values = result.get("values", [])
    if not values or values[0] != header:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:E1",
            valueInputOption="RAW",
            body={"values": [header]}
        ).execute()


def backfill_reactions(service, reaction_map, member_names, message_id_to_row):
    data = []
    for mid, reactions in reaction_map.items():
        row = message_id_to_row.get(mid)
        if row:
            data.append({
                "range": f"{SHEET_NAME}!E{row}",
                "values": [[format_reactions(reactions, member_names)]]
            })
    if data:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "RAW", "data": data}
        ).execute()


def main():
    print("Google Sheetsに接続中...")
    service = get_sheets_service()
    ensure_header(service)

    print("既存のmessage_idを取得中...")
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:A"
    ).execute()
    values = result.get("values", [])
    message_id_to_row = {row[0]: i + 2 for i, row in enumerate(values[1:]) if row}
    existing_ids = set(message_id_to_row.keys())
    print(f"  既存: {len(existing_ids)}件")

    print("チャットワークからメッセージ取得中...")
    messages = fetch_cw_messages(force=1)
    print(f"  取得: {len(messages)}件")

    print("メンバー一覧を取得中...")
    member_names = fetch_room_members()

    print("リアクションを取得中（ブラウザでログインします）...")
    # 今回取得したAPI分だけでなく、シートに既にある一番古いメッセージまで
    # 遡ってスクロールすることで、過去メッセージのリアクションも更新対象にする
    api_min_id = min((int(m["message_id"]) for m in messages), default=0)
    sheet_min_id = min((int(mid) for mid in existing_ids), default=api_min_id)
    min_id = min(api_min_id, sheet_min_id)
    try:
        reaction_map = fetch_reactions(min_id)
        print(f"  リアクション付きメッセージ: {len(reaction_map)}件")
    except Exception as e:
        print(f"  [WARN] リアクション取得に失敗しました: {e}")
        reaction_map = {}

    new_rows = []
    for msg in sorted(messages, key=lambda m: int(m["send_time"])):
        mid = msg["message_id"]
        if mid in existing_ids:
            continue
        dt = datetime.fromtimestamp(msg["send_time"], tz=JST).strftime("%Y/%m/%d %H:%M:%S")
        sender = msg["account"]["name"]
        body = msg["body"]
        reaction_str = format_reactions(reaction_map.get(mid), member_names)
        new_rows.append([mid, dt, sender, body, reaction_str])

    if new_rows:
        print(f"新規: {len(new_rows)}件を書き出し中...")
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A:E",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": new_rows}
        ).execute()
        print(f"完了: {len(new_rows)}件を追記しました。")
    else:
        print("新規メッセージなし。")

    print("既存行のリアクションを更新中...")
    backfill_reactions(service, reaction_map, member_names, message_id_to_row)
    print("完了しました。")


if __name__ == "__main__":
    main()
