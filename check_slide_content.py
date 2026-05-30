#!/usr/bin/env python3
"""
Googleスライドの内容を確認するスクリプト
"""
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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

    # スライド内の全テキストを表示
    slides = presentation.get('slides', [])
    for i, slide in enumerate(slides):
        print(f"\n--- Slide {i + 1} ---")
        for j, element in enumerate(slide.get('pageElements', [])):
            if 'shape' in element:
                shape = element['shape']
                if 'text' in shape:
                    text_elements = shape['text'].get('textElements', [])
                    for k, text_element in enumerate(text_elements):
                        if 'textRun' in text_element:
                            content = text_element['textRun']['content']
                            print(f"  Shape {j + 1}, TextElement {k + 1}: {content}")


if __name__ == '__main__':
    main()
