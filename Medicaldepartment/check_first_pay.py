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

# 初回支払日(J列)が空の行を確認（B列は埋まっているもの）
all_rows = ws.get_all_values()
empty_j = []
for i, row in enumerate(all_rows[1:], start=2):
    pid = row[0].strip() if row else ""
    b = row[1].strip() if len(row) > 1 else ""
    j = row[9].strip() if len(row) > 9 else ""
    e = row[4].strip() if len(row) > 4 else ""  # 支払方法
    f = row[5].strip() if len(row) > 5 else ""  # contract_id
    if b and not j and f:
        empty_j.append({"row": i, "patient_id": pid, "payment": e, "contract_id": f})

print(f"氏名あり・contract_idあり・初回支払日が空: {len(empty_j)}行")
print("\n支払方法別の内訳:")
from collections import Counter
c = Counter(r["payment"] for r in empty_j)
for method, cnt in c.most_common():
    print(f"  {method}: {cnt}件")

print("\n=== BigQueryでcontract_payment_methodの日付フィールドを確認 ===")
# サンプルのcontract_idで全日付フィールドを確認
sample_cids = ", ".join(r["contract_id"] for r in empty_j[:20] if r["contract_id"])
if sample_cids:
    r2 = bq_query(f"""
SELECT
  CAST(contract_id AS STRING) as contract_id,
  payment_method_slug,
  FORMAT_TIMESTAMP('%Y/%m/%d', first_payment_at, 'Asia/Tokyo') as first_payment_at,
  FORMAT_TIMESTAMP('%Y/%m/%d', will_pay_at, 'Asia/Tokyo') as will_pay_at,
  FORMAT_TIMESTAMP('%Y/%m/%d', paid_at, 'Asia/Tokyo') as paid_at,
  payday,
  installment_count,
  initial_amount,
  amount,
  medical_loan_apply_id
FROM `stream-443709.stream.contract_payment_method`
WHERE contract_id IN ({sample_cids})
LIMIT 20
""", token)
    for r in r2:
        print(f"  contract_id={r['contract_id']}: method={r['payment_method_slug']}, "
              f"first_pay={r['first_payment_at']}, will_pay={r['will_pay_at']}, "
              f"paid_at={r['paid_at']}, payday={r['payday']}, loan_id={r['medical_loan_apply_id']}")
