"""
スプレッドシート自動補完スクリプト（統合版）

処理①：B-M列が空の行 → BigQueryから氏名・契約情報を補完
処理②：初回支払日(J列)が空の行 → 支払方法別ルールで補完

初回支払日のルール:
  現金(cash)          : 契約日を使用
  クレジット(cc_square): 契約日を使用
  医療ローン BQに日付あり: first_payment_at → paid_at の順
  ポケットカード(ml_pocketcard): 翌々月1日
  アプラス(ml_aplus)  : 契約1〜5日→翌月27日 / 6〜末日→翌々月27日
  日本プラム(ml_jplum): 契約1〜25日→翌々月5日 / 26〜末日→翌々々月5日
  ライフティ(ml_ryfety): 契約1〜20日→翌月27日 / 21〜末日→翌々月27日
  CBS(ml_cbsfs)       : 翌々月27日

使い方:
  python sync_all.py
"""
import sys, io, requests, subprocess, calendar
from datetime import datetime
from collections import defaultdict
import gspread
from google.oauth2.service_account import Credentials

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ==================== 設定 ====================
SA_FILE     = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID    = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME  = "2026年5月16日時点未解約データ"
SCOPES      = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
GCLOUD_PATH = r"C:\Users\Loser\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.ps1"
BQ_PROJECT  = "stream-443709"
# ==============================================

PAYMENT_MAP = {
    "cash":          "現金",
    "wire_transfer": "銀行振込",
    "spot":          "スポット",
    "in_house_loan": "分割支払",
    "cc_stripe":     "クレジットカード(Stripe)",
    "cc_square":     "クレジットカード(Square)",
    "cc_gmo":        "クレジットカード(GMO)",
    "cc_stera":      "クレジットカード(Stera)",
    "cc_alpha_note": "クレジットカード(アルファノート)",
    "ml_pocketcard": "医療ローン(ポケットカード株式会社)",
    "ml_ryfety":     "医療ローン(ライフティ株式会社)",
    "ml_aplus":      "医療ローン(アプラス)",
    "ml_ideacard":   "医療ローン(アイディアカード)",
    "ml_jplum":      "医療ローン(日本プラム)",
    "ml_cbsfs":      "医療ローン(CBSFS)",
}

# 一括払い系（2回目支払日なし）
ONE_TIME_SLUGS = {"cash", "cc_square", "cc_stripe", "cc_gmo", "cc_stera", "cc_alpha_note", "wire_transfer", "spot"}

# ローン推定ルール対象
LOAN_ESTIMATE_SLUGS = {"ml_pocketcard", "ml_aplus", "ml_jplum", "ml_ryfety", "ml_cbsfs"}


# ==================== ユーティリティ ====================

def get_token():
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"& '{GCLOUD_PATH}' auth print-access-token"],
        capture_output=True, text=True, encoding="utf-8"
    )
    token = r.stdout.strip()
    if not token:
        raise RuntimeError("gcloudトークン取得失敗。`gcloud auth login` を実行してください。")
    return token


def bq_query(sql, token, max_results=10000):
    url  = f"https://bigquery.googleapis.com/bigquery/v2/projects/{BQ_PROJECT}/queries"
    resp = requests.post(url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql, "useLegacySql": False, "timeoutMs": 60000, "maxResults": max_results})
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(f"BQエラー: {data.get('error', {}).get('message', data)}")
    fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    return [{fields[i]: r["f"][i].get("v") for i in range(len(fields))} for r in data.get("rows", [])]


def add_months(dt, n):
    month = dt.month + n
    year  = dt.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day   = min(dt.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day)


def add_one_month(dt_str):
    if not dt_str:
        return ""
    try:
        dt = datetime.strptime(dt_str.strip(), "%Y/%m/%d")
        nxt = add_months(dt, 1)
        return nxt.strftime("%Y/%m/%d")
    except Exception:
        return ""


def fmt(dt):
    return dt.strftime("%Y/%m/%d") if dt else ""


def format_yen(v):
    try:
        return f"¥{int(float(v)):,}" if v else ""
    except Exception:
        return v or ""


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y/%m/%d")
    except Exception:
        return None


def write_batches(ws, batch_data, chunk=200):
    for i in range(0, len(batch_data), chunk):
        ws.batch_update(batch_data[i:i+chunk], value_input_option="USER_ENTERED")


# ==================== ローン推定ルール ====================

