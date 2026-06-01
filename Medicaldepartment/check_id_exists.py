import sys, io, requests, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import gspread
from google.oauth2.service_account import Credentials
import json

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
        json={"query": sql, "useLegacySql": False, "timeoutMs": 30000, "maxResults": 100})
    data = resp.json()
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]

# スプレッドシートから空行のIDを取得
creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)
all_rows = ws.get_all_values()

empty_ids = []
for i, row in enumerate(all_rows[1:], start=2):
    pid = row[0].strip() if row else ""
    if not pid:
        continue
    b_to_m = row[1:13] if len(row) >= 13 else row[1:] + [""] * (13 - len(row))
    if all(v.strip() == "" for v in b_to_m):
        empty_ids.append(pid)

print(f"現在の空行ID数: {len(empty_ids)}")
print(f"IDサンプル: {empty_ids[:10]}")

token = get_token()

# stream.clients で存在確認
ids_str = ", ".join(empty_ids[:50])
r_clients = bq_query(f"SELECT CAST(id AS STRING) as id FROM `stream-443709.stream.clients` WHERE id IN ({ids_str})", token)
found_in_clients = {r["id"] for r in r_clients}

# stream.contracts でcontract_idとして存在確認
r_contracts = bq_query(f"SELECT CAST(id AS STRING) as id, CAST(client_id AS STRING) as client_id FROM `stream-443709.stream.contracts` WHERE id IN ({ids_str})", token)
found_in_contracts = {r["id"]: r["client_id"] for r in r_contracts}

print("\n=== ID種別判定（空行のID 先頭20件）===")
for pid in empty_ids[:20]:
    if pid in found_in_clients:
        status = "✓ clients.id（患者ID）"
    elif pid in found_in_contracts:
        status = f"✓ contracts.id（契約ID）→ client_id={found_in_contracts[pid]}"
    else:
        status = "✗ どちらにも存在しない"
    print(f"  {pid}: {status}")
