#!/usr/bin/env python3
"""
Googleスライドのローマ字をroman_correction_list.csvの内容に基づいて訂正するスクリプト（最終版・v5）
"""
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import re
import csv

# サービスアカウントの認証情報
SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
SCOPES = ['https://www.googleapis.com/auth/presentations']

# スライドID
SLIDE_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'

# roman_correction_list.csvを読み込んでROMAN_MAPPINGを生成
def load_roman_mapping():
    roman_mapping = {}
    with open('/home/loser/wsl-projects/roman_correction_list.csv', mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            roman_mapping[row['名前']] = row['正しいローマ字']
    return roman_mapping

# メンリストのローマ字マッピング
ROMAN_MAPPING = load_roman_mapping()


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


def update_slide_text(service, presentation_id, requests):
    """スライドのテキストを一括更新"""
    try:
        response = service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests}
        ).execute()
        return response
    except HttpError as error:
        print(f"Error: {error}")
        return None


def normalize_roman(text):
    """テキストからスペース付きのローマ字を正規化（例：T A K A H A S H I -> TAKAHASHI）"""
    # スペースを削除し、大文字を維持
    normalized = re.sub(r'\s+', '', text)
    return normalized


def extract_roman_from_content(content):
    """コンテンツからローマ字部分を抽出（名前の後のローマ字）"""
    # 名前（漢字やひらがな）の後に続くローマ字を抽出
    # 例："濱田 涼介 RYOSUKE HAMADA" → "RYOSUKE HAMADA"
    # 例："T A K A H A S H I　S U Z U K A" → "T A K A H A S H I　S U Z U K A"
    
    # 1. 名前（漢字やひらがな）の後に続くローマ字を抽出
    roman_matches = re.findall(r'[A-Z][\sA-Z]*$', content.strip())
    if roman_matches:
        return roman_matches[0].strip()
    
    # 2. スペース付きの大文字列を抽出（全体がローマ字の場合）
    roman_matches = re.findall(r'[A-Z][\sA-Z]*', content)
    if roman_matches:
        return roman_matches[0].strip()
    
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

    # スライド内の全テキストを取得
    slides = presentation.get('slides', [])
    requests = []

    for slide in slides:
        # スライド内の全テキストを結合
        full_text = ""
        for element in slide.get('pageElements', []):
            if 'shape' in element:
                shape = element['shape']
                if 'text' in shape:
                    text_elements = shape['text'].get('textElements', [])
                    for text_element in text_elements:
                        if 'textRun' in text_element:
                            content = text_element['textRun']['content']
                            full_text += content + " "
        
        # 名前を検索
        for name, correct_roman in ROMAN_MAPPING.items():
            if name in full_text:
                # ローマ字部分を抽出
                current_roman = extract_roman_from_content_v2(full_text)
                if not current_roman:
                    continue  # ローマ字が見つからない場合はスキップ
                
                normalized_roman = normalize_roman(current_roman)
                normalized_correct_roman = normalize_roman(correct_roman)
                
                if normalized_roman != normalized_correct_roman:
                    # ローマ字部分のみを置換
                    # 重複を防ぐため、全てのテキスト要素をループ
                    for element in slide.get('pageElements', []):
                        if 'shape' in element:
                            shape = element['shape']
                            if 'text' in shape:
                                text_elements = shape['text'].get('textElements', [])
                                for text_element in text_elements:
                                    if 'textRun' in text_element:
                                        content = text_element['textRun']['content']
                                        # ローマ字部分を抽出
                                        roman_in_element = extract_roman_from_content_v2(content)
                                        if roman_in_element and normalize_roman(roman_in_element) == normalized_roman:
                                            requests.append({
                                                "replaceAllText": {
                                                    "containsText": {
                                                        "text": roman_in_element,
                                                        "matchCase": True
                                                    },
                                                    "replaceText": correct_roman,
                                                    "pageObjectIds": [slide['objectId']]
                                                }
                                            })
                                            print(f"Updated: {roman_in_element} -> {correct_roman}")

    # 一括更新
    if requests:
        update_slide_text(service, SLIDE_ID, requests)
        print("Successfully updated the slide.")
    else:
        print("No updates were made.")


def extract_roman_from_content_v2(content):
    """コンテンツからローマ字部分を抽出（名前の後のローマ字）"""
    # 名前（漢字やひらがな）の後に続くローマ字を抽出
    # 例：「濱田 涼介 RYOSUKE HAMADA」 → "RYOSUKE HAMADA"
    # 例：「RYOSUKE HAMADA」 → "RYOSUKE HAMADA"
    # 例：「T A K A H A S H I　S U Z U K A」 → "T A K A H A S H I　S U Z U K A"

    # 1. 全体がローマ字の場合
    if re.fullmatch(r'^[A-Z][A-Z\s]+$', content.strip()):
        return content.strip()

    # 2. 名前（漢字やひらがな）の後に続くローマ字を抽出
    roman_matches = re.findall(r'([A-Z][A-Z\s]+)$', content.strip())
    if roman_matches:
        return roman_matches[0].strip()

    # 3. スペース付きの大文字列を抽出（全体がローマ字の場合）
    roman_matches = re.findall(r'([A-Z][A-Z\s]+)', content)
    if roman_matches:
        return roman_matches[-1].strip()

    return None


if __name__ == '__main__':
    main()