def estimate_first_pay(contracted_str, slug):
    """ローン会社ルールで初回支払日を推定する"""
    d = parse_date(contracted_str)
    if not d:
        return None
    day = d.day

    if slug == "ml_pocketcard":
        base = add_months(d, 2)
        return datetime(base.year, base.month, 1)

    elif slug == "ml_aplus":
        months = 1 if day <= 5 else 2
        base   = add_months(d, months)
        pd     = min(27, calendar.monthrange(base.year, base.month)[1])
        return datetime(base.year, base.month, pd)

    elif slug == "ml_jplum":
        months = 2 if day <= 25 else 3
        base   = add_months(d, months)
        return datetime(base.year, base.month, 5)

    elif slug == "ml_ryfety":
        months = 1 if day <= 20 else 2
        base   = add_months(d, months)
        pd     = min(27, calendar.monthrange(base.year, base.month)[1])
        return datetime(base.year, base.month, pd)

    elif slug == "ml_cbsfs":
        base = add_months(d, 2)
        pd   = min(27, calendar.monthrange(base.year, base.month)[1])
        return datetime(base.year, base.month, pd)

    return None


# ==================== 処理① B-M列補完 ====================

def step1_fill_empty_rows(ws, token):
    print("\n" + "=" * 55)
    print("【処理①】B-M列が空の行を BigQuery から補完")
    print("=" * 55)

    all_rows = ws.get_all_values()
    targets  = []
    seen     = set()
    for i, row in enumerate(all_rows[1:], start=2):
        pid    = row[0].strip() if row else ""
        b_to_m = row[1:13] if len(row) >= 13 else row[1:] + [""] * (13 - len(row))
        if pid and all(v.strip() == "" for v in b_to_m) and pid not in seen:
            targets.append({"row": i, "patient_id": pid})
            seen.add(pid)

    if not targets:
        print("  → 補完対象なし")
        return 0, 0

    print(f"  補完対象: {len(targets)}行")
    patient_ids = [t["patient_id"] for t in targets]
    ids_str     = ", ".join(patient_ids)

    # クライアント情報（source_id=patient_id, source_code='RKR'）
    clients = {r["patient_id"]: r for r in bq_query(f"""
SELECT
  CAST(c.source_id AS STRING) AS patient_id,
  CAST(c.id AS STRING) AS client_id,
  CONCAT(c.last_name, ' ', c.first_name) AS name,
  CONCAT(c.last_name_kana, ' ', c.first_name_kana) AS name_kana,
  c.tel AS tel
FROM `stream-443709.stream.clients` c
WHERE c.source_id IN ({ids_str}) AND c.source_code = 'RKR'
""", token)}

    # 契約情報（client_id経由）
    client_ids = ", ".join(r["client_id"] for r in clients.values() if r.get("client_id"))
    contracts  = {}
    if client_ids:
        contracts = {r["patient_id"]: r for r in bq_query(f"""
SELECT
  CAST(c.source_id AS STRING) AS patient_id,
  cpm.payment_method_slug,
  CAST(con.id AS STRING) AS contract_id,
  CAST(con.contract_amount AS STRING) AS contract_amount,
  CAST(cpm.initial_amount AS STRING) AS initial_amount,
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_date,
  FORMAT_TIMESTAMP('%Y/%m/%d',
    COALESCE(cpm.first_payment_at, cpm.paid_at),
    'Asia/Tokyo') AS first_pay_date,
  CAST(cpm.payday AS STRING) AS payday,
  CAST(cpm.installment_count AS STRING) AS installment_count
FROM `stream-443709.stream.clients` c
JOIN `stream-443709.stream.contracts` con ON con.client_id = c.id
LEFT JOIN `stream-443709.stream.contract_payment_method` cpm ON cpm.contract_id = con.id
WHERE c.id IN ({client_ids}) AND c.source_code = 'RKR'
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY con.contracted_at DESC) = 1
""", token)}

    batch_data = []
    filled_client, filled_contract = 0, 0

    for t in targets:
        pid = t["patient_id"]
        if pid not in clients:
            continue
        c   = clients[pid]
        con = contracts.get(pid, {})
        slug        = con.get("payment_method_slug") or ""
        payment     = PAYMENT_MAP.get(slug, slug)
        first_pay   = con.get("first_pay_date") or ""
        second_pay  = "" if slug in ONE_TIME_SLUGS else add_one_month(first_pay)
        con_amount  = format_yen(con.get("contract_amount"))
        init_amount = con.get("initial_amount") or ""

        # ローン系で日付なし → 推定ルール
        if not first_pay and slug in LOAN_ESTIMATE_SLUGS:
            dt = estimate_first_pay(con.get("contracted_date", ""), slug)
            if dt:
                first_pay  = fmt(dt)
                second_pay = fmt(add_months(dt, 1))

        # 現金・Square で日付なし → 契約日
        if not first_pay and slug in ("cash", "cc_square"):
            first_pay = con.get("contracted_date") or ""

        batch_data.append({
            "range": f"B{t['row']}:M{t['row']}",
            "values": [[
                c.get("name") or "",
                c.get("name_kana") or "",
                c.get("tel") or "",
                payment,
                con.get("contract_id") or "",
                con_amount,
                init_amount,
                con.get("contracted_date") or "",
                first_pay,
                second_pay,
                con.get("payday") or "",
                con.get("installment_count") or "",
            ]]
        })
        filled_client += 1
        if con:
            filled_contract += 1

    write_batches(ws, batch_data)
    not_found = len(targets) - filled_client
    print(f"  氏名・電話番号を補完: {filled_client}行")
    print(f"  契約情報まで補完    : {filled_contract}行")
    print(f"  BQ未存在（スキップ）: {not_found}行")
    return filled_client, filled_contract


