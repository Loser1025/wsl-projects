"""
現金（cash）の初回支払日が空の行を契約日で補完する
"""
import sys, io, requests, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import gspread
from google.oauth2.service_account import Credentials

SA_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME = "2026年5月16日時点未解約データ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
GCLOUD_PATH = r"C:\Users\Loser\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.ps1"
BQ_PROJECT = "stream-443709"

def get_token():
    r = subprocess.run(["powershell", "-NoProfile", "-Command", f"& '{GCLOUD_PATH}' auth print-access-token"],
        capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip()

def bq_query(sql, token):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{BQ_PROJECT}/queries"
    resp = requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql, "useLegacySql": False, "timeoutMs": 30000, "maxResults": 5000})
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(data)
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]

creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# 初回支払日空・契約日ありの行を抽出
all_rows = ws.get_all_values()
targets = []
for i, row in enumerate(all_rows[1:], start=2):
    contract_id = row[5].strip() if len(row) > 5 else ""
    first_pay   = row[9].strip() if len(row) > 9 else ""
    contracted  = row[8].strip() if len(row) > 8 else ""
    if contract_id and not first_pay and contracted:
        targets.append({"row": i, "contract_id": contract_id, "contracted": contracted})

print(f"契約日あり・初回支払日空の行: {len(targets)}件")

# BQでcashのものを絞り込む
token = get_token()
contract_ids = ", ".join(set(t["contract_id"] for t in targets))
bq_rows = bq_query(f"""
SELECT CAST(contract_id AS STRING) AS contract_id, payment_method_slug
FROM `stream-443709.stream.contract_payment_method`
WHERE contract_id IN ({contract_ids})
  AND payment_method_slug = 'cash'
""", token)
cash_ids = {r["contract_id"] for r in bq_rows}
print(f"うち cash: {len(cash_ids)}件")

batch_data = []
for t in targets:
    if t["contract_id"] in cash_ids:
        batch_data.append({
            "range": f"J{t['row']}",
            "values": [[t["contracted"]]]
        })

print(f"書き込み対象: {len(batch_data)}行")

for i in range(0, len(batch_data), 200):
    ws.batch_update(batch_data[i:i+200], value_input_option="USER_ENTERED")
    print(f"  {min(i+200, len(batch_data))}/{len(batch_data)}件 完了")

print(f"\n完了：cash {len(batch_data)}行の初回支払日に契約日を設定しました")
