#!/usr/bin/env python3
"""デバッグ用: スライドのテキスト要素の座標と構造を確認"""
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json

SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
PRESENTATION_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'
SCOPES = ['https://www.googleapis.com/auth/presentations.readonly']

credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('slides', 'v1', credentials=credentials)

presentation = service.presentations().get(presentationId=PRESENTATION_ID).execute()

print(f"Title: {presentation.get('title')}")
print(f"Slides count: {len(presentation.get('slides', []))}")
print("=" * 80)

for slide_idx, slide in enumerate(presentation.get('slides', [])):
    print(f"\n--- Slide {slide_idx + 1} (ID: {slide['objectId']}) ---")
    page_elements = slide.get('pageElements', [])
    # テキスト要素をY座標でグループ化して表示
    text_items = []
    for element in page_elements:
        if 'shape' in element:
            shape = element['shape']
            transform = shape.get('transform', {})
            tx = transform.get('translateX', 0)
            ty = transform.get('translateY', 0)
            if 'text' in shape:
                text_elements = shape['text'].get('textElements', [])
                parts = []
                for elem in text_elements:
                    if 'textRun' in elem:
                        content = elem['textRun'].get('content', '')
                        parts.append(content)
                full = ''.join(parts).strip()
                if full:
                    text_items.append((ty, tx, full, element['objectId']))

    # Y座標でソート、同じYならXでソート
    text_items.sort()
    for ty, tx, text, element_id in text_items:
        print(f"  Y={ty:8.1f} X={tx:8.1f} | {repr(text)} | Element ID: {element_id}")