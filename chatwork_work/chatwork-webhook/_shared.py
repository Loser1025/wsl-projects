"""
Chatwork -> Google Sheets 連携の共通ロジック。
api/poll.py と api/daily_reset.py の両方から使う。

旧 chatwork_work/chatwork-to-sheet/export_to_sheet.py からリアクション取得
(Cookie/Playwright/内部API依存)を除いたもの。公式REST APIのみで完結する。
"""

import os
import re
import requests
from datetime import datetime, timezone, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

CW_API_TOKEN = os.environ.get("CW_API_TOKEN", "")
CW_ROOM_ID = int(os.environ.get("CW_ROOM_ID", "445630230"))
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "11RAnfeZZPS8dF6llHV7T2FOd2shSdPgiBdmzeMU4sQo")
SHEET_NAME = os.environ.get("SHEET_NAME", "シート1")
SHEET_ID = int(os.environ.get("SHEET_ID", "0"))
CHECK_COLUMN = os.environ.get("CHECK_COLUMN", "I")

JST = timezone(timedelta(hours=9))

HEADER = ["message_id", "日付", "送信者", "内容", "面談対応(先生)", "対応者(CS)", "リアクション"]

_URL_RE = re.compile(r"https?://[\w\-._~:/?#\[\]@!$&'()*+,;=%]+")
_TEACHER_RE = re.compile(r"面談対応\(先生\)[:：]\s*(.+)")
_CS_RE = re.compile(r"対応者\(CS\)[:：]\s*(.+)")


def get_sheets_service():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    sa_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    import json
    creds = service_account.Credentials.from_service_account_info(json.loads(sa_json), scopes=scopes)
    return build("sheets", "v4", credentials=creds)


def fetch_cw_messages(force=1):
    """Chatwork公式APIからメッセージ取得（最新100件）"""
    url = f"https://api.chatwork.com/v2/rooms/{CW_ROOM_ID}/messages"
    headers = {"X-ChatWorkToken": CW_API_TOKEN}
    resp = requests.get(url, headers=headers, params={"force": force}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _extract_field(body, pattern):
    m = pattern.search(body)
    return m.group(1).strip() if m else ""


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


def ensure_header(service):
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:G1"
    ).execute()
    values = result.get("values", [])
    if not values or values[0] != HEADER:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:G1",
            valueInputOption="RAW",
            body={"values": [HEADER]}
        ).execute()


def _get_row_count(service):
    meta = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        fields="sheets.properties(sheetId,gridProperties.rowCount)"
    ).execute()
    props = next(s["properties"] for s in meta["sheets"] if s["properties"]["sheetId"] == SHEET_ID)
    return props["gridProperties"]["rowCount"]


def ensure_min_rows(service, min_rows):
    """values.update()は範囲がグリッドの行数を超えるとエラーになる
    (appendと違い自動では広がらない)ため、書き込み前に必要な行数を確保する"""
    current_rows = _get_row_count(service)
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


def clear_previous_day_and_reset_checkboxes(service):
    """前日以前のデータを削除する。I列(処理完了チェック)だけは値クリアで終わらせず、
    明示的にFALSEを敷き詰め直す（クリアだけだと空セルになり、値としてのFALSEにはならない）"""
    service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A2:Z100000",
        body={}
    ).execute()

    row_count = _get_row_count(service)
    if row_count >= 2:
        values = [[False] for _ in range(row_count - 1)]
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!{CHECK_COLUMN}2:{CHECK_COLUMN}{row_count}",
            valueInputOption="RAW",
            body={"values": values}
        ).execute()


def build_new_rows(all_messages, today, existing_ids):
    """本日分かつ未追記のメッセージから、シートに書き込む行データを作る"""
    messages = [
        m for m in all_messages
        if datetime.fromtimestamp(int(m["send_time"]), tz=JST).date() == today
    ]
    new_rows = []
    for msg in sorted(messages, key=lambda m: int(m["send_time"])):
        mid = msg["message_id"]
        if mid in existing_ids:
            continue
        dt = datetime.fromtimestamp(msg["send_time"], tz=JST).strftime("%Y/%m/%d %H:%M:%S")
        sender = msg["account"]["name"]
        body = msg["body"]
        teacher = _extract_field(body, _TEACHER_RE)
        cs = _extract_field(body, _CS_RE)
        new_rows.append([mid, dt, sender, body, teacher, cs, ""])
    return messages, new_rows


def write_new_rows(service, message_id_to_row, new_rows):
    if not new_rows:
        return 0
    # values.append()の「テーブル自動検出」はシート全体の書式・行数に引きずられて
    # 挿入位置が大きくずれることがあったため使わない。A列から得た実際の最終行を
    # 根拠に、書き込み範囲を自分で明示的に計算する
    next_row = max(message_id_to_row.values(), default=1) + 1
    ensure_min_rows(service, next_row + len(new_rows) - 1)
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A{next_row}:G{next_row + len(new_rows) - 1}",
        valueInputOption="RAW",
        body={"values": new_rows}
    ).execute()
    apply_url_links(service, [(next_row + i, row[3]) for i, row in enumerate(new_rows)])
    return len(new_rows)
