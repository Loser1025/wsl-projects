"""
BigQuery REST APIで患者情報を取得してスプレッドシートB-M列を埋める（文字化け対策版）
"""
import sys, io, json, time, calendar, requests
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SA_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME = "2026年5月16日時点未解約データ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
BQ_PROJECT = "stream-443709"
TOKEN_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\gcloud_token.txt"

PAYMENT_MAP = {
    "cash": "現金",
    "wire_transfer": "銀行振込",
    "spot": "スポット",
    "in_house_loan": "分割支払",
    "cc_stripe": "クレジットカード(Stripe)",
    "cc_square": "クレジットカード(Square)",
    "cc_gmo": "クレジットカード(GMO)",
    "cc_stera": "クレジットカード(Stera)",
    "cc_alpha_note": "クレジットカード(アルファノート)",
    "ml_pocketcard": "医療ローン(ポケットカード株式会社)",
    "ml_ryfety": "医療ローン(ライフティ株式会社)",
    "ml_aplus": "医療ローン(アプラス)",
    "ml_ideacard": "医療ローン(アイディアカード)",
    "ml_jplum": "医療ローン(ジェイプラム)",
    "ml_cbsfs": "医療ローン(CBSFS)",
}


def get_token():
    with open(TOKEN_FILE, encoding="ascii") as f:
        return f.read().strip()


def bq_query(sql, token):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{BQ_PROJECT}/queries"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"query": sql, "useLegacySql": False, "timeoutMs": 60000, "maxResults": 10000}
    resp = requests.post(url, headers=headers, json=body)
    data = resp.json()
    if not resp.ok:
        raise Exception(f"BQ error: {data}")
    # ページング対応
    schema_fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    rows = data.get("rows", [])
    results = []
    for row in rows:
        record = {}
        for i, field in enumerate(schema_fields):
            record[field] = row["f"][i].get("v")
        results.append(record)
    return results


def add_one_month(dt_str):
    if not dt_str:
        return ""
    try:
        dt = datetime.strptime(dt_str.strip(), "%Y/%m/%d")
        month = dt.month + 1
        year = dt.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return f"{year}/{month:02d}/{day:02d}"
    except Exception:
        return ""


def format_yen(v):
    try:
        return f"¥{int(float(v)):,}" if v else ""
    except Exception:
        return v or ""


def main():
    token = get_token()
    print("トークン取得OK")

    with open(r"C:\Users\Loser\Desktop\-\tamalabo\empty_rows.json", encoding="utf-8") as f:
        empty_rows = json.load(f)

    patient_ids = [r["patient_id"] for r in empty_rows]
    row_map = {r["patient_id"]: r["row"] for r in empty_rows}
    ids_str = ", ".join(patient_ids)

    # 1. クライアント情報取得
    print("クライアント情報取得中...")
    sql_clients = f"""
SELECT
  CAST(c.id AS STRING) AS patient_id,
  CONCAT(c.last_name, ' ', c.first_name) AS name,
  CONCAT(c.last_name_kana, ' ', c.first_name_kana) AS name_kana,
  c.tel AS tel
FROM `stream-443709.stream.clients` c
WHERE c.id IN ({ids_str})
"""
    clients = {r["patient_id"]: r for r in bq_query(sql_clients, token)}
    print(f"  取得: {len(clients)}件")

    # 2. 契約情報取得
    print("契約情報取得中...")
    sql_contracts = f"""
SELECT
  CAST(c.id AS STRING) AS patient_id,
  cpm.payment_method_slug,
  CAST(con.id AS STRING) AS contract_id,
  CAST(con.contract_amount AS STRING) AS contract_amount,
  CAST(cpm.initial_amount AS STRING) AS initial_amount,
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_date,
  FORMAT_TIMESTAMP('%Y/%m/%d', cpm.first_payment_at, 'Asia/Tokyo') AS first_pay_date,
  CAST(cpm.payday AS STRING) AS payday,
  CAST(cpm.installment_count AS STRING) AS installment_count
FROM `stream-443709.stream.clients` c
JOIN `stream-443709.stream.contracts` con ON con.client_id = c.id
LEFT JOIN `stream-443709.stream.contract_payment_method` cpm ON cpm.contract_id = con.id
WHERE c.id IN ({ids_str})
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY con.contracted_at DESC) = 1
"""
    contracts = {r["patient_id"]: r for r in bq_query(sql_contracts, token)}
    print(f"  取得: {len(contracts)}件")

    # 3. スプレッドシートを一旦クリア（B-M列を空白に）
    print("\nスプレッドシートの既存データをクリア中...")
    creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    # クリア対象行を収集
    clear_requests = []
    for entry in empty_rows:
        row_num = entry["row"]
        clear_requests.append({
            "range": f"B{row_num}:M{row_num}",
            "values": [[""] * 12]
        })
    for i in range(0, len(clear_requests), 200):
        ws.batch_update(clear_requests[i:i+200], value_input_option="USER_ENTERED")
    print(f"  {len(clear_requests)}行クリア完了")

    # 4. 新しいデータで書き込み
    print("\n新データ書き込み中...")
    batch_data = []
    filled_client = 0
    filled_contract = 0

    for entry in empty_rows:
        pid = entry["patient_id"]
        row_num = entry["row"]

        if pid not in clients:
            continue

        c = clients[pid]
        con = contracts.get(pid, {})

        slug = con.get("payment_method_slug") or ""
        payment = PAYMENT_MAP.get(slug, slug)
        first_pay = con.get("first_pay_date") or ""
        second_pay = add_one_month(first_pay)
        contract_amount = format_yen(con.get("contract_amount"))
        initial_amount = con.get("initial_amount") or ""

        values = [
            c.get("name") or "",
            c.get("name_kana") or "",
            c.get("tel") or "",
            payment,
            con.get("contract_id") or "",
            contract_amount,
            initial_amount,
            con.get("contracted_date") or "",
            first_pay,
            second_pay,
            con.get("payday") or "",
            con.get("installment_count") or "",
        ]

        batch_data.append({"range": f"B{row_num}:M{row_num}", "values": [values]})
        filled_client += 1
        if con:
            filled_contract += 1

    for i in range(0, len(batch_data), 100):
        ws.batch_update(batch_data[i:i+100], value_input_option="USER_ENTERED")
        print(f"  {min(i+100, len(batch_data))}/{len(batch_data)} 件書き込み完了")

    print(f"\n=== 完了 ===")
    print(f"  氏名・電話番号を埋めた行: {filled_client}")
    print(f"  契約情報まで埋めた行: {filled_contract}")
    print(f"  BigQueryで見つからなかった患者: {len(empty_rows) - filled_client}")


if __name__ == "__main__":
    main()
