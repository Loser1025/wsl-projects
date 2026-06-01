import sys, io, requests, subprocess
from collections import Counter, defaultdict
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
        json={"query": sql, "useLegacySql": False, "timeoutMs": 60000, "maxResults": 10000})
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(data)
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]

creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# J列（初回支払日）が空でF列（contract_id）がある行を収集
all_rows = ws.get_all_values()
targets = []
for i, row in enumerate(all_rows[1:], start=2):
    contract_id = row[5].strip() if len(row) > 5 else ""
    first_pay   = row[9].strip() if len(row) > 9 else ""
    payment     = row[4].strip() if len(row) > 4 else ""
    amount      = row[6].strip() if len(row) > 6 else ""
    contracted  = row[8].strip() if len(row) > 8 else ""
    name        = row[1].strip() if len(row) > 1 else ""
    if contract_id and not first_pay:
        targets.append({
            "row": i, "contract_id": contract_id,
            "payment": payment, "amount": amount,
            "contracted": contracted, "name": name
        })

print(f"初回支払日が空の件数: {len(targets)}行\n")

# BigQueryで詳細を取得
token = get_token()
contract_ids = ", ".join(set(t["contract_id"] for t in targets))

bq_rows = bq_query(f"""
SELECT
  CAST(cpm.contract_id AS STRING) AS contract_id,
  cpm.payment_method_slug,
  cpm.first_payment_at,
  cpm.paid_at,
  cpm.will_pay_at,
  cpm.payday,
  cpm.installment_count,
  cpm.initial_amount,
  cpm.amount,
  cpm.medical_loan_apply_id,
  cpm.is_verification_in_progress,
  con.status AS contract_status,
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_at
FROM `stream-443709.stream.contract_payment_method` cpm
JOIN `stream-443709.stream.contracts` con ON con.id = cpm.contract_id
WHERE cpm.contract_id IN ({contract_ids})
""", token)

bq_map = {r["contract_id"]: r for r in bq_rows}

# シートの支払方法とBQのslugを突合して分析
print("=" * 60)
print("【1】支払方法別の内訳")
print("=" * 60)
slug_counter = Counter()
no_bq_counter = Counter()
for t in targets:
    info = bq_map.get(t["contract_id"])
    if info:
        slug_counter[info["payment_method_slug"]] += 1
    else:
        no_bq_counter[t["payment"]] += 1

for slug, cnt in slug_counter.most_common():
    print(f"  {slug or '(null)'}: {cnt}件")
if no_bq_counter:
    print(f"\n  ※BQにcontract_payment_methodなし: {sum(no_bq_counter.values())}件")
    for p, c in no_bq_counter.most_common():
        print(f"    シート支払方法=「{p}」: {c}件")

print("\n" + "=" * 60)
print("【2】各フィールドのNULL状況（BQにあるもの）")
print("=" * 60)
total_bq = len([t for t in targets if t["contract_id"] in bq_map])
fields_null = defaultdict(int)
for t in targets:
    info = bq_map.get(t["contract_id"])
    if not info:
        continue
    for f in ["first_payment_at", "paid_at", "will_pay_at", "payday", "medical_loan_apply_id", "is_verification_in_progress"]:
        if not info.get(f):
            fields_null[f] += 1

for f, cnt in sorted(fields_null.items(), key=lambda x: -x[1]):
    print(f"  {f} がNULL: {cnt}/{total_bq}件 ({cnt*100//total_bq}%)")

print("\n" + "=" * 60)
print("【3】ローン系（ml_*）の詳細")
print("=" * 60)
loan_cases = [(t, bq_map[t["contract_id"]]) for t in targets
              if t["contract_id"] in bq_map and (bq_map[t["contract_id"]]["payment_method_slug"] or "").startswith("ml_")]
loan_slug_cnt = Counter(info["payment_method_slug"] for _, info in loan_cases)
for slug, cnt in loan_slug_cnt.most_common():
    has_loan_id = sum(1 for _, info in loan_cases if info["payment_method_slug"] == slug and info.get("medical_loan_apply_id"))
    has_payday  = sum(1 for _, info in loan_cases if info["payment_method_slug"] == slug and info.get("payday"))
    print(f"  {slug}: {cnt}件  (loan_id有={has_loan_id}件 / payday有={has_payday}件)")

print("\n" + "=" * 60)
print("【4】契約日の分布（契約年月）")
print("=" * 60)
month_cnt = Counter()
for t in targets:
    ym = t["contracted"][:7] if len(t["contracted"]) >= 7 else "(不明)"
    month_cnt[ym] += 1
for ym, cnt in sorted(month_cnt.items()):
    bar = "█" * (cnt // 3)
    print(f"  {ym}: {cnt:3d}件 {bar}")

print("\n" + "=" * 60)
print("【5】分割支払（in_house_loan）の状況")
print("=" * 60)
inhouse = [(t, bq_map[t["contract_id"]]) for t in targets
           if t["contract_id"] in bq_map and bq_map[t["contract_id"]]["payment_method_slug"] == "in_house_loan"]
print(f"  件数: {len(inhouse)}件")
if inhouse:
    has_payday = sum(1 for _, info in inhouse if info.get("payday"))
    has_installment = sum(1 for _, info in inhouse if info.get("installment_count"))
    print(f"  payday（毎月支払日）あり: {has_payday}件")
    print(f"  installment_count（分割回数）あり: {has_installment}件")
    print("  サンプル:")
    for t, info in inhouse[:5]:
        print(f"    row={t['row']}, contract_id={t['contract_id']}, payday={info['payday']}, "
              f"installment={info['installment_count']}, contracted={info['contracted_at']}")
