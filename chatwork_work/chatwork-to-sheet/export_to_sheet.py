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
import re
import time
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
SHEET_ID = 0
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


_URL_RE = re.compile(r"https?://[\w\-._~:/?#\[\]@!$&'()*+,;=%]+")


def _link_runs_for_urls(text):
    """本文中のURL部分だけをクリック可能なリンクにするtextFormatRunsを作る。
    URLが無ければNoneを返す（セル全体をUSER_ENTEREDにしても文章中に埋め込まれた
    URLは自動リンク化されない＝セル全体がURLの場合のみ効くため、明示的に指定する）"""
    matches = list(_URL_RE.finditer(text))
    if not matches:
        return None
    runs = []
    pos = 0
    for m in matches:
        if m.start() > pos:
            runs.append({"startIndex": pos, "format": {}})
        runs.append({"startIndex": m.start(), "format": {"link": {"uri": m.group(0)}}})
        pos = m.end()
    if pos < len(text):
        runs.append({"startIndex": pos, "format": {}})
    return runs


def apply_url_links(service, rows_with_body):
    """[(行番号, 本文), ...] のD列にURLリンクのtextFormatRunsを適用する"""
    requests_body = []
    for row_number, body in rows_with_body:
        runs = _link_runs_for_urls(body)
        if not runs:
            continue
        requests_body.append({
            "updateCells": {
                "range": {
                    "sheetId": SHEET_ID,
                    "startRowIndex": row_number - 1,
                    "endRowIndex": row_number,
                    "startColumnIndex": 3,
                    "endColumnIndex": 4
                },
                "rows": [{"values": [{"textFormatRuns": runs}]}],
                "fields": "textFormatRuns"
            }
        })
    if requests_body:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": requests_body}
        ).execute()


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


