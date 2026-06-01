"""
Google スプレッドシート「2026年5月16日時点未解約データ」シートのA列について、
重複するIDのセルを赤色で塗りつぶすスクリプト
"""
import gspread
from google.oauth2.service_account import Credentials
from collections import Counter

# --- 設定 ---
SERVICE_ACCOUNT_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME = "2026年5月16日時点未解約データ"

# 赤色 (RGB)
RED_RGB = {"red": 1.0, "green": 0.0, "blue": 0.0}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_gspread_client():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def main():
    print("=== 重複IDセル赤色塗りつぶし処理開始 ===")
    print(f"対象シート: {SHEET_NAME}")

    # 1. 認証
    print("\n[1/4] Google Sheets API 認証中...")
    gc = get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.worksheet(SHEET_NAME)
    print("  → 認証・シート取得完了")

    # 2. A列全件取得
    print("\n[2/4] A列データ取得中...")
    col_values = worksheet.col_values(1)  # A列全件
    total_rows = len(col_values)
    print(f"  → A列 {total_rows} 件取得（ヘッダー含む）")

    if total_rows <= 1:
        print("  → データ行がありません。処理終了。")
        return

    # 3. 重複IDの特定（1行目ヘッダーを除く）
    print("\n[3/4] 重複IDを特定中...")
    header = col_values[0]
    data_values = col_values[1:]  # ヘッダー除外
    print(f"  → ヘッダー: '{header}'")
    print(f"  → データ行数: {len(data_values)}")

    # 2つ目以降の出現のみを対象（初出はスキップ）
    seen = set()
    duplicate_rows = []
    for idx, val in enumerate(data_values):
        if val.strip() == "":
            continue
        if val in seen:
            duplicate_rows.append(idx + 2)  # +2: 0-indexed → 1-based、ヘッダー1行分
        else:
            seen.add(val)

    duplicate_values = set()  # 件数表示用

    if not duplicate_rows:
        print("  → 重複IDは見つかりませんでした。処理終了。")
        return

    print(f"  → 塗りつぶし対象セル数（2つ目以降）: {len(duplicate_rows)} セル")

    # 4. A列全体の背景色をリセットしてから、2つ目以降だけ赤く塗る
    print("\n[4/4] A列の背景色をリセット後、重複セルを赤色で塗りつぶし中...")

    # A列全体をリセット（白に戻す）
    reset_request = {
        "repeatCell": {
            "range": {
                "sheetId": worksheet.id,
                "startRowIndex": 1,  # ヘッダー除く
                "endRowIndex": total_rows,
                "startColumnIndex": 0,
                "endColumnIndex": 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
                }
            },
            "fields": "userEnteredFormat.backgroundColor",
        }
    }
    worksheet.spreadsheet.batch_update({"requests": [reset_request]})
    print("  → A列背景色リセット完了")

    # バッチ処理（API呼び出しを減らすため範囲をまとめる）
    # 個別セル指定で format を適用
    # gspread の batch_update を使って一括適用
    red_format = {
        "repeatCell": {
            "range": None,  # 各セルごとに設定
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": RED_RGB
                }
            },
            "fields": "userEnteredFormat.backgroundColor",
        }
    }

    # 100件ずつバッチでリクエストを送信
    batch_size = 100
    requests_list = []
    for row in duplicate_rows:
        requests_list.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": worksheet.id,
                        "startRowIndex": row - 1,  # 0-based
                        "endRowIndex": row,
                        "startColumnIndex": 0,  # A列
                        "endColumnIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": RED_RGB
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        )

    total_batches = (len(requests_list) + batch_size - 1) // batch_size
    for i in range(0, len(requests_list), batch_size):
        batch = requests_list[i : i + batch_size]
        batch_num = i // batch_size + 1
        worksheet.spreadsheet.batch_update({"requests": batch})
        print(f"  → バッチ {batch_num}/{total_batches} 完了 ({len(batch)} セル)")

    print(f"\n=== 処理完了 ===")
    print(f"  赤く塗ったセル数（2つ目以降の重複）: {len(duplicate_rows)} セル")
    print(f"  対象シート: {SHEET_NAME}")


if __name__ == "__main__":
    main()
