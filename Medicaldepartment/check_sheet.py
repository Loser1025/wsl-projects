import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import gspread
from google.oauth2.service_account import Credentials

SA_FILE = r"C:\Users\Loser\Desktop\-\tamalabo\automation-visitor-shindan\ageless-impulse-488713-m6-03014b3cddad.json"
SHEET_ID = "1NQU2SGVykYL3n35NgzL78R0fszK0vt5yacNSV151wYI"
SHEET_NAME = "2026年5月16日時点未解約データ"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

creds = Credentials.from_service_account_file(SA_FILE, scopes=SCOPES)
gc = gspread.authorize(creds)
ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

rows = ws.get("A1960:M1980")
filled = 0
empty = 0
for i, row in enumerate(rows):
    rn = 1960 + i
    b = row[1] if len(row) > 1 else ""
    g = row[6] if len(row) > 6 else ""
    has_data = any(v.strip() for v in row[1:]) if len(row) > 1 else False
    if has_data:
        filled += 1
        print(f"行{rn} [埋] A={row[0]} B={b} G={g}")
    else:
        empty += 1
        print(f"行{rn} [空] A={row[0]}")

print(f"\n埋まっている: {filled}行 / 空: {empty}行")
