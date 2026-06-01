"""
ローン会社ごとに「契約日→初回支払日」の傾向を分析する（シート変更なし）
"""
import sys, io, requests, subprocess
from collections import defaultdict
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import gspread
from google.oauth2.service_account import Credentials

SA_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME = "2026年5月16日時点未解約データ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
GCLOUD_PATH = r"C:\Users\Loser\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.ps1"
BQ_PROJECT = "stream-443709"

LOAN_NAMES = {
    "ml_pocketcard": "医療ローン(ポケットカード)",
    "ml_aplus":      "医療ローン(アプラス)",
    "ml_jplum":      "医療ローン(日本プラム)",
    "ml_ryfety":     "医療ローン(ライフティ)",
    "ml_cbsfs":      "医療ローン(CBS)",
    "ml_ideacard":   "医療ローン(アイディアカード)",
}

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

def diff_days(d1_str, d2_str):
    """2つのYYYY/MM/DD文字列の差分日数を返す（d2 - d1）"""
    try:
        fmt = "%Y/%m/%d"
        return (datetime.strptime(d2_str, fmt) - datetime.strptime(d1_str, fmt)).days
    except Exception:
        return None

# シートから全データ取得
creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)
all_rows = ws.get_all_values()

# contract_id → {contracted, first_pay} のマッピング（シート）
sheet_map = {}
for i, row in enumerate(all_rows[1:], start=2):
    cid        = row[5].strip() if len(row) > 5 else ""
    first_pay  = row[9].strip() if len(row) > 9 else ""
    contracted = row[8].strip() if len(row) > 8 else ""
    if cid:
        sheet_map[cid] = {"first_pay": first_pay, "contracted": contracted, "row": i}

all_contract_ids = ", ".join(sheet_map.keys())

# BQからローン系の支払情報を全件取得
token = get_token()
print("BigQueryからローン情報取得中...")
bq_rows = bq_query(f"""
SELECT
  CAST(cpm.contract_id AS STRING) AS contract_id,
  cpm.payment_method_slug,
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_at,
  FORMAT_TIMESTAMP('%Y/%m/%d', cpm.first_payment_at, 'Asia/Tokyo') AS first_payment_at,
  cpm.payday,
  cpm.medical_loan_apply_id
FROM `stream-443709.stream.contract_payment_method` cpm
JOIN `stream-443709.stream.contracts` con ON con.id = cpm.contract_id
WHERE cpm.contract_id IN ({all_contract_ids})
  AND cpm.payment_method_slug LIKE 'ml_%'
""", token)

print(f"ローン系レコード取得: {len(bq_rows)}件\n")

# ローン会社ごとに分類
# 「空欄あり」のローン会社を特定 → そのローン会社の「日付あり」分布を分析
loan_data = defaultdict(lambda: {"with_date": [], "without_date": []})

for r in bq_rows:
    slug = r["payment_method_slug"]
    cid  = r["contract_id"]
    s    = sheet_map.get(cid, {})
    contracted = r["contracted_at"] or s.get("contracted", "")
    first_pay_bq   = r["first_payment_at"]
    first_pay_sheet = s.get("first_pay", "")
    first_pay = first_pay_bq or first_pay_sheet

    entry = {
        "contract_id": cid,
        "contracted": contracted,
        "first_pay": first_pay,
        "payday": r["payday"],
        "loan_id": r["medical_loan_apply_id"],
    }
    if first_pay:
        loan_data[slug]["with_date"].append(entry)
    else:
        loan_data[slug]["without_date"].append(entry)

# 空欄ありのローン会社のみ分析
empty_slugs = [s for s, d in loan_data.items() if d["without_date"]]

print("=" * 65)
print(f"初回支払日が空欄のローン会社: {len(empty_slugs)}社")
print("=" * 65)

for slug in sorted(empty_slugs):
    name = LOAN_NAMES.get(slug, slug)
    with_d  = loan_data[slug]["with_date"]
    without = loan_data[slug]["without_date"]

    print(f"\n▼ {name}")
    print(f"  空欄: {len(without)}件 ／ 日付あり: {len(with_d)}件")

    if with_d:
        # 契約日→初回支払日 の差分日数を計算
        diffs = []
        paydays = []
        for e in with_d:
            d = diff_days(e["contracted"], e["first_pay"])
            if d is not None:
                diffs.append(d)
            if e["payday"]:
                paydays.append(int(e["payday"]))

        if diffs:
            diffs.sort()
            avg = sum(diffs) / len(diffs)
            print(f"  【契約日→初回支払日 差分】")
            print(f"    最小: {min(diffs)}日 / 最大: {max(diffs)}日 / 平均: {avg:.0f}日")
            # 分布（0〜30日、31〜60日、61〜90日、91〜）
            buckets = {"0〜30日": 0, "31〜60日": 0, "61〜90日": 0, "91日以上": 0}
            for d in diffs:
                if d <= 30:   buckets["0〜30日"] += 1
                elif d <= 60: buckets["31〜60日"] += 1
                elif d <= 90: buckets["61〜90日"] += 1
                else:         buckets["91日以上"] += 1
            for k, v in buckets.items():
                if v:
                    bar = "█" * v
                    print(f"    {k}: {v}件 {bar}")

        if paydays:
            from collections import Counter
            pd_cnt = Counter(paydays)
            top = pd_cnt.most_common(3)
            print(f"  【毎月支払日（payday）の分布】")
            for day, cnt in top:
                print(f"    {day}日: {cnt}件")

        # サンプル（日付ありの実例）
        print(f"  【日付ありのサンプル（最大5件）】")
        for e in with_d[:5]:
            gap = diff_days(e["contracted"], e["first_pay"])
            gap_str = f"+{gap}日" if gap is not None else ""
            print(f"    契約日={e['contracted']} → 初回={e['first_pay']} ({gap_str})  payday={e['payday']}")
    else:
        print(f"  ※このローン会社は日付ありのデータが0件のため傾向分析不可")

    # 空欄ケースのサンプル
    print(f"  【空欄のサンプル（最大5件）】")
    for e in without[:5]:
        print(f"    contract_id={e['contract_id']}, 契約日={e['contracted']}, loan_id={e['loan_id'] or 'なし'}")