# ==================== 処理② 初回支払日補完 ====================

def step2_fill_first_pay(ws, token):
    print("\n" + "=" * 55)
    print("【処理②】初回支払日(J列)が空の行を補完")
    print("=" * 55)

    all_rows = ws.get_all_values()
    targets  = []
    for i, row in enumerate(all_rows[1:], start=2):
        cid        = row[5].strip() if len(row) > 5 else ""
        first_pay  = row[9].strip() if len(row) > 9 else ""
        contracted = row[8].strip() if len(row) > 8 else ""
        if cid and not first_pay:
            targets.append({"row": i, "contract_id": cid, "contracted": contracted})

    if not targets:
        print("  → 補完対象なし")
        return 0

    print(f"  補完対象: {len(targets)}行")
    contract_ids = ", ".join(set(t["contract_id"] for t in targets))

    # BQから支払情報を取得
    bq_rows = bq_query(f"""
SELECT
  CAST(cpm.contract_id AS STRING) AS contract_id,
  cpm.payment_method_slug,
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_at,
  FORMAT_TIMESTAMP('%Y/%m/%d',
    COALESCE(cpm.first_payment_at, cpm.paid_at),
    'Asia/Tokyo') AS first_pay_date
FROM `stream-443709.stream.contract_payment_method` cpm
JOIN `stream-443709.stream.contracts` con ON con.id = cpm.contract_id
WHERE cpm.contract_id IN ({contract_ids})
""", token)
    pay_map = {r["contract_id"]: r for r in bq_rows}

    batch_data = []
    result_cnt = defaultdict(int)

    for t in targets:
        cid        = t["contract_id"]
        contracted = t["contracted"]
        info       = pay_map.get(cid, {})
        slug       = info.get("payment_method_slug") or ""
        first_pay  = info.get("first_pay_date") or ""
        source     = ""

        # ① BQに日付あり
        if first_pay:
            source = "BQ(first/paid_at)"

        # ② 現金・Square → 契約日
        elif slug in ("cash", "cc_square") and contracted:
            first_pay = contracted
            source    = f"契約日({slug})"

        # ③ ローン推定ルール
        elif slug in LOAN_ESTIMATE_SLUGS and contracted:
            dt = estimate_first_pay(contracted, slug)
            if dt:
                first_pay = fmt(dt)
                source    = f"推定({slug})"

        if not first_pay:
            result_cnt["スキップ"] += 1
            continue

        second_pay = "" if slug in ONE_TIME_SLUGS else add_one_month(first_pay)
        batch_data.append({
            "range": f"J{t['row']}:K{t['row']}",
            "values": [[first_pay, second_pay]]
        })
        result_cnt[source] += 1

    write_batches(ws, batch_data)

    filled = sum(v for k, v in result_cnt.items() if k != "スキップ")
    print(f"  補完完了: {filled}行 / スキップ: {result_cnt['スキップ']}行")
    for src, cnt in sorted(result_cnt.items()):
        if cnt and src != "スキップ":
            print(f"    {src}: {cnt}件")
    return filled


# ==================== メイン ====================

def main():
    print("=" * 55)
    print("スプレッドシート自動補完（統合版）")
    print("=" * 55)

    creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    ws    = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    print(f"シート「{SHEET_NAME}」接続完了")

    token = get_token()
    print("gcloudトークン取得完了")

    # 処理①
    filled_client, filled_contract = step1_fill_empty_rows(ws, token)

    # 処理②（①で書き込んだ後に再取得して実行）
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    filled_pay = step2_fill_first_pay(ws, token)

    print("\n" + "=" * 55)
    print("完了サマリー")
    print("=" * 55)
    print(f"  ①新規行補完（氏名等）  : {filled_client}行")
    print(f"  ①新規行補完（契約情報）: {filled_contract}行")
    print(f"  ②初回支払日補完        : {filled_pay}行")


if __name__ == "__main__":
    main()
