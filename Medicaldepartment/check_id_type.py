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

creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
gc = gspread.authorize(creds)
ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# ヘッダーと既存データ行（上部）
print("=== ヘッダー ===")
header = ws.row_values(1)
print(header)

print("\n=== 既存データ行（2〜6行）===")
for i in [2, 3, 4, 5, 6]:
    row = ws.row_values(i)
    a = row[0] if row else ""
    b = row[1] if len(row) > 1 else ""
    f = row[5] if len(row) > 5 else ""
    print(f"行{i}: A(patient_id)={a}, B(氏名)={b}, F(contract_id)={f}")

print("\n=== 新規追加行（1964〜1968）===")
for i in [1964, 1965, 1966, 1967, 1968]:
    row = ws.row_values(i)
    a = row[0] if row else ""
    b = row[1] if len(row) > 1 else ""
    f = row[5] if len(row) > 5 else ""
    print(f"行{i}: A={a}, B={b}, F(contract_id)={f}")

# BigQueryでA列のIDが clients か contracts どちらにあるか確認
result = subprocess.run(
    ["powershell", "-NoProfile", "-Command", f"& '{GCLOUD_PATH}' auth print-access-token"],
    capture_output=True, text=True, encoding="utf-8"
)
token = result.stdout.strip()

# 既存行のA列ID（505588）とF列ID（53033）をBigQueryで確認
def bq_query(sql, token):
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{BQ_PROJECT}/queries"
    resp = requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql, "useLegacySql": False, "timeoutMs": 30000, "maxResults": 10})
    data = resp.json()
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]

print("\n=== BigQuery確認 ===")
# A列のID 505588 → stream.clients に存在するか
r = bq_query("SELECT id, CONCAT(last_name,' ',first_name) as name FROM `stream-443709.stream.clients` WHERE id = 505588", token)
print(f"clients.id=505588: {r}")

# F列のID 53033 → stream.contracts に存在するか
r2 = bq_query("SELECT id, client_id, contract_amount FROM `stream-443709.stream.contracts` WHERE id = 53033", token)
print(f"contracts.id=53033: {r2}")

# 新規行の1048214 → clientsに存在するか
r3 = bq_query("SELECT id, CONCAT(last_name,' ',first_name) as name FROM `stream-443709.stream.clients` WHERE id = 1048214", token)
print(f"clients.id=1048214: {r3}")

# 1048214がcontract_idとして存在するか
r4 = bq_query("SELECT id, client_id, contract_amount FROM `stream-443709.stream.contracts` WHERE id = 1048214", token)
print(f"contracts.id=1048214: {r4}")
