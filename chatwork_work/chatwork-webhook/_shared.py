"""
Chatwork -> Google Sheets 連携の共通ロジック。
api/run.py から使う。

旧 chatwork_work/chatwork-to-sheet/export_to_sheet.py からリアクション取得
(Cookie/Playwright/内部API依存)を除いたもの。公式REST APIのみで完結する。

日付が変わるたびに「テンプレ」シートを複製してその日専用のシート
(タブ名 MM/DD)を作り、そこにその日のメッセージだけを書き込んでいく。
過去日のシートは削除・上書きせずそのまま残す。
"""

import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

CW_API_TOKEN = os.environ.get("CW_API_TOKEN", "")
CW_ROOM_ID = int(os.environ.get("CW_ROOM_ID", "445630230"))
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "11RAnfeZZPS8dF6llHV7T2FOd2shSdPgiBdmzeMU4sQo")
TEMPLATE_SHEET_NAME = os.environ.get("TEMPLATE_SHEET_NAME", "テンプレ")

JST = timezone(timedelta(hours=9))

_URL_RE = re.compile(r"https?://[\w\-._~:/?#\[\]@!$&'()*+,;=%]+")
_TEACHER_RE = re.compile(r"面談対応\(先生\)[:：]\s*(.+)")
_CS_RE = re.compile(r"対応者\(CS\)[:：]\s*(.+)")


def get_sheets_service():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    sa_json = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
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


def _list_sheets(service):
    meta = service.spreadsheets().get(
        spreadsheetId=SPREADSHEET_ID,
        fields="sheets.properties(sheetId,title,gridProperties.rowCount)"
    ).execute()
    return [s["properties"] for s in meta["sheets"]]


def daily_sheet_name(date):
    return date.strftime("%m/%d")


def get_or_create_daily_sheet(service, date):
    """その日専用のシート(タブ名 MM/DD)のsheetIdを返す。無ければ「テンプレ」を
    複製して作る（書式・条件付き書式・チェックボックスもテンプレのまま引き継がれる）"""
    name = daily_sheet_name(date)
    sheets = _list_sheets(service)

    existing = next((s for s in sheets if s["title"] == name), None)
    if existing:
        return existing["sheetId"], name

    template = next((s for s in sheets if s["title"] == TEMPLATE_SHEET_NAME), None)
    if not template:
        raise RuntimeError(f"テンプレートシート「{TEMPLATE_SHEET_NAME}」が見つかりません")

    resp = service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [{
            "duplicateSheet": {
                "sourceSheetId": template["sheetId"],
                "newSheetName": name,
            }
        }]}
    ).execute()
    new_sheet_id = resp["replies"][0]["duplicateSheet"]["properties"]["sheetId"]
    return new_sheet_id, name


def apply_url_links(service, sheet_id, rows_with_body):
    """[(行番号, 本文), ...] のD列にURLリンクのtextFormatRunsを適用する"""
    requests_body = []
    for row_number, body in rows_with_body:
        runs = _link_runs_for_urls(body)
        if not runs:
            continue
        requests_body.append({
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
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


def ensure_min_rows(service, sheet_id, min_rows):
    """values.update()は範囲がグリッドの行数を超えるとエラーになる
    (appendと違い自動では広がらない)ため、書き込み前に必要な行数を確保する"""
    sheets = _list_sheets(service)
    props = next(s for s in sheets if s["sheetId"] == sheet_id)
    current_rows = props["gridProperties"]["rowCount"]
    if current_rows < min_rows:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"requests": [{
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"rowCount": min_rows + 200}},
                    "fields": "gridProperties.rowCount"
                }
            }]}
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


def write_new_rows(service, sheet_name, sheet_id, message_id_to_row, new_rows):
    if not new_rows:
        return 0
    # values.append()の「テーブル自動検出」はシート全体の書式・行数に引きずられて
    # 挿入位置が大きくずれることがあったため使わない。A列から得た実際の最終行を
    # 根拠に、書き込み範囲を自分で明示的に計算する
    next_row = max(message_id_to_row.values(), default=1) + 1
    ensure_min_rows(service, sheet_id, next_row + len(new_rows) - 1)
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A{next_row}:G{next_row + len(new_rows) - 1}",
        valueInputOption="RAW",
        body={"values": new_rows}
    ).execute()
    apply_url_links(service, sheet_id, [(next_row + i, row[3]) for i, row in enumerate(new_rows)])
    return len(new_rows)
