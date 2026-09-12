"""
単一エントリポイント。外部cronから ?job=poll (1分毎) / ?job=reset (1日1回) の
クエリパラメータで呼び分ける。Vercelの新しいPythonランタイムがapi/配下の
複数ファイルをそれぞれ別関数として自動認識してくれなかったため、1ファイルに
まとめてルーティングする方式にした。
"""

import os
import sys
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _shared import (  # noqa: E402
    JST, SPREADSHEET_ID, SHEET_NAME,
    get_sheets_service, ensure_header, fetch_cw_messages,
    clear_previous_day_and_reset_checkboxes, build_new_rows, write_new_rows,
)

POLL_SECRET = os.environ.get("POLL_SECRET", "")


def run_poll():
    service = get_sheets_service()
    ensure_header(service)

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A:B"
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

    reset = False
    if existing_ids and not today_existing_ids:
        clear_previous_day_and_reset_checkboxes(service)
        message_id_to_row = {}
        existing_ids = set()
        reset = True

    all_messages = fetch_cw_messages()
    _today_msgs, new_rows = build_new_rows(all_messages, today, existing_ids)
    written = write_new_rows(service, message_id_to_row, new_rows)

    return {"job": "poll", "fetched": len(all_messages), "written": written, "daily_reset": reset}


def run_daily_reset():
    """呼ばれるたびに無条件で消すと事故るため、本日分が1件も無い場合だけ実行する
    （poll側と同じ判定。1日に何度叩かれても安全な設計にする）"""
    service = get_sheets_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B:B"
    ).execute()
    values = result.get("values", [])
    today_prefix = datetime.now(JST).date().strftime("%Y/%m/%d")
    has_today = any(row and row[0].startswith(today_prefix) for row in values[1:])
    has_any = any(row for row in values[1:])

    if has_any and not has_today:
        clear_previous_day_and_reset_checkboxes(service)
        return {"job": "reset", "reset": True}
    return {"job": "reset", "reset": False, "reason": "today's data already exists or sheet is empty"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        key = qs.get("key", [""])[0]
        if not POLL_SECRET or key != POLL_SECRET:
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"unauthorized")
            return
        job = qs.get("job", ["poll"])[0]
        try:
            result = run_daily_reset() if job == "reset" else run_poll()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))
