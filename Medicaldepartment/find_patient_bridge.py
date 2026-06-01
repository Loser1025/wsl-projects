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

# シートのpatient_id（870516）がstream内のどこかに紐付いているか探す
# stream.clients.source_id に元のpatient_idが入っているかも
print("=== stream.clients.source_id で patient_id=870516 を検索 ===")
r1 = bq_query("""
SELECT CAST(id AS STRING) as id, source_id, source_code,
       CONCAT(last_name,' ',first_name) as name
FROM `stream-443709.stream.clients`
WHERE source_id = 870516
""", token)
print(f"  結果: {r1 if r1 else 'なし'}")

# stream.inquiries.migration_id にpatient_idが入っているかも
print("\n=== stream.inquiries.migration_id で 870516 を検索 ===")
r2 = bq_query("""
SELECT CAST(id AS STRING) as inq_id, CAST(client_id AS STRING) as client_id,
       migration_id, last_name, first_name
FROM `stream-443709.stream.inquiries`
WHERE migration_id = '870516'
LIMIT 5
""", token)
print(f"  結果: {r2 if r2 else 'なし'}")

# stream-443709の全テーブルでpatient_idカラムがあるものを探す
print("\n=== stream-443709.stream の全テーブルで patient_id カラムを持つものを探す ===")
r3 = bq_query("""
SELECT table_name, column_name
FROM `stream-443709`.stream.INFORMATION_SCHEMA.COLUMNS
WHERE column_name LIKE '%patient%'
ORDER BY table_name
""", token)
for r in r3:
    print(f"  {r['table_name']}.{r['column_name']}")

# rakkar_productionでも確認
print("\n=== rakkar-report.rakkar_production の全テーブルで patient_id + name 系カラムを持つものを探す ===")
r4 = bq_query("""
SELECT table_name, column_name
FROM `rakkar-report`.rakkar_production.INFORMATION_SCHEMA.COLUMNS
WHERE column_name LIKE '%patient%' OR column_name IN ('name','last_name','first_name','full_name')
ORDER BY table_name, column_name
""", token)
for r in r4:
    print(f"  {r['table_name']}.{r['column_name']}")
