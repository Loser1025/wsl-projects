"""
setup_bq_auth.py — BigQuery OAuth2 初回認証スクリプト
======================================================
MCPサーバーを使う前に1回だけ実行してください。
ブラウザが開いてGoogleアカウント認証が求められます。
認証後、token.json が保存されます。

実行方法:
  python setup_bq_auth.py
"""

from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/bigquery.readonly",
]

HERE = Path(__file__).parent
CLIENT_SECRET = HERE / "client_secret.json"
TOKEN_FILE = HERE / "token.json"

def main():
    if not CLIENT_SECRET.exists():
        print(f"ERROR: {CLIENT_SECRET} が見つかりません")
        return

    print("ブラウザでGoogleアカウントの認証を行ってください...")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    print(f"✓ 認証完了: {TOKEN_FILE}")
    print("これでMCPサーバーが使用できます。")

if __name__ == "__main__":
    main()
