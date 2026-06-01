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

# シートの既存データ行（上部）からpatient_idを取得
creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)
rows = ws.get("A2:B10")
existing_ids = [(row[0], row[1] if len(row) > 1 else "") for row in rows if row and row[0]]
print("=== 既存行のpatient_id（シート）===")
for pid, name in existing_ids:
    print(f"  patient_id={pid}, 氏名={name}")

token = get_token()
sample_ids = ", ".join(pid for pid, _ in existing_ids)

# ① stream.clients.id で照合
print("\n=== ① stream.clients.id で照合 ===")
r1 = bq_query(f"SELECT CAST(id AS STRING) as id, CONCAT(last_name,' ',first_name) as name FROM `stream-443709.stream.clients` WHERE id IN ({sample_ids})", token)
for r in r1:
    print(f"  clients.id={r['id']}: {r['name']}")

# ② rakkar_production.clinics_patients.patient_id で照合
print("\n=== ② rakkar_production.clinics_patients.patient_id で照合 ===")
r2 = bq_query(f"SELECT CAST(patient_id AS STRING) as patient_id, CAST(mst_clinic_id AS STRING) as clinic_id FROM `rakkar-report.rakkar_production.clinics_patients` WHERE patient_id IN ({sample_ids}) LIMIT 20", token)
for r in r2:
    print(f"  patient_id={r['patient_id']}, clinic_id={r['clinic_id']}")

# ③ 空行のIDも同様に確認
print("\n=== ③ 空行のID（未補完）→ rakkar_production での存在確認 ===")
all_rows = ws.get_all_values()
empty_ids = []
for i, row in enumerate(all_rows[1:], start=2):
    pid = row[0].strip() if row else ""
    if not pid:
        continue
    b_to_m = row[1:13] if len(row) >= 13 else row[1:] + [""] * (13 - len(row))
    if all(v.strip() == "" for v in b_to_m):
        empty_ids.append(pid)

if empty_ids:
    ids_str = ", ".join(empty_ids[:30])
    r3 = bq_query(f"SELECT CAST(patient_id AS STRING) as patient_id, COUNT(*) as cnt FROM `rakkar-report.rakkar_production.clinics_patients` WHERE patient_id IN ({ids_str}) GROUP BY patient_id", token)
    found = {r["patient_id"] for r in r3}
    print(f"  空行ID数: {len(empty_ids)}")
    print(f"  rakkar clinics_patientsにヒット: {len(found)}件")
    for pid in empty_ids[:10]:
        status = "✓ rakkar_production に存在" if pid in found else "✗ 存在しない"
        print(f"  {pid}: {status}")
