"""
単一エントリポイント。外部cron(GAS)から ?job=poll (1分毎) / ?job=reset (1日1回) の
クエリパラメータで呼び分ける。

日付が変わると「テンプレ」シートを複製してその日専用のシート(タブ名 MM/DD)を
作り、そこにその日のメッセージだけを書き込む。過去日のシートは削除しない。
"""

import os
import sys
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _shared import (  # noqa: E402
    JST, SPREADSHEET_ID, get_sheets_service, fetch_cw_messages,
    get_or_create_daily_sheet, build_new_rows, write_new_rows,
)

POLL_SECRET = os.environ.get("POLL_SECRET", "")


def run_poll():
    service = get_sheets_service()
    today = datetime.now(JST).date()
    sheet_id, sheet_name = get_or_create_daily_sheet(service, today)

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{sheet_name}!A:A"
    ).execute()
    values = result.get("values", [])
    message_id_to_row = {row[0]: i + 2 for i, row in enumerate(values[1:]) if row and row[0]}
    existing_ids = set(message_id_to_row.keys())

    all_messages = fetch_cw_messages()
    _today_msgs, new_rows = build_new_rows(all_messages, today, existing_ids)
    written = write_new_rows(service, sheet_name, sheet_id, message_id_to_row, new_rows)

    return {"job": "poll", "sheet": sheet_name, "fetched": len(all_messages), "written": written}


def run_daily_reset():
    """安全ネット。poll側で毎回その日のシート有無を確認しているので必須では
    ないが、pollが長時間呼ばれなかった場合に備えてこちらでも作成しておく"""
    service = get_sheets_service()
    today = datetime.now(JST).date()
    sheet_id, sheet_name = get_or_create_daily_sheet(service, today)
    return {"job": "reset", "sheet": sheet_name, "sheet_id": sheet_id}


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
