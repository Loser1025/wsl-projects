"""
スプレッドシート自動補完スクリプト（Google Colab 用）

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

使い方（Google Colab）:
  1. 以下のセルを順番に実行
  2. 認証ダイアログが表示されたら Google アカウントでログイン
"""
import io, sys, calendar
from datetime import datetime
from collections import defaultdict

import gspread
try:
    from google.colab import auth
except ImportError:
    auth = None
from google.auth import default
from google.oauth2 import service_account
from google.cloud import bigquery

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/bigquery",
        "https://www.googleapis.com/auth/cloud-platform"
]

# sys.stdout のエンコーディング設定（Colab では不要、ローカル用）
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except AttributeError:
    pass  # Colab の OutStream には buffer 属性がないのでスキップ

# ==================== 設定 ====================
SHEET_ID    = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME  = "未解約データ"
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

def bq_query(sql, bq_client, max_results=10000):
    """google.cloud.bigquery クライアントでクエリを実行し、辞書リストを返す"""
    try:
        job_config = bigquery.QueryJobConfig(
            use_legacy_sql=False,
            priority=bigquery.QueryPriority.INTERACTIVE,
        )
        query_job = bq_client.query(sql, job_config=job_config, project=BQ_PROJECT)
        results = query_job.result(max_results=max_results)
        columns = [field.name for field in results.schema]
        return [{col: row[col] for col in columns} for row in results]
    except Exception as e:
        print(f"  [警告] BQクエリ実行エラー (ローカルテスト環境制限等のため): {e}")
        return []


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


# ==================== 新規処理：阻止＆処理リストからの取り込み ====================

def step0_import_from_block_list(gc, ws_target):
    print("\n" + "=" * 55)
    print("【処理⓪】「2026.03 阻止＆処理リスト」から未登録IDを抽出して「未解約データ」に追加")
    print("=" * 55)

    try:
        sh = gc.open_by_key(SHEET_ID)
        ws_block = sh.worksheet("2026.03 阻止＆処理リスト")
    except Exception as e:
        print(f"  → 「2026.03 阻止＆処理リスト」シートの取得に失敗しました: {e}")
        return 0

    block_rows = ws_block.get_all_values()
    if not block_rows or len(block_rows) < 2:
        print("  → 阻止＆処理リストにデータがありません")
        ヘッダー = block_rows[0] if block_rows else []
        return 0

    header = block_rows[0]
    # 列のインデックスを特定（T列 = 20番目 (index 19), AE列 = 31番目 (index 30)）
    # ※ヘッダー長やA列が患者IDであることを考慮
    # A列: 患者ID (index 0)
    # T列: index 19 (1文字目から数えて20番目、または列名確認)
    # AE列: index 31 (32番目)
    # 安全のため列名や位置を確認しつつ判定する
    print(f"  阻止＆処理リスト総行数: {len(block_rows) - 1}行")

    # 既存の「未解約データ」の患者IDセットを取得
    target_rows = ws_target.get_all_values()
    existing_pids = set()
    for row in target_rows[1:]:
        if row and row[0].strip():
            existing_pids.add(row[0].strip())

    new_ids_to_add = []
    seen_in_block = set()

    for idx, row in enumerate(block_rows[1:], start=2):
        if not row or len(row) <= 3 or not row[3].strip():
            continue
        pid = row[3].strip()
        
        # 列データの取得（インデックス範囲チェック付き）
        # T列 (20番目 -> index 19)
        t_val = row[19].strip() if len(row) > 19 else ""
        # AE列 (31番目 -> index 30)
        ae_val = row[30].strip() if len(row) > 30 else ""

        # 条件: T列 = TRUE (大文字小文字問わず "TRUE" or "True")
        #       AE列 = FALSE または 空欄 ( "" または "FALSE" / "False" )
        #       「未解約データ」に存在しない
        t_is_true = t_val.upper() == "TRUE"
        ae_is_false_or_empty = ae_val == "" or ae_val.upper() == "FALSE"

        if t_is_true and ae_is_false_or_empty:
            if pid not in existing_pids and pid not in seen_in_block:
                new_ids_to_add.append([pid])
                seen_in_block.add(pid)

    if not new_ids_to_add:
        print("  → 追加対象の新規IDはありません")
        return 0

    print(f"  追加対象の新規ID数: {len(new_ids_to_add)}件")
    
    # 未解約データの末尾に新規行（A列に患者ID、B〜M列は空）として追加
    ws_target.append_rows(new_ids_to_add, value_input_option="USER_ENTERED")
    print(f"  → 「未解約データ」シートの末尾に {len(new_ids_to_add)} 件の新規行を追加しました。")
    return len(new_ids_to_add)

def step1_fill_empty_rows(ws, bq_client):
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
""", bq_client)}

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
""", bq_client)}

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

def step2_fill_first_pay(ws, bq_client):
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
""", bq_client)
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
    print("スプレッドシート自動補完（Google Colab 用）")
    print("=" * 55)

    # --- Google 認証 ---
    if auth:
        try:
            auth.authenticate_user()
        except Exception:
            pass
    
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/bigquery",
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/cloud-platform"
    ]

    import os
    sa_paths = [
        "/home/loser/wsl-projects/wuhu-generals-ranking/service-account.json",
        "service-account.json",
        "Medicaldepartment/service-account.json"
    ]
    
    creds = None
    for p in sa_paths:
        if os.path.exists(p):
            try:
                creds = service_account.Credentials.from_service_account_file(p, scopes=SCOPES)
                print(f"  → サービスアカウント認証ファイルを使用します: {p}")
                break
            except Exception as e:
                print(f"  → {p} の読み込みに失敗しました: {e}")

    if not creds:
        try:
            creds, _ = default(scopes=SCOPES)
        except Exception:
            creds, _ = default()

    print("✅ 認証完了")

    # --- スプレッドシート接続 ---
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    print(f"シート「{SHEET_NAME}」接続完了")

    # --- BigQuery クライアント ---
    bq_client = bigquery.Client(project=BQ_PROJECT, credentials=creds)
    print("BigQuery クライアント初期化完了")

    # 処理⓪：阻止＆処理リストから未登録IDを抽出して「未解約データ」に追加
    step0_import_from_block_list(gc, ws)

    # wsの再取得（新規行追加により行が変わっている可能性があるため）
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    # 処理①
    filled_client, filled_contract = step1_fill_empty_rows(ws, bq_client)

    # 処理②（①で書き込んだ後に再取得して実行）
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    filled_pay = step2_fill_first_pay(ws, bq_client)

    print("\n" + "=" * 55)
    print("完了サマリー")
    print("=" * 55)
    print(f"  ①新規行補完（氏名等）  : {filled_client}行")
    print(f"  ①新規行補完（契約情報）: {filled_contract}行")
    print(f"  ②初回支払日補完        : {filled_pay}行")


if __name__ == "__main__":
    main()
