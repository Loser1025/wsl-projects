"""
BigQueryから患者情報を取得してスプレッドシートのB-M列を埋めるスクリプト
"""
import json
import subprocess
import csv
import io
import sys
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
import calendar

SA_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME = "2026年5月16日時点未解約データ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
BQ_PROJECT = "stream-443709"
BQ_CMD = r"C:\Users\Loser\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\bq.cmd"

PAYMENT_METHOD_MAP = {
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


def run_bq_query(sql):
    result = subprocess.run(
        [BQ_CMD, "query", "--use_legacy_sql=false", "--format=csv",
         f"--project_id={BQ_PROJECT}", sql],
        capture_output=True, text=True, encoding="utf-8", shell=True
    )
    if result.returncode != 0:
        print(f"BQ ERROR: {result.stderr}", file=sys.stderr)
        return []
    reader = csv.DictReader(io.StringIO(result.stdout))
    return list(reader)


def add_months(dt_str, months):
    """YYYY/MM/DD 形式の日付に月数を加算して返す"""
    if not dt_str or dt_str.strip() == "":
        return ""
    try:
        dt = datetime.strptime(dt_str.strip(), "%Y/%m/%d")
        month = dt.month + months
        year = dt.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return f"{year}/{month:02d}/{day:02d}"
    except Exception:
        return ""


def format_yen(amount_str):
    """数値を ¥N,NNN,NNN 形式にフォーマット"""
    try:
        n = int(float(amount_str))
        return f"¥{n:,}"
    except Exception:
        return amount_str


def main():
    # 埋め残し行を読み込む
    with open(r"C:\Users\Loser\Desktop\-\tamalabo\empty_rows.json", encoding="utf-8") as f:
        empty_rows = json.load(f)

    patient_ids = [r["patient_id"] for r in empty_rows]
    row_map = {r["patient_id"]: r["row"] for r in empty_rows}
    print(f"対象patient_id数: {len(patient_ids)}")

    # BigQueryクエリ（100件ずつ分割）
    all_results = {}
    chunk_size = 50
    for i in range(0, len(patient_ids), chunk_size):
        chunk = patient_ids[i:i + chunk_size]
        ids_str = ", ".join(chunk)
        sql = f"""
SELECT
  c.id AS patient_id,
  CONCAT(c.last_name, ' ', c.first_name) AS name,
  CONCAT(c.last_name_kana, ' ', c.first_name_kana) AS name_kana,
  c.tel AS tel,
  cpm.payment_method_slug,
  con.id AS contract_id,
  CAST(con.contract_amount AS STRING) AS contract_amount,
  CAST(cpm.initial_amount AS STRING) AS initial_amount,
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_date,
  FORMAT_TIMESTAMP('%Y/%m/%d', cpm.first_payment_at, 'Asia/Tokyo') AS first_pay_date,
  CAST(cpm.payday AS STRING) AS payday,
  CAST(cpm.installment_count AS STRING) AS installment_count
FROM `stream-443709.stream.clients` c
JOIN `stream-443709.stream.contracts` con ON con.client_id = c.id
LEFT JOIN `stream-443709.stream.contract_payment_method` cpm ON cpm.contract_id = con.id
WHERE CAST(c.id AS STRING) IN ({ids_str})
  AND con.canceled_at IS NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY con.contracted_at DESC) = 1
"""
        rows = run_bq_query(sql)
        for row in rows:
            pid = row["patient_id"]
            all_results[pid] = row
        print(f"  チャンク {i // chunk_size + 1}: {len(rows)}件取得")

    print(f"\nBigQueryで見つかった患者数: {len(all_results)} / {len(patient_ids)}")
    not_found = [pid for pid in patient_ids if pid not in all_results]
    if not_found:
        print(f"見つからなかったID({len(not_found)}件): {not_found[:10]}")

    # スプレッドシートに書き込む
    creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    batch_data = []
    filled = 0
    for pid, row_num in row_map.items():
        if pid not in all_results:
            continue
        d = all_results[pid]

        payment_slug = d.get("payment_method_slug", "")
        payment_name = PAYMENT_METHOD_MAP.get(payment_slug, payment_slug)

        first_pay = d.get("first_pay_date", "")
        second_pay = add_months(first_pay, 1)

        contract_amount = format_yen(d.get("contract_amount", "")) if d.get("contract_amount") else ""
        initial_amount = d.get("initial_amount", "")

        values = [
            d.get("name", ""),           # B: 氏名
            d.get("name_kana", ""),       # C: 氏名カナ
            d.get("tel", ""),             # D: 電話番号
            payment_name,                 # E: 支払方法
            d.get("contract_id", ""),     # F: contract_id
            contract_amount,              # G: 契約金額
            initial_amount,               # H: 初回金額
            d.get("contracted_date", ""), # I: 契約日
            first_pay,                    # J: 初回支払日
            second_pay,                   # K: 2回目支払日
            d.get("payday", ""),          # L: 毎月支払日
            d.get("installment_count", ""), # M: 分割回数
        ]

        batch_data.append({
            "range": f"B{row_num}:M{row_num}",
            "values": [values]
        })
        filled += 1

    print(f"\n書き込み対象: {filled}行")

    chunk_size = 100
    for i in range(0, len(batch_data), chunk_size):
        chunk = batch_data[i:i + chunk_size]
        ws.batch_update(chunk, value_input_option="USER_ENTERED")
        print(f"  {i + len(chunk)}/{len(batch_data)} 件書き込み完了")

    print(f"\n=== 完了 ===")
    print(f"  BigQueryから取得・書き込み: {filled}行")
    print(f"  取得できなかった: {len(not_found)}行")


if __name__ == "__main__":
    main()
