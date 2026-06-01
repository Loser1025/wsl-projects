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

# 既存行のpatient_idサンプル
sample_ids = "870516, 60076, 872449, 768988, 959600, 727153, 1037940"

# ① r_clinic.mp_clients でpatient_idとclient_idのブリッジを確認
print("=== r_clinic.mp_clients ===")
r1 = bq_query(f"""
SELECT CAST(patient_id AS STRING) as patient_id, CAST(client_id AS STRING) as client_id, name, phone_number
FROM `stream-443709.r_clinic.mp_clients`
WHERE patient_id IN ({sample_ids})
""", token)
for r in r1:
    print(f"  patient_id={r['patient_id']} → client_id={r['client_id']}, name={r['name']}, tel={r['phone_number']}")

# ② client_idを経由してstream.clientsで照合
if r1:
    client_ids = ", ".join(r["client_id"] for r in r1 if r["client_id"])
    print(f"\n=== stream.clients（client_id経由）===")
    r2 = bq_query(f"""
SELECT CAST(id AS STRING) as id, CONCAT(last_name,' ',first_name) as name, tel
FROM `stream-443709.stream.clients`
WHERE id IN ({client_ids})
""", token)
    for r in r2:
        print(f"  client_id={r['id']}: {r['name']}, tel={r['tel']}")

    # ③ さらにcontractsも確認
    print(f"\n=== stream.contracts（client_id経由）===")
    r3 = bq_query(f"""
SELECT CAST(con.client_id AS STRING) as client_id, con.id as contract_id,
    con.contract_amount, FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') as contracted_date,
    cpm.payment_method_slug, cpm.initial_amount, cpm.payday, cpm.installment_count
FROM `stream-443709.stream.contracts` con
LEFT JOIN `stream-443709.stream.contract_payment_method` cpm ON cpm.contract_id = con.id
WHERE con.client_id IN ({client_ids})
QUALIFY ROW_NUMBER() OVER (PARTITION BY con.client_id ORDER BY con.contracted_at DESC) = 1
""", token)
    for r in r3:
        print(f"  client_id={r['client_id']}: contract_id={r['contract_id']}, amount={r['contract_amount']}, method={r['payment_method_slug']}")
