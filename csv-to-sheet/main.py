"""
CSV → スプレッドシート 備考転記スクリプト
- hibiki.leaduplus.pro からエクスポートしたCSVを読み込み
- スプレッドシートの各案件（CSP番号）に対し、
  担当者名（E列）が一致する最新の備考をG列に書き込む
"""

import csv
import json
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

CONFIG_PATH = Path(__file__).parent / 'config.json'
SA_PATH = Path(__file__).parent / 'sa_credentials.json'


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))


def build_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        str(SA_PATH),
        scopes=['https://www.googleapis.com/auth/spreadsheets'],
    )
    return build('sheets', 'v4', credentials=creds)


def load_csv(csv_path: str):
    """CSVを読み込んでCSP番号をキーにした辞書を返す（文字コード自動判定）"""
    for encoding in ['utf-8-sig', 'cp932', 'shift-jis']:
        try:
            with open(csv_path, newline='', encoding=encoding) as f:
                reader = csv.reader(f)
                headers = next(reader)
                data = {}
                for row in reader:
                    csp_id = row[0].strip() if row else ''
                    if csp_id:
                        data[csp_id] = row
            print(f"CSV読み込み成功 (encoding={encoding}): {len(data)}件")
            return headers, data
        except (UnicodeDecodeError, StopIteration):
            continue
    raise ValueError("CSVの文字コードを特定できませんでした")


def get_latest_biko(headers: list, row: list, tanto_name: str) -> str:
    """
    担当者名が一致する最新の備考を返す。
    一致するものがなければ最新の備考（非空）を返す。
    """
    # ヘッダーから 対応者N と 備考N の列インデックスを収集
    tanto_map = {}  # N -> index
    biko_map = {}   # N -> index
    for i, h in enumerate(headers):
        if h.startswith('対応者') and h[3:].isdigit():
            tanto_map[int(h[3:])] = i
        elif h.startswith('備考') and h[2:].isdigit():
            biko_map[int(h[2:])] = i

    max_n = max(biko_map.keys()) if biko_map else 0

    # 大きいN（最新）から順に検索 - 担当者一致優先
    for n in range(max_n, 0, -1):
        biko_idx = biko_map.get(n)
        tanto_idx = tanto_map.get(n)
        if biko_idx is None or biko_idx >= len(row):
            continue
        biko_val = row[biko_idx].strip()
        if not biko_val:
            continue
        # 担当者が一致すれば即返す
        if tanto_idx is not None and tanto_idx < len(row):
            if row[tanto_idx].strip() == tanto_name:
                return biko_val

    # 担当者一致がなければ、最新の非空備考をフォールバック
    for n in range(max_n, 0, -1):
        biko_idx = biko_map.get(n)
        if biko_idx is None or biko_idx >= len(row):
            continue
        biko_val = row[biko_idx].strip()
        if biko_val:
            return biko_val

    return ''


def main():
    config = load_config()
    csv_path = config['csv_path']
    spreadsheet_id = config['spreadsheet_id']
    sheet_name = config['sheet_name']
    row_start = config.get('row_start', 36)
    row_end = config.get('row_end', 100)

    print("CSV読み込み中...")
    headers, csv_data = load_csv(csv_path)

    print("Google Sheets接続中...")
    service = build_sheets_service()
    sheets_api = service.spreadsheets().values()

    # A36:G100 を取得
    range_notation = f"'{sheet_name}'!A{row_start}:G{row_end}"
    result = sheets_api.get(
        spreadsheetId=spreadsheet_id,
        range=range_notation,
    ).execute()
    sheet_rows = result.get('values', [])

    # G列をクリア
    clear_range = f"'{sheet_name}'!G{row_start}:G{row_end}"
    sheets_api.clear(spreadsheetId=spreadsheet_id, range=clear_range).execute()
    print(f"G列クリア完了 ({clear_range})")

    updates = []
    not_found = []
    no_biko = []

    for i, row in enumerate(sheet_rows):
        sheet_row_num = row_start + i
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
                'range': f"'{sheet_name}'!G{sheet_row_num}",
                'values': [[biko]],
            })
            print(f"  [OK] CSP {csp_id} ({tanto_name}): {biko[:40]}{'...' if len(biko) > 40 else ''}")
        else:
            no_biko.append(csp_id)
            print(f"  [-] CSP {csp_id} ({tanto_name}): bikonashi")

    if updates:
        body = {'valueInputOption': 'RAW', 'data': updates}
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body,
        ).execute()
        print(f"\n[DONE] {len(updates)}件 書き込み完了")
    else:
        print("\n書き込み対象なし")

    if not_found:
        print(f"\n[WARN] CSVに見つからなかったCSP ({len(not_found)}件): {', '.join(not_found)}")
    if no_biko:
        print(f"  備考が空だったCSP ({len(no_biko)}件): {', '.join(no_biko)}")


if __name__ == '__main__':
    main()
