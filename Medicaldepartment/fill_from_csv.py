"""
BigQueryから取得したCSVを使ってスプレッドシートのB-M列を埋める
"""
import json
import csv
import sys
import io
import calendar
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SA_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME = "2026年5月16日時点未解約データ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

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


def add_one_month(dt_str):
    if not dt_str or dt_str.strip() == "":
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
    try:
        n = int(float(v))
        return f"¥{n:,}"
    except Exception:
        return v or ""


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    # CSVから読み込み
    clients = {r["patient_id"]: r for r in read_csv(r"C:\Users\Loser\Desktop\-\tamalabo\bq_clients.csv")}
    contracts = {r["patient_id"]: r for r in read_csv(r"C:\Users\Loser\Desktop\-\tamalabo\bq_contracts.csv")}

    print(f"clients: {len(clients)}件, contracts: {len(contracts)}件")

    with open(r"C:\Users\Loser\Desktop\-\tamalabo\empty_rows.json", encoding="utf-8") as f:
        empty_rows = json.load(f)

    creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    batch_data = []
    filled_client = 0
    filled_contract = 0
    not_found = 0

    for entry in empty_rows:
        pid = entry["patient_id"]
        row_num = entry["row"]

        if pid not in clients:
            not_found += 1
            continue

        c = clients[pid]
        con = contracts.get(pid, {})

        # 支払方法
        slug = con.get("payment_method_slug", "")
        payment = PAYMENT_MAP.get(slug, slug)

        # 2回目支払日を計算
        first_pay = con.get("first_pay_date", "")
        second_pay = add_one_month(first_pay)

        # 契約金額フォーマット
        contract_amount = format_yen(con.get("contract_amount", "")) if con.get("contract_amount") else ""
        initial_amount = con.get("initial_amount", "")

        values = [
            c.get("name", ""),                   # B: 氏名
            c.get("name_kana", ""),               # C: 氏名カナ
            c.get("tel", ""),                     # D: 電話番号
            payment,                              # E: 支払方法
            con.get("contract_id", ""),           # F: contract_id
            contract_amount,                      # G: 契約金額
            initial_amount,                       # H: 初回金額
            con.get("contracted_date", ""),       # I: 契約日
            first_pay,                            # J: 初回支払日
            second_pay,                           # K: 2回目支払日
            con.get("payday", ""),                # L: 毎月支払日
            con.get("installment_count", ""),     # M: 分割回数
        ]

        batch_data.append({"range": f"B{row_num}:M{row_num}", "values": [values]})
        filled_client += 1
        if con:
            filled_contract += 1

    print(f"書き込み対象: {filled_client}行（うち契約情報あり: {filled_contract}行）")
    print(f"BigQueryに存在しない患者: {not_found}件")

    chunk = 100
    for i in range(0, len(batch_data), chunk):
        ws.batch_update(batch_data[i:i+chunk], value_input_option="USER_ENTERED")
        print(f"  {min(i+chunk, len(batch_data))}/{len(batch_data)} 件書き込み完了")

    print("=== 完了 ===")
    print(f"  氏名・電話番号を埋めた行: {filled_client}")
    print(f"  契約情報まで埋めた行: {filled_contract}")
    print(f"  BigQueryで見つからなかった患者: {not_found}")


if __name__ == "__main__":
    main()