def _refresh_cookies_via_browser():
    """PlaywrightでKDDI Chatworkにログインし、Cookieファイルを更新する。
    Cookieが有効な間はrequestsだけで完結するので、この関数は
    Cookie切れ時のフォールバックとしてのみ呼ばれる"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        if COOKIE_FILE.exists():
            try:
                context.add_cookies(json.loads(COOKIE_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass
        page = context.new_page()
        page.goto(ROOM_URL, wait_until="commit", timeout=30000)
        page.wait_for_timeout(3000)
        if "auth.chatwork.com" in page.url or page.locator("#username").is_visible():
            _login(page)
        cookies = context.cookies()
        COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()


def _build_cookie_jar():
    if not COOKIE_FILE.exists():
        return requests.cookies.RequestsCookieJar()
    try:
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return requests.cookies.RequestsCookieJar()
    jar = requests.cookies.RequestsCookieJar()
    for c in cookies:
        jar.set(c["name"], c["value"], domain=c.get("domain", "").lstrip("."), path=c.get("path", "/"))
    return jar


def _fetch_token_and_myid(session):
    """トップページの生HTMLに埋め込まれているACCESS_TOKEN/MYIDを正規表現で抜き出す。
    ブラウザでJSを実行しなくても、Cookieが有効ならこれだけで内部APIを叩ける"""
    resp = session.get("https://kcw.kddi.ne.jp/", timeout=15)
    token_m = re.search(r"ACCESS_TOKEN\s*=\s*'([^']+)'", resp.text)
    myid_m = re.search(r"MYID\s*=\s*'?(\d+)'?", resp.text)
    if not token_m or not myid_m:
        return None, None
    return token_m.group(1), myid_m.group(1)


def _call_internal_api(session, myid, token, endpoint, extra_params):
    params = {"myid": myid, "_v": "1.80a", "_av": "5", "ln": "ja"}
    params.update(extra_params)
    data = {"pdata": json.dumps({"load_file_version": "2", "_t": token})}
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Referer": ROOM_URL,
        "Accept": "application/json, text/plain, */*",
    }
    resp = session.post(
        f"https://kcw.kddi.ne.jp/gateway/{endpoint}",
        params=params, data=data, headers=headers, timeout=15
    )
    resp.raise_for_status()
    return resp.json()["result"]["chat_list"]


def fetch_reactions(min_message_id, max_seconds=60):
    """requestsだけで内部API(load_chat.php/load_old_chat.php)を呼び出し、
    message_id単位のリアクションを収集する。Cookieが無効な場合のみ
    Playwrightでログインし直す（通常運用ではブラウザ起動が発生しない）"""
    reaction_map = {}

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36",
    })
    session.cookies = _build_cookie_jar()

    token, myid = _fetch_token_and_myid(session)
    if not token:
        print("  [debug] Cookie無効のためPlaywrightでログインします")
        _refresh_cookies_via_browser()
        session.cookies = _build_cookie_jar()
        token, myid = _fetch_token_and_myid(session)
        if not token:
            print("  [debug] ログイン後もトークン取得に失敗しました")
            return reaction_map

    start = time.time()
    try:
        chat_list = _call_internal_api(session, myid, token, "load_chat.php", {
            "room_id": str(CW_ROOM_ID), "last_chat_id": "0", "unread_num": "0",
            "bookmark": "1", "desc": "1"
        })
    except Exception as e:
        print(f"  [debug] load_chat.php呼び出しに失敗: {e}")
        return reaction_map

    _merge_reactions(reaction_map, chat_list)
    earliest_id = min((int(c["id"]) for c in chat_list), default=0)

    batches = 0
    while earliest_id > min_message_id and (time.time() - start) < max_seconds:
        batches += 1
        try:
            chat_list2 = _call_internal_api(session, myid, token, "load_old_chat.php", {
                "room_id": str(CW_ROOM_ID), "first_chat_id": str(earliest_id)
            })
        except Exception as e:
            print(f"  [debug] load_old_chat.php {batches}回目で失敗: {e}")
            break
        if not chat_list2:
            break
        _merge_reactions(reaction_map, chat_list2)
        new_earliest = min(int(c["id"]) for c in chat_list2)
        if new_earliest >= earliest_id:
            break
        earliest_id = new_earliest

    print(f"  [debug] load_old_chat.php {batches}回、最終earliest_id={earliest_id}、"
          f"経過{time.time()-start:.1f}秒")
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


def ensure_min_rows(service, min_rows):
    """values.update()は範囲がグリッドの行数を超えるとエラーになる
    (appendと違い自動では広がらない)ため、書き込み前に必要な行数を確保する"""
    meta = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        fields="sheets.properties(sheetId,gridProperties.rowCount)"
    ).execute()
    props = next(s["properties"] for s in meta["sheets"] if s["properties"]["sheetId"] == SHEET_ID)
    current_rows = props["gridProperties"]["rowCount"]
    if current_rows < min_rows:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{
                "updateSheetProperties": {
                    "properties": {"sheetId": SHEET_ID, "gridProperties": {"rowCount": min_rows + 200}},
                    "fields": "gridProperties.rowCount"
                }
            }]}
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
        range=f"{SHEET_NAME}!A:B"
    ).execute()
    values = result.get("values", [])
    message_id_to_row = {row[0]: i + 2 for i, row in enumerate(values[1:]) if row}
    existing_ids = set(message_id_to_row.keys())

    today = datetime.now(JST).date()
    today_prefix = today.strftime("%Y/%m/%d")
    today_existing_ids = {
        row[0] for row in values[1:]
        if row and len(row) >= 2 and row[1].startswith(today_prefix)
    }
    print(f"  既存: {len(existing_ids)}件（本日分: {len(today_existing_ids)}件）")

    # 日付が変わった後の初回実行(本日分がまだ0件)は、前日以前のデータを削除する
    if existing_ids and not today_existing_ids:
        print("日付が変わったため、前日以前のデータを削除します...")
        service.spreadsheets().values().clear(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A2:H100000",
            body={}
        ).execute()
        message_id_to_row = {}
        existing_ids = set()
        print("  削除完了")

    print("チャットワークからメッセージ取得中...")
    all_messages = fetch_cw_messages(force=1)
    messages = [
        m for m in all_messages
        if datetime.fromtimestamp(int(m["send_time"]), tz=JST).date() == today
    ]
    print(f"  取得: {len(all_messages)}件（本日分: {len(messages)}件）")

    print("メンバー一覧を取得中...")
    member_names = fetch_room_members()

    print("リアクションを取得中（ブラウザでログインします）...")
    # 本日分のメッセージ（API取得分・シート既存分の両方）のうち
    # 一番古いものまで遡ってスクロールする。日をまたいだ過去分は対象にしない
    # （日が経つほどスクロール量が際限なく増えるのを防ぐため）
    candidates = [int(m["message_id"]) for m in messages]
    candidates += [int(mid) for mid in today_existing_ids]
    min_id = min(candidates) if candidates else float("inf")
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
        # values.append()の「テーブル自動検出」はE〜H列の書式やシート全体の
        # 行数(バンディング/条件付き書式で広げた範囲)に引きずられて挿入位置が
        # 大きくずれることがあったため使わない。A列を読んで得た実際の最終行
        # (message_id_to_row)を根拠に、書き込み範囲を自分で明示的に計算する
        next_row = max(message_id_to_row.values(), default=1) + 1
        ensure_min_rows(service, next_row + len(new_rows) - 1)
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A{next_row}:E{next_row + len(new_rows) - 1}",
            valueInputOption="RAW",
            body={"values": new_rows}
        ).execute()
        # D列(内容)に含まれるURLをクリック可能なリンクにする
        apply_url_links(service, [(next_row + i, row[3]) for i, row in enumerate(new_rows)])
        print(f"完了: {len(new_rows)}件を追記しました。")
    else:
        print("新規メッセージなし。")

    print("既存行のリアクションを更新中...")
    backfill_reactions(service, reaction_map, member_names, message_id_to_row)
    print("完了しました。")


if __name__ == "__main__":
    main()
