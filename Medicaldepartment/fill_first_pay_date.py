"""
初回支払日（J列）・2回目支払日（K列）が空の行を contract_id から補完する
- first_payment_at（ローン確定日）→ paid_at（現金・クレカ支払済日）の順で使用
- 2回目支払日は分割・ローン系のみ（現金・クレカ一括は空）
"""
import sys, io, requests, subprocess, calendar
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SA_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME = "2026年5月16日時点未解約データ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
GCLOUD_PATH = r"C:\Users\Loser\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.ps1"
BQ_PROJECT = "stream-443709"

ONE_TIME_METHODS = {"cash", "cc_square", "cc_stripe", "cc_gmo", "cc_stera", "cc_alpha_note", "wire_transfer", "spot"}

def get_token():
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"& '{GCLOUD_PATH}' auth print-access-token"],
        capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip()

def bq_query(sql, token):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{BQ_PROJECT}/queries"
    resp = requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql, "useLegacySql": False, "timeoutMs": 60000, "maxResults": 10000})
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(f"BQエラー: {data.get('error', {}).get('message', data)}")
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]

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

def main():
    print("=" * 50)
    print("初回支払日・2回目支払日 補完スクリプト")
    print("=" * 50)

    creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    print("\n[1/3] 対象行を検出中（J列が空・F列(contract_id)あり）...")
    all_rows = ws.get_all_values()
    targets = []
    for i, row in enumerate(all_rows[1:], start=2):
        contract_id = row[5].strip() if len(row) > 5 else ""
        first_pay   = row[9].strip() if len(row) > 9 else ""
        if contract_id and not first_pay:
            targets.append({"row": i, "contract_id": contract_id})

    print(f"  → {len(targets)}行が対象")
    if not targets:
        print("対象行なし。終了。")
        return

    print("\n[2/3] BigQueryから初回支払日を取得中...")
    token = get_token()
    contract_ids = ", ".join(set(t["contract_id"] for t in targets))

    rows = bq_query(f"""
SELECT
  CAST(cpm.contract_id AS STRING) AS contract_id,
  cpm.payment_method_slug,
  FORMAT_TIMESTAMP('%Y/%m/%d',
    COALESCE(cpm.first_payment_at, cpm.paid_at),
    'Asia/Tokyo') AS first_pay_date,
  cpm.payday
FROM `stream-443709.stream.contract_payment_method` cpm
WHERE cpm.contract_id IN ({contract_ids})
""", token)

    pay_map = {r["contract_id"]: r for r in rows}
    print(f"  → {len(pay_map)}件取得（うち日付あり: {sum(1 for r in rows if r['first_pay_date'])}件）")

    print("\n[3/3] スプレッドシートに書き込み中...")
    batch_data = []
    filled = 0
    skipped = 0

    for t in targets:
        cid = t["contract_id"]
        info = pay_map.get(cid, {})
        first_pay = info.get("first_pay_date") or ""
        slug = info.get("payment_method_slug") or ""
        second_pay = "" if slug in ONE_TIME_METHODS else add_one_month(first_pay)

        if not first_pay:
            skipped += 1
            continue

        batch_data.append({
            "range": f"J{t['row']}:K{t['row']}",
            "values": [[first_pay, second_pay]]
        })
        filled += 1

    for i in range(0, len(batch_data), 200):
        ws.batch_update(batch_data[i:i+200], value_input_option="USER_ENTERED")
        print(f"  {min(i+200, len(batch_data))}/{len(batch_data)}件 書き込み完了")

    print(f"\n=== 完了 ===")
    print(f"  初回支払日を補完: {filled}行")
    print(f"  日付データなし（スキップ）: {skipped}行")
    print(f"  ※スキップ分はBigQueryに日付データがありません（ローン未確定など）")

if __name__ == "__main__":
    main()
