"""
チャットワーク「【響】債務部門・面談結果連携チャット」のメッセージを
Google Sheetsの「CW書き出し」シートに書き出す

列構成: A=message_id(重複チェック用), B=日付, C=送信者, D=内容
"""

import requests
import json
import sys
from datetime import datetime, timezone, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ---- 設定 ----
CW_API_TOKEN = "11be7c90cda7d8ca19954e0867b41a5b"
CW_ROOM_ID = 98813954
SPREADSHEET_ID = "13cK3BhIxFot0cZilbDHa4dzZoH_tocmNYWEk-pTnkJo"
SHEET_NAME = "CW書き出し"
import os as _os
_SA_CANDIDATES = [
    "C:/Users/弁護士法人響/Downloads/ageless-impulse-488713-m6-0c52b81add54.json",
    _os.path.join(_os.path.dirname(__file__), "../csv-to-sheet/sa_credentials.json"),
]
SA_PATH = next((p for p in _SA_CANDIDATES if _os.path.exists(p)), _SA_CANDIDATES[0])
JST = timezone(timedelta(hours=9))


def get_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        SA_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)


def get_existing_message_ids(service):
    """シートにすでに書かれているmessage_idの一覧を取得"""
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:A"
    ).execute()
    values = result.get("values", [])
    # 1行目はヘッダー
    return set(row[0] for row in values[1:] if row)


def fetch_cw_messages(force=1):
    """チャットワークAPIからメッセージ取得（最新100件）"""
    url = f"https://api.chatwork.com/v2/rooms/{CW_ROOM_ID}/messages"
    headers = {"X-ChatWorkToken": CW_API_TOKEN}
    params = {"force": force}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def ensure_header(service):
    """ヘッダー行がなければ追加"""
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1:D1"
    ).execute()
    values = result.get("values", [])
    if not values or values[0] != ["message_id", "日付", "送信者", "内容"]:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A1:D1",
            valueInputOption="RAW",
            body={"values": [["message_id", "日付", "送信者", "内容"]]}
        ).execute()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("Google Sheetsに接続中...")
    service = get_sheets_service()
    ensure_header(service)

    print("既存のmessage_idを取得中...")
    existing_ids = get_existing_message_ids(service)
    print(f"  既存: {len(existing_ids)}件")

    print("チャットワークからメッセージ取得中...")
    messages = fetch_cw_messages(force=1)
    print(f"  取得: {len(messages)}件")

    # 新規メッセージのみ抽出（古い順にソート）
    new_rows = []
    for msg in sorted(messages, key=lambda m: int(m["send_time"])):
        mid = msg["message_id"]
        if mid in existing_ids:
            continue
        dt = datetime.fromtimestamp(msg["send_time"], tz=JST).strftime("%Y/%m/%d %H:%M:%S")
        sender = msg["account"]["name"]
        body = msg["body"]
        new_rows.append([mid, dt, sender, body])

    if not new_rows:
        print("新規メッセージなし。終了します。")
        return

    print(f"新規: {len(new_rows)}件を書き出し中...")
    try:
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAME}!A:D",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": new_rows}
        ).execute()
        print(f"完了: {len(new_rows)}件を追記しました。")
        for row in new_rows[:3]:
            print(f"  {row[1]} | {row[2][:20]} | {row[3][:30]}")
        if len(new_rows) > 3:
            print(f"  ... 他{len(new_rows)-3}件")
    except Exception as e:
        print(f"\n[WARN] Sheets書き込み失敗: {e}")
        print(f"\n── 書き出し予定だった内容（{len(new_rows)}件）──")
        for row in new_rows:
            mid, dt, sender, body = row
            print(f"  message_id={mid}")
            print(f"  日付    : {dt}")
            print(f"  送信者  : {sender}")
            print(f"  内容    : {body}")
            print(f"  {'─'*60}")


if __name__ == "__main__":
    main()
