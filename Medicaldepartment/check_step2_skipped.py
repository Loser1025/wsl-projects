import sys, io, requests, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import gspread
from google.oauth2.service_account import Credentials
from collections import Counter

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
    resp = requests.post(url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql, "useLegacySql": False, "timeoutMs": 30000, "maxResults": 500})
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(data)
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]

creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)
all_rows = ws.get_all_values()

targets = []
for i, row in enumerate(all_rows[1:], start=2):
    cid       = row[5].strip() if len(row) > 5 else ""
    first_pay = row[9].strip() if len(row) > 9 else ""
    payment   = row[4].strip() if len(row) > 4 else ""
    contracted= row[8].strip() if len(row) > 8 else ""
    if cid and not first_pay:
        targets.append({"row": i, "contract_id": cid, "payment": payment, "contracted": contracted})

token = get_token()
cids = ", ".join(set(t["contract_id"] for t in targets))
bq_rows = bq_query(f"""
SELECT CAST(contract_id AS STRING) as cid, payment_method_slug
FROM `stream-443709.stream.contract_payment_method`
WHERE contract_id IN ({cids})
""", token)
found = {r["cid"]: r["payment_method_slug"] for r in bq_rows}

print(f"スキップ対象: {len(targets)}行")
print("\n支払方法の内訳（シート表記）:")
print(Counter(t["payment"] for t in targets).most_common())

in_bq = sum(1 for t in targets if t["contract_id"] in found)
print(f"\nBQにcontract_payment_method存在: {in_bq}件")
print(f"BQに存在しない（旧システム）    : {len(targets) - in_bq}件")
