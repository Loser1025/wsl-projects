from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import csv

# サービスアカウントの認証情報
SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
SCOPES = ['https://www.googleapis.com/auth/presentations']
SLIDE_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'

# ローマ字マッピングを読み込む
def load_roman_mapping():
    roman_mapping = {}
    with open('/home/loser/wsl-projects/roman_correction_list.csv', mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            roman_mapping[row['名前']] = row['正しいローマ字']
    return roman_mapping

ROMAN_MAPPING = load_roman_mapping()

def main():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build('slides', 'v1', credentials=creds)

    # プレゼンテーションを取得
    presentation = service.presentations().get(
        presentationId=SLIDE_ID
    ).execute()

    slides = presentation.get('slides', [])
    requests = []

    for slide in slides:
        slide_id = slide['objectId']
        # 背景を白に変更
        requests.append({
            "updatePageProperties": {
                "objectId": slide_id,
                "pageProperties": {
                    "pageBackgroundFill": {
                        "solidFill": {
                            "color": {
                                "rgbColor": {
                                    "red": 1.0,
                                    "green": 1.0,
                                    "blue": 1.0
                                }
                            }
                        }
                    }
                },
                "fields": "pageBackgroundFill.solidFill.color"
            }
        })

        # スライド内のテキスト要素を処理
        for element in slide.get('pageElements', []):
            if 'shape' in element:
                shape = element['shape']
                if 'text' in shape:
                    text_elements = shape['text'].get('textElements', [])
                    for text_element in text_elements:
                        if 'textRun' in text_element:
                            content = text_element['textRun']['content'].strip()
                            # 不要なテキスト（CHALLENGERやSTAFFなど）を削除
                            if content in ["CHALLENGER", "STAFF", "ORERATION", "S 軍"]:
                                requests.append({
                                    "deleteText": {
                                        "objectId": element['objectId'],
                                        "textRange": {
                                            "type": "ALL"
                                        }
                                    }
                                })
                            # 名前とローマ字のみを残す
                            elif content in ROMAN_MAPPING or content in ROMAN_MAPPING.values():
                                continue
                            else:
                                # テキストが空でない場合のみ削除
                                if content.strip():
                                    requests.append({
                                        "deleteText": {
                                            "objectId": element['objectId'],
                                            "textRange": {
                                                "type": "ALL"
                                            }
                                        }
                                    })

    # 一括更新
    if requests:
        try:
            response = service.presentations().batchUpdate(
                presentationId=SLIDE_ID,
                body={"requests": requests}
            ).execute()
            print("Successfully updated the slide backgrounds and text.")
        except HttpError as error:
            print(f"An error occurred: {error}")
    else:
        print("No updates were made.")

if __name__ == '__main__':
    main()