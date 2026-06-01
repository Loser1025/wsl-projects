"""
契約日の「日」と初回支払日の関係を詳細分析する
"""
import sys, io, requests, subprocess
from collections import defaultdict, Counter
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
    "ml_pocketcard": "ポケットカード",
    "ml_aplus":      "アプラス",
    "ml_jplum":      "日本プラム",
    "ml_ryfety":     "ライフティ",
    "ml_cbsfs":      "CBS",
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

def parse_date(s):
    if not s:
        return None
    for fmt in ["%Y/%m/%d", "%Y/%m/%d"]:
        try:
            return datetime.strptime(s.strip(), fmt)
        except:
            pass
    return None

def months_diff(d1, d2):
    """d2がd1の何ヶ月後か（翌月=1, 翌々月=2, ...）"""
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)

# シートから contract_id → contracted, first_pay マッピング取得
creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)
all_rows = ws.get_all_values()
sheet_map = {}
for row in all_rows[1:]:
    cid       = row[5].strip() if len(row) > 5 else ""
    first_pay = row[9].strip() if len(row) > 9 else ""
    contracted= row[8].strip() if len(row) > 8 else ""
    if cid:
        sheet_map[cid] = {"first_pay": first_pay, "contracted": contracted}

token = get_token()
all_cids = ", ".join(sheet_map.keys())

# BQからローン系（日付あり）を全件取得
bq_rows = bq_query(f"""
SELECT
  CAST(cpm.contract_id AS STRING) AS contract_id,
  cpm.payment_method_slug,
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_at,
  FORMAT_TIMESTAMP('%Y/%m/%d', cpm.first_payment_at, 'Asia/Tokyo') AS first_payment_at,
  cpm.payday
FROM `stream-443709.stream.contract_payment_method` cpm
JOIN `stream-443709.stream.contracts` con ON con.id = cpm.contract_id
WHERE cpm.contract_id IN ({all_cids})
  AND cpm.payment_method_slug IN ('ml_pocketcard','ml_aplus','ml_jplum','ml_ryfety','ml_cbsfs')
  AND cpm.first_payment_at IS NOT NULL
""", token)

print(f"日付ありローン取得: {len(bq_rows)}件\n")

# ローン会社ごとに「契約日の日(day)」と「何ヶ月後のpaydayか」を集計
for slug, name in LOAN_NAMES.items():
    rows = [r for r in bq_rows if r["payment_method_slug"] == slug]
    if not rows:
        continue

    print("=" * 65)
    print(f"▼ {name}（{len(rows)}件）")
    print("=" * 65)

    # paydayを確認
    paydays = Counter(r["payday"] for r in rows if r["payday"])
    main_payday = paydays.most_common(1)[0][0] if paydays else "不明"
    print(f"  メイン支払日: 毎月{main_payday}日\n")

    # 契約日の「日」ごとに何ヶ月後になるかを集計
    # 契約日を区間に分けて分析
    # 区間: 1〜5日, 6〜10日, 11〜15日, 16〜20日, 21〜25日, 26〜末日
    buckets = {
        "1〜5日":   [],
        "6〜10日":  [],
        "11〜15日": [],
        "16〜20日": [],
        "21〜25日": [],
        "26〜末日": [],
    }

    for r in rows:
        c_date = parse_date(r["contracted_at"])
        f_date = parse_date(r["first_payment_at"])
        if not c_date or not f_date:
            continue
        day = c_date.day
        m_diff = months_diff(c_date, f_date)

        if   day <= 5:  buckets["1〜5日"].append(m_diff)
        elif day <= 10: buckets["6〜10日"].append(m_diff)
        elif day <= 15: buckets["11〜15日"].append(m_diff)
        elif day <= 20: buckets["16〜20日"].append(m_diff)
        elif day <= 25: buckets["21〜25日"].append(m_diff)
        else:           buckets["26〜末日"].append(m_diff)

    print(f"  {'契約日':^10} {'件数':>5}  {'最多ヶ月後':>8}  {'分布（月後: 件数）'}")
    print(f"  {'-'*10} {'-'*5}  {'-'*8}  {'-'*30}")
    for label, diffs in buckets.items():
        if not diffs:
            print(f"  {label:^10}  {'0':>5}件  {'—':>8}")
            continue
        cnt = Counter(diffs)
        top = cnt.most_common(1)[0]
        dist = "  ".join(f"{m}ヶ月後:{c}件" for m, c in sorted(cnt.items()))
        print(f"  {label:^10}  {len(diffs):>4}件  {top[0]:>6}ヶ月後  {dist}")

    # 締め日ルールの仮説を提示
    print(f"\n  【推定ルール】")
    # 契約日ごとの最多パターンを見て締め日ルールを推定
    ranges_months = {}
    for label, diffs in buckets.items():
        if diffs:
            top = Counter(diffs).most_common(1)[0][0]
            ranges_months[label] = top

    # 同じ月数のグループをまとめる
    from itertools import groupby
    items = list(ranges_months.items())
    groups = defaultdict(list)
    for label, m in items:
        groups[m].append(label)
    for m, labels in sorted(groups.items()):
        range_str = "・".join(labels)
        payday_str = main_payday
        print(f"    契約日 {range_str} → {m}ヶ月後の{payday_str}日")
    print()
