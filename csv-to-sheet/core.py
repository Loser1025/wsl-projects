"""
CSVパース + Google Sheetsへの書き込みロジック
"""
import csv
import io
import json
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

CONFIG_PATH = Path(__file__).parent / 'config.json'
SA_PATH = Path(__file__).parent / 'sa_credentials.json'

SPREADSHEET_ID = '1qw_aL8B9aJ_7Ad58qNxjNexTT20UOKU4LuUsjf3c6eQ'
SHEET_NAME = '流入ごと'
ROW_START = 36


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))


def _sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_PATH),
        scopes=['https://www.googleapis.com/auth/spreadsheets'],
    )
    return build('sheets', 'v4', credentials=creds)


def parse_csv(text: str):
    """CSVテキストをヘッダーと辞書{CSP_ID: row}に変換"""
    text = text.lstrip('\ufeff')  # BOM除去

    reader = csv.reader(io.StringIO(text))
    headers = next(reader)
    data = {}
    for row in reader:
        csp_id = row[0].strip() if row else ''
        if csp_id:
            data[csp_id] = row
    return headers, data


def get_latest_biko(headers: list, row: list, tanto_name: str) -> str:
    """担当者名が一致する最新の備考を返す（なければ最新の備考）"""
    tanto_map = {}
    biko_map = {}
    for i, h in enumerate(headers):
        if h.startswith('対応者') and h[3:].isdigit():
            tanto_map[int(h[3:])] = i
        elif h.startswith('備考') and h[2:].isdigit():
            biko_map[int(h[2:])] = i

    max_n = max(biko_map.keys()) if biko_map else 0

    # 担当者一致優先
    for n in range(max_n, 0, -1):
        bi = biko_map.get(n)
        ti = tanto_map.get(n)
        if bi is None or bi >= len(row):
            continue
        biko = row[bi].strip()
        if not biko:
            continue
        if ti is not None and ti < len(row) and row[ti].strip() == tanto_name:
            return biko

    # フォールバック
    for n in range(max_n, 0, -1):
        bi = biko_map.get(n)
        if bi is None or bi >= len(row):
            continue
        biko = row[bi].strip()
        if biko:
            return biko

    return ''


def process_and_write(csv_text: str, log_fn=None) -> int:
    """CSVテキストを受け取ってシートに書き込む。書き込み件数を返す"""
    def log(msg):
        if log_fn:
            log_fn(msg)

    headers, csv_data = parse_csv(csv_text)
    log(f'CSV解析完了: {len(csv_data)}件')

    service = _sheets_service()
    sheets_api = service.spreadsheets().values()

    # 列Aの最終行を動的に取得（ROW_START行目から末尾まで）
    range_notation = f"'{SHEET_NAME}'!A{ROW_START}:G"
    result = sheets_api.get(spreadsheetId=SPREADSHEET_ID, range=range_notation).execute()
    sheet_rows = result.get('values', [])
    log(f'シート読み込み: {len(sheet_rows)}行 (A{ROW_START}〜)')

    updates = []
    not_found = []

    for i, row in enumerate(sheet_rows):
        csp_id = row[0].strip() if len(row) > 0 else ''
        tanto_name = row[4].strip() if len(row) > 4 else ''

        if not csp_id or not csp_id.isdigit():
            continue

        if csp_id not in csv_data:
            not_found.append(csp_id)
            continue

        biko = get_latest_biko(headers, csv_data[csp_id], tanto_name)
        if biko:
            updates.append({
                'range': f"'{SHEET_NAME}'!G{ROW_START + i}",
                'values': [[biko]],
            })
            preview = biko[:30] + ('...' if len(biko) > 30 else '')
            log(f'[OK] {csp_id} ({tanto_name}): {preview}')
        else:
            log(f'[-] {csp_id} ({tanto_name}): 備考なし')

    if updates:
        body = {'valueInputOption': 'RAW', 'data': updates}
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID, body=body
        ).execute()

    if not_found:
        log(f'[WARN] CSVに未存在: {", ".join(not_found[:10])}{"..." if len(not_found) > 10 else ""}')

    log(f'[完了] {len(updates)}件書き込み')
    return len(updates)
