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
        json={"query": sql, "useLegacySql": False, "timeoutMs": 30000, "maxResults": 500})
    data = resp.json()
    if not resp.ok:
        raise Exception(data)
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]

token = get_token()
creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# 現在の空行のpatient_idを取得
all_rows = ws.get_all_values()
empty_ids = []
for i, row in enumerate(all_rows[1:], start=2):
    pid = row[0].strip() if row else ""
    if not pid:
        continue
    b_to_m = row[1:13] if len(row) >= 13 else row[1:] + [""] * (13 - len(row))
    if all(v.strip() == "" for v in b_to_m):
        empty_ids.append(pid)

print(f"空行ID数: {len(empty_ids)}")
ids_str = ", ".join(empty_ids)

# source_id経由でstream.clientsにヒットする件数
r = bq_query(f"""
SELECT COUNT(*) as cnt
FROM `stream-443709.stream.clients`
WHERE source_id IN ({ids_str}) AND source_code = 'RKR'
""", token)
print(f"source_id(RKR)でhit: {r[0]['cnt']} 件 / {len(empty_ids)} 件")

# サンプル確認
r2 = bq_query(f"""
SELECT CAST(source_id AS STRING) as patient_id, CAST(id AS STRING) as client_id,
       CONCAT(last_name,' ',first_name) as name,
       CONCAT(last_name_kana,' ',first_name_kana) as name_kana,
       tel
FROM `stream-443709.stream.clients`
WHERE source_id IN ({ids_str}) AND source_code = 'RKR'
LIMIT 10
""", token)
print("\n=== サンプル（空行のpatient_id → 氏名）===")
for r in r2:
    print(f"  patient_id={r['patient_id']} → client_id={r['client_id']}, 氏名={r['name']}, tel={r['tel']}")
