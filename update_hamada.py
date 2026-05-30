#!/usr/bin/env python3
"""
濱田 涼介のローマ字を手動で更新するスクリプト
"""
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 設定
SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
PRESENTATION_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'
SCOPES = ['https://www.googleapis.com/auth/presentations']

# Google Slides APIの認証
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('slides', 'v1', credentials=credentials)

# 更新リクエスト
requests = [{
    "updateText": {
        "objectId": "g3e59e49d1cd_2_99",  # 濱田 涼介のローマ字要素ID
        "text": "RYOSUKE HAMADA",
        "fields": "text"
    }
}]

# 更新を実行
response = service.presentations().batchUpdate(
    presentationId=PRESENTATION_ID, body={"requests": requests}
).execute()

print("濱田 涼介のローマ字を更新しました。")