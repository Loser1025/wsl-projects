#!/usr/bin/env python3
"""
ローマ字更新スクリプトのデバッグ用（スペース考慮版）
"""
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build

# 設定
SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
PRESENTATION_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'
SCOPES = ['https://www.googleapis.com/auth/presentations.readonly']
MEMBER_LIST_FILE = '/home/loser/wsl-projects/メンリスト'

# メンバーリストから名前とローマ字の辞書を作成
name_to_roman = {}
with open(MEMBER_LIST_FILE, 'r', encoding='utf-8') as f:
    next(f)  # ヘッダー行をスキップ
    for line in f:
        parts = line.strip().split(',')
        if len(parts) >= 3:
            name = parts[0].strip()  # スペースを保持
            roman = parts[2].strip()
            name_to_roman[name] = roman

# Google Slides APIの認証
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('slides', 'v1', credentials=credentials)

# スライドの取得
presentation = service.presentations().get(presentationId=PRESENTATION_ID).execute()
slides = presentation.get('slides', [])

for slide in slides:
    slide_id = slide['objectId']
    page_elements = slide.get('pageElements', [])
    
    # 名前とローマ字の要素を特定
    name_element = None
    roman_element = None
    name_text = ""
    roman_text = ""
    
    for element in page_elements:
        if 'shape' not in element or 'text' not in element['shape']:
            continue
        
        text_elements = element['shape']['text'].get('textElements', [])
        parts = []
        for te in text_elements:
            if 'textRun' in te:
                parts.append(te['textRun'].get('content', ''))
        full_text = ''.join(parts).strip()
        
        # 名前の要素を特定（日本語の名前）
        if re.search(r'[\u3040-\u30ff\u4e00-\u9fff]', full_text):
            name_element = element
            name_text = full_text  # スペースを保持
        # ローマ字の要素を特定（大文字のアルファベットとスペースのみ、かつ CHALLENGER/STAFF 以外）
        elif re.fullmatch(r'^[A-Z\s]+$', full_text) and full_text not in ['CHALLENGER', 'STAFF']:
            roman_element = element
            roman_text = full_text
    
    # 名前とローマ字の要素が両方見つかった場合
    if name_element and roman_element:
        correct_roman = name_to_roman.get(name_text, '')
        
        # ローマ字が一致しない場合はデバッグ出力
        if correct_roman and correct_roman != roman_text:
            print(f"[更新候補] Slide {slide_id}: {name_text} -> {correct_roman} (現在: {roman_text})")
        elif correct_roman == roman_text:
            print(f"[一致] Slide {slide_id}: {name_text} -> {correct_roman}")
    else:
        if name_element:
            print(f"[ローマ字なし] Slide {slide_id}: {name_text}")
        elif roman_element:
            print(f"[名前なし] Slide {slide_id}: {roman_text}")

print("\n--- メンバーリストの名前一覧 ---")
for name in name_to_roman:
    print(f"{name}")