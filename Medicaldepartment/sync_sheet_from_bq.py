"""
スプレッドシートの空行をBigQueryから自動補完するスクリプト

使い方:
    python sync_sheet_from_bq.py

処理内容:
    1. スプレッドシートのA列IDを全件取得
    2. B-M列が空の行を検出
    3. BigQuery REST APIでクライアント情報・契約情報を取得
    4. スプレッドシートに書き込み
"""
import sys
import io
import json
import calendar
import subprocess
import requests
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ==================== 設定 ====================
SA_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME = "2026年5月16日時点未解約データ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
BQ_PROJECT = "stream-443709"
GCLOUD_PATH = r"C:\Users\Loser\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.ps1"
# ==============================================

PAYMENT_MAP = {
    "cash": "現金",
    "wire_transfer": "銀行振込",
    "spot": "スポット",
    "in_house_loan": "分割支払",
    "cc_stripe": "クレジットカード(Stripe)",
    "cc_square": "クレジットカード(Square)",
    "cc_gmo": "クレジットカード(GMO)",
    "cc_stera": "クレジットカード(Stera)",
    "cc_alpha_note": "クレジットカード(アルファノート)",
    "ml_pocketcard": "医療ローン(ポケットカード株式会社)",
    "ml_ryfety": "医療ローン(ライフティ株式会社)",
    "ml_aplus": "医療ローン(アプラス)",
    "ml_ideacard": "医療ローン(アイディアカード)",
    "ml_jplum": "医療ローン(ジェイプラム)",
    "ml_cbsfs": "医療ローン(CBSFS)",
}


def get_gcloud_token():
    """gcloud CLIからアクセストークンを取得"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"& '{GCLOUD_PATH}' auth print-access-token"],
        capture_output=True, text=True, encoding="utf-8"
    )
    token = result.stdout.strip()
    if not token:
        raise RuntimeError("gcloudトークン取得失敗。`gcloud auth login` を実行してください。")
    return token


def bq_query(sql, token):
    """BigQuery REST APIでクエリを実行してリストで返す"""
    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{BQ_PROJECT}/queries"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"query": sql, "useLegacySql": False, "timeoutMs": 60000, "maxResults": 10000}
    resp = requests.post(url, headers=headers, json=body)
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(f"BigQueryエラー: {data.get('error', {}).get('message', data)}")
    schema_fields = [f["name"] for f in data.get("schema", {}).get("fields", [])]
    results = []
    for row in data.get("rows", []):
        record = {schema_fields[i]: row["f"][i].get("v") for i in range(len(schema_fields))}
        results.append(record)
    return results


def add_one_month(dt_str):
    """YYYY/MM/DD に1か月加算"""
    if not dt_str:
        return ""
    try:
        dt = datetime.strptime(dt_str.strip(), "%Y/%m/%d")
        month = dt.month + 1
        year = dt.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return f"{year}/{month:02d}/{day:02d}"
    except Exception:
        return ""


def format_yen(v):
    """数値を ¥N,NNN,NNN 形式に変換"""
    try:
        return f"¥{int(float(v)):,}" if v else ""
    except Exception:
        return v or ""


def find_empty_rows(ws):
    """B-M列が空でA列にIDがある行を返す [{row: int, patient_id: str}]"""
    print("  スプレッドシートデータ取得中...")
    all_rows = ws.get_all_values()
    empty = []
    seen = set()
    for i, row in enumerate(all_rows[1:], start=2):  # 1行目ヘッダーをスキップ
        pid = row[0].strip() if row else ""
        if not pid:
            continue
        b_to_m = row[1:13] if len(row) >= 13 else row[1:] + [""] * (13 - len(row))
        if all(v.strip() == "" for v in b_to_m) and pid not in seen:
            empty.append({"row": i, "patient_id": pid})
            seen.add(pid)
    return empty


def fetch_bq_data(patient_ids, token):
    """BigQueryからクライアント情報と契約情報を取得

    シートの patient_id = stream.clients.source_id (source_code='RKR') でマッピング
    stream.clients.id (内部ID) を経由して contracts に結合する
    """
    ids_str = ", ".join(patient_ids)

    print("  BigQuery: クライアント情報取得中...")
    sql_clients = f"""
SELECT
  CAST(c.source_id AS STRING) AS patient_id,
  CAST(c.id AS STRING) AS client_id,
  CONCAT(c.last_name, ' ', c.first_name) AS name,
  CONCAT(c.last_name_kana, ' ', c.first_name_kana) AS name_kana,
  c.tel AS tel
FROM `stream-443709.stream.clients` c
WHERE c.source_id IN ({ids_str})
  AND c.source_code = 'RKR'
"""
    clients = {r["patient_id"]: r for r in bq_query(sql_clients, token)}
    print(f"    → {len(clients)}件取得")

    print("  BigQuery: 契約情報取得中...")
    # client_idリストを作成して contracts を検索
    client_ids = ", ".join(r["client_id"] for r in clients.values() if r.get("client_id"))
    if not client_ids:
        return clients, {}

    sql_contracts = f"""
