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

# 既存シート行の contract_id → client_id を取得して、client_id → 氏名 を確認
# シート: patient_id=870516, contract_id=317054 → BQ: contracts.client_id=845685
print("=== contracts.client_id → stream.clients 氏名確認 ===")
r1 = bq_query("""
SELECT c.id as stream_client_id,
       CONCAT(c.last_name,' ',c.first_name) as name,
       CONCAT(c.last_name_kana,' ',c.first_name_kana) as name_kana,
       c.tel
FROM `stream-443709.stream.clients` c
WHERE c.id IN (845685, 816754, 848169, 733399, 941731)
""", token)
for r in r1:
    print(f"  stream_client_id={r['stream_client_id']}: {r['name']} ({r['name_kana']}) tel={r['tel']}")

# stream.clientsにpatient_idのような外部IDフィールドがないか全フィールド確認
print("\n=== stream.clientsの全フィールド名（patient関連を探す）===")
r2 = bq_query("""
SELECT column_name
FROM `stream-443709`.stream.INFORMATION_SCHEMA.COLUMNS
WHERE table_name = 'clients'
ORDER BY ordinal_position
""", token)
for r in r2:
    print(f"  {r['column_name']}")

# stream.inquiriesにpatient_id/external_idがあるか確認
print("\n=== stream.inquiries スキーマ（外部IDフィールド）===")
r3 = bq_query("""
SELECT column_name
FROM `stream-443709`.stream.INFORMATION_SCHEMA.COLUMNS
WHERE table_name = 'inquiries'
ORDER BY ordinal_position
""", token)
for r in r3:
    print(f"  {r['column_name']}")
