import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import gspread
from google.oauth2.service_account import Credentials

SA_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1Ca6pUgCyA_DVcwHWt3JC_wuwYKFkQKd2x30X8DzKMPw"
SHEET_NAME = "Stream貼付"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# ヘッダー行と先頭10行を確認
rows = ws.get("A1:J15")
print(f"=== シート「{SHEET_NAME}」の内容 ===")
for i, row in enumerate(rows):
    print(f"行{i+1}: {row}")

print(f"\n全シート一覧:")
sh = gspread.authorize(creds).open_by_key(SHEET_ID)
for s in sh.worksheets():
    print(f"  - {s.title}")