SELECT
  CAST(c.source_id AS STRING) AS patient_id,
  cpm.payment_method_slug,
  CAST(con.id AS STRING) AS contract_id,
  CAST(con.contract_amount AS STRING) AS contract_amount,
  CAST(cpm.initial_amount AS STRING) AS initial_amount,
  FORMAT_TIMESTAMP('%Y/%m/%d', con.contracted_at, 'Asia/Tokyo') AS contracted_date,
  -- 初回支払日: first_payment_at（ローン確定日）→ paid_at（現金・クレカ支払済日）の順で使用
  FORMAT_TIMESTAMP('%Y/%m/%d',
    COALESCE(cpm.first_payment_at, cpm.paid_at),
    'Asia/Tokyo') AS first_pay_date,
  CAST(cpm.payday AS STRING) AS payday,
  CAST(cpm.installment_count AS STRING) AS installment_count,
  cpm.payment_method_slug AS method_for_second_pay
FROM `stream-443709.stream.clients` c
JOIN `stream-443709.stream.contracts` con ON con.client_id = c.id
LEFT JOIN `stream-443709.stream.contract_payment_method` cpm ON cpm.contract_id = con.id
WHERE c.id IN ({client_ids})
  AND c.source_code = 'RKR'
QUALIFY ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY con.contracted_at DESC) = 1
"""
    contracts = {r["patient_id"]: r for r in bq_query(sql_contracts, token)}
    print(f"    → {len(contracts)}件取得")

    return clients, contracts


def build_row_values(pid, clients, contracts):
    """1行分のB-M列データを組み立てる"""
    c = clients.get(pid, {})
    con = contracts.get(pid, {})

    slug = con.get("payment_method_slug") or ""
    payment = PAYMENT_MAP.get(slug, slug)
    first_pay = con.get("first_pay_date") or ""
    # 2回目支払日：分割・ローン系のみ計算（現金・クレジット一括は空）
    one_time_methods = {"cash", "cc_square", "cc_stripe", "cc_gmo", "cc_stera", "cc_alpha_note", "wire_transfer", "spot"}
    method_for_second = con.get("method_for_second_pay") or slug
    second_pay = "" if method_for_second in one_time_methods else add_one_month(first_pay)

    return [
        c.get("name") or "",                    # B: 氏名
        c.get("name_kana") or "",               # C: 氏名カナ
        c.get("tel") or "",                     # D: 電話番号
        payment,                                # E: 支払方法
        con.get("contract_id") or "",           # F: contract_id
        format_yen(con.get("contract_amount")), # G: 契約金額
        con.get("initial_amount") or "",        # H: 初回金額
        con.get("contracted_date") or "",       # I: 契約日
        first_pay,                              # J: 初回支払日
        second_pay,                             # K: 2回目支払日
        con.get("payday") or "",                # L: 毎月支払日
        con.get("installment_count") or "",     # M: 分割回数
    ]


def main():
    print("=" * 50)
    print("スプレッドシート自動補完スクリプト")
    print("=" * 50)

    # Step 1: スプレッドシート接続
    print("\n[1/4] スプレッドシート接続中...")
    creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    print(f"  → シート「{SHEET_NAME}」接続完了")

    # Step 2: 空行を検出
    print("\n[2/4] 補完対象行を検出中...")
    empty_rows = find_empty_rows(ws)
    if not empty_rows:
        print("  → 補完対象の行はありません。処理終了。")
        return
    print(f"  → {len(empty_rows)}行が補完対象")

    # Step 3: BigQueryからデータ取得
    print("\n[3/4] BigQueryからデータ取得中...")
    token = get_gcloud_token()
    patient_ids = [r["patient_id"] for r in empty_rows]

    # 500件ずつ分割してクエリ
    all_clients, all_contracts = {}, {}
    chunk_size = 500
    for i in range(0, len(patient_ids), chunk_size):
        chunk = patient_ids[i:i + chunk_size]
        print(f"  チャンク {i // chunk_size + 1}/{(len(patient_ids) + chunk_size - 1) // chunk_size}")
        c, con = fetch_bq_data(chunk, token)
        all_clients.update(c)
        all_contracts.update(con)

    # Step 4: スプレッドシートに書き込み
    print("\n[4/4] スプレッドシートに書き込み中...")
    batch_data = []
    filled_client = 0
    filled_contract = 0
    not_found = 0

    for entry in empty_rows:
        pid = entry["patient_id"]
        row_num = entry["row"]

        if pid not in all_clients:
            not_found += 1
            continue

        values = build_row_values(pid, all_clients, all_contracts)
        batch_data.append({"range": f"B{row_num}:M{row_num}", "values": [values]})
        filled_client += 1
        if pid in all_contracts:
            filled_contract += 1

    for i in range(0, len(batch_data), 100):
        ws.batch_update(batch_data[i:i + 100], value_input_option="USER_ENTERED")
        print(f"  {min(i + 100, len(batch_data))}/{len(batch_data)}行 書き込み完了")

    # 結果サマリー
    print("\n" + "=" * 50)
    print("完了サマリー")
    print("=" * 50)
    print(f"  補完対象行数          : {len(empty_rows)}行")
    print(f"  氏名・電話番号を補完  : {filled_client}行")
    print(f"  契約情報まで補完      : {filled_contract}行")
    print(f"  BigQueryに存在しない  : {not_found}行")
    print(f"  契約情報が見つからない: {filled_client - filled_contract}行（氏名のみ補完）")


if __name__ == "__main__":
    main()
