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

# シートの既存行（名前がわかっている）のpatient_id
# 870516=神林 圭, 60076=木村 友哉, 872449=甲地 功徳, 768988=山下 紘司, 959600=四元 秀幸
sample_ids = "870516, 60076, 872449, 768988, 959600, 727153"

print("=== r_clinic.clients で patient_id → client_id → 氏名 確認 ===")
r1 = bq_query(f"""
SELECT CAST(patient_id AS STRING) as patient_id, CAST(client_id AS STRING) as client_id,
       name, name_kana, phone_number
FROM `stream-443709.r_clinic.clients`
WHERE patient_id IN ({sample_ids})
""", token)
for r in r1:
    print(f"  patient_id={r['patient_id']} → client_id={r['client_id']}, name={r['name']}, tel={r['phone_number']}")

# r_clinic.mp_clients でも試す
print("\n=== r_clinic.mp_clients で patient_id 確認 ===")
r2 = bq_query(f"""
SELECT CAST(patient_id AS STRING) as patient_id, CAST(client_id AS STRING) as client_id,
       name, phone_number
FROM `stream-443709.r_clinic.mp_clients`
WHERE patient_id IN ({sample_ids})
""", token)
if r2:
    for r in r2:
        print(f"  patient_id={r['patient_id']} → client_id={r['client_id']}, name={r['name']}")
else:
    print("  ヒットなし")

# stream.contracts から直接 patient_id で取れるか（counselingのclient_idとして？）
print("\n=== stream.contracts.client_id = rakkar patient_id として直接検索 ===")
r3 = bq_query(f"""
SELECT CAST(client_id AS STRING) as client_id, id as contract_id,
       contract_amount, FORMAT_TIMESTAMP('%Y/%m/%d', contracted_at, 'Asia/Tokyo') as contracted_date,
       status
FROM `stream-443709.stream.contracts`
WHERE client_id IN ({sample_ids})
ORDER BY contracted_at DESC
LIMIT 10
""", token)
if r3:
    for r in r3:
        print(f"  client_id(=patient_id?)={r['client_id']}: contract_id={r['contract_id']}, amount={r['contract_amount']}, date={r['contracted_date']}, status={r['status']}")
else:
    print("  ヒットなし")
