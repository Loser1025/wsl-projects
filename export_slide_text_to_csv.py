#!/usr/bin/env python3
"""
スライド内の全テキストをCSVファイルにエクスポートするスクリプト
"""
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import csv

# サービスアカウントの認証情報
SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
SCOPES = ['https://www.googleapis.com/auth/presentations']

# スライドID
SLIDE_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'


def get_presentation(service, presentation_id):
    """プレゼンテーションを取得"""
    try:
        presentation = service.presentations().get(
            presentationId=presentation_id
        ).execute()
        return presentation
    except HttpError as error:
        print(f"Error: {error}")
        return None


def main():
    # 認証
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build('slides', 'v1', credentials=creds)

    # プレゼンテーションを取得
    presentation = get_presentation(service, SLIDE_ID)
    if not presentation:
        print("Failed to get presentation.")
        return

    # CSVファイルに書き込み
    with open('slide_text_export.csv', 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Slide ID', 'Shape ID', 'Text'])

        # スライド内の全テキストを取得
        slides = presentation.get('slides', [])
        for slide in slides:
            for element in slide.get('pageElements', []):
                if 'shape' in element:
                    shape = element['shape']
                    if 'text' in shape:
                        text_elements = shape['text'].get('textElements', [])
                        for text_element in text_elements:
                            if 'textRun' in text_element:
                                content = text_element['textRun']['content']
                                writer.writerow([slide['objectId'], element['objectId'], content])

    print("Successfully exported slide text to slide_text_export.csv")


if __name__ == '__main__':
    main()
