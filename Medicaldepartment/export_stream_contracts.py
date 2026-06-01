"""
Stream貼付シートに当月1日以降の契約データをBigQueryから書き出すスクリプト

出力列（A〜F）:
  A: 契約日
  B: 患者ID
  C: 名前
  D: 商材
  E: 契約メニュー
  F: 合計契約金額/月額料金

処理:
  1. A3:F の既存データをクリア
  2. BQから当月1日以降・契約金額あり・キャンセルなしの契約を取得
  3. A3から順に書き込む

使い方:
  python export_stream_contracts.py
"""
import sys, io, requests, subprocess
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ==================== 設定 ====================
SA_FILE     = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID    = "1Ca6pUgCyA_DVcwHWt3JC_wuwYKFkQKd2x30X8DzKMPw"
SHEET_NAME  = "Stream貼付"
SCOPES      = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
GCLOUD_PATH = r"C:\Users\Loser\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.ps1"
BQ_PROJECT  = "stream-443709"
START_ROW   = 3   # ヘッダー（行2）を残してデータはA3から
# ==============================================


def get_token():
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"& '{GCLOUD_PATH}' auth print-access-token"],
        capture_output=True, text=True, encoding="utf-8"
    )
    token = r.stdout.strip()
    if not token:
        raise RuntimeError("gcloudトークン取得失敗。`gcloud auth login` を実行してください。")
    return token


def bq_query(sql, token, max_results=50000):
    url  = f"https://bigquery.googleapis.com/bigquery/v2/projects/{BQ_PROJECT}/queries"
    body = {"query": sql, "useLegacySql": False, "timeoutMs": 120000, "maxResults": max_results}
    resp = requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body)
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(f"BQエラー: {data.get('error', {}).get('message', data)}")

    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    rows   = data.get("rows", [])

    # ページネーション対応
    page_token = data.get("pageToken")
    while page_token:
        resp2 = requests.get(
            f"https://bigquery.googleapis.com/bigquery/v2/projects/{BQ_PROJECT}/queries/{data.get('jobReference', {}).get('jobId', '')}",
            headers={"Authorization": f"Bearer {token}"},
            params={"pageToken": page_token, "maxResults": max_results}
        )
        page_data = resp2.json()
        rows += page_data.get("rows", [])
        page_token = page_data.get("pageToken")

    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in rows]


def main():
    today = datetime.now()
    month_start = today.strftime("%Y-%m-01")
    print("=" * 55)
    print("Stream貼付 シート書き出しスクリプト")
    print(f"対象期間: {month_start} 〜 当日")
    print("=" * 55)

    # BigQueryからデータ取得
    print("\n[1/3] BigQueryからデータ取得中...")
    token = get_token()

    sql = f"""
SELECT
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_date,
  CAST(c.id AS STRING) AS patient_id,
  CONCAT(c.last_name, ' ', c.first_name) AS name,
  pc.name AS product_class,
  con.menu_name AS menu_name,
  CAST(con.contract_amount AS STRING) AS amount
FROM `stream-443709.stream.contracts` con
JOIN `stream-443709.stream.clients` c ON c.id = con.client_id
LEFT JOIN `stream-443709.stream.product_classes` pc ON pc.id = con.product_class_id
WHERE c.source_code = 'RKR'
  AND DATE(con.contracted_at, 'Asia/Tokyo') >= '{month_start}'
  AND con.contract_amount IS NOT NULL
  AND con.contract_amount > 0
ORDER BY con.contracted_at, con.id
"""
    rows = bq_query(sql, token)
    print(f"  → {len(rows)}件取得")

    if not rows:
        print("  データがありません。終了。")
        return

    # スプレッドシート接続
    print("\n[2/3] 既存データをクリア中...")
    creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    ws    = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    # 既存データ件数を確認してクリア範囲を決定
    existing = ws.col_values(1)  # A列
    last_row = max(len(existing), START_ROW + 10)
    ws.batch_clear([f"A{START_ROW}:F{last_row + 100}"])
    print(f"  → A{START_ROW}:F{last_row + 100} をクリア")

    # 書き込みデータ作成
    print("\n[3/3] シートに書き込み中...")
    write_data = [
        [
            r["contracted_date"] or "",
            r["patient_id"]      or "",
            r["name"]            or "",
            r["product_class"]   or "",
            r["menu_name"]       or "",
            r["amount"]          or "",
        ]
        for r in rows
    ]

    # batch_update で一括書き込み（500行ずつ）
    chunk_size = 500
    for i in range(0, len(write_data), chunk_size):
        chunk   = write_data[i:i + chunk_size]
        row_start = START_ROW + i
        row_end   = row_start + len(chunk) - 1
        ws.update(range_name=f"A{row_start}:F{row_end}", values=chunk, value_input_option="USER_ENTERED")
        print(f"  {min(i + chunk_size, len(write_data))}/{len(write_data)}件 書き込み完了")

    print(f"\n=== 完了 ===")
    print(f"  書き込み件数 : {len(rows)}件")
    print(f"  書き込み範囲 : A{START_ROW}:F{START_ROW + len(rows) - 1}")
    print(f"  対象期間     : {month_start} 〜 {today.strftime('%Y/%m/%d')}")


if __name__ == "__main__":
    main()
