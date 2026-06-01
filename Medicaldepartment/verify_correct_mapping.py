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
        json={"query": sql, "useLegacySql": False, "timeoutMs": 30000, "maxResults": 200})
    data = resp.json()
    if not resp.ok:
        raise Exception(data)
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]

token = get_token()
creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# シートの既存行（A=patient_id, B=氏名, F=contract_id, G=契約金額）を取得
print("=== シートの既存データ（行2〜8）===")
rows = ws.get("A2:G8")
sheet_data = []
for i, row in enumerate(rows, start=2):
    if not row:
        continue
    pid = row[0] if len(row) > 0 else ""
    name = row[1] if len(row) > 1 else ""
    cid = row[5] if len(row) > 5 else ""
    amount = row[6] if len(row) > 6 else ""
    print(f"  行{i}: patient_id={pid}, 氏名={name}, contract_id={cid}, 契約金額={amount}")
    sheet_data.append((pid, name, cid, amount))

# patient_id を stream.contracts.client_id として検索
print("\n=== stream.contracts.client_id = patient_id で照合 ===")
pids = ", ".join(d[0] for d in sheet_data if d[0])
r = bq_query(f"""
SELECT
  CAST(con.client_id AS STRING) as patient_id,
  CAST(con.id AS STRING) as contract_id,
  con.contract_amount,
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') as contracted_date,
  cpm.payment_method_slug,
  cpm.initial_amount,
  cpm.payday,
  cpm.installment_count,
  FORMAT_TIMESTAMP('%Y/%m/%d', cpm.first_payment_at, 'Asia/Tokyo') as first_pay_date
FROM `stream-443709.stream.contracts` con
LEFT JOIN `stream-443709.stream.contract_payment_method` cpm ON cpm.contract_id = con.id
WHERE con.client_id IN ({pids})
ORDER BY con.client_id, con.contracted_at DESC
LIMIT 20
""", token)
for row in r:
    print(f"  patient_id={row['patient_id']}: contract_id={row['contract_id']}, amount={row['contract_amount']}, date={row['contracted_date']}, method={row['payment_method_slug']}")

# シートのcontract_idと一致するか確認
print("\n=== シートのcontract_idと照合確認 ===")
sheet_cids = ", ".join(d[2] for d in sheet_data if d[2])
r2 = bq_query(f"""
SELECT CAST(id AS STRING) as contract_id, CAST(client_id AS STRING) as client_id, contract_amount
FROM `stream-443709.stream.contracts`
WHERE id IN ({sheet_cids})
""", token)
for row in r2:
    print(f"  contracts.id={row['contract_id']}, client_id={row['client_id']}, amount={row['contract_amount']}")
