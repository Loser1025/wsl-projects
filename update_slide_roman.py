#!/usr/bin/env python3
"""
Googleスライドのローマ字をメンリストのローマ字に訂正するスクリプト
"""
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# サービスアカウントの認証情報
SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
SCOPES = ['https://www.googleapis.com/auth/presentations']

# スライドID
SLIDE_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'

# メンリストのローマ字マッピング
ROMAN_MAPPING = {
    "廣田 珠輝": "TAMAKI HIROTA",
    "吉村 行雲": "KOUN YOSHIMURA",
    "塩見 慎太郎": "SHINTARO SHIOMI",
    "本田 顕士": "KENTO HONDA",
    "秋山 匠": "TAKUMI AKIYAMA",
    "藤村 俊枝": "TOSHIE FUJIMURA",
    "石井 晴": "HARUSHI ISHII",
    "稲垣 太一": "TAICHI INAGAKI",
    "池上 雄斗": "YUTO IKEGAMI",
    "熊谷 侑輝": "YUKI KUMAGAI",
    "加藤 亮平": "RYOHEI KATO",
    "安藤 優世": "YUSEI ANDO",
    "江波戸 健": "TAKERU EBATO",
    "田畑 陽菜": "HINA TAHATA",
    "中田 恵里": "ERI NAKADA",
    "星野 優輝": "YUKI HOSHINO",
    "栗原 堅太": "KENTA KURIHARA",
    "村中 媛香": "HIMEKA MURANAKA",
    "島田 優": "YU SHIMADA",
    "石橋 乙葉": "OTOHA ISHIBASHI",
    "並河 真一": "SHINICHI NAMIKAWA",
    "共田 悠馬": "YUMA TOMODA",
    "進藤 彪": "HYO SHINDO",
    "宮本 悠大": "YUDAI MIYAMOTO",
    "中川 翔太": "SHOTA NAKAGAWA",
    "山﨑 陽向": "HINATA YAMASAKI",
    "熊倉 空大": "KUTO KUMAKURA",
    "吉房 つばさ": "TSUBASA YOSHIFUSA",
    "大関 秀": "SHU OSEKI",
    "髙 未佳": "MIKA KO",
    "金 亜耶": "AYA KIN",
    "穂原 志織": "SHIORI HOBARA",
    "石田 悠真": "YUMA ISHIDA",
    "堀野 昌樹": "MASAKI HORINO",
    "森本 風子": "FUKO MORIMOTO",
    "髙橋 涼夏": "SUZUKA TAKAHASHI",
    "大村 愛咲": "AISA OMURA",
    "田本 翔真": "SHOMA TAMOTO",
    "宮良 高基": "TAKATO MIYARA",
    "吉川 秀斗": "SHUTO KIKKAWA",
    "長谷川 ひらり": "HIRARI HASEGAWA",
    "幡野 智也": "TOMOYA HATANO",
    "皆川 雅斗": "MASATO MINAGAWA",
    "濱田 涼介": "RYOSUKE HAMADA"
}


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
        for element in slide.get('pageElements', []):
            if 'shape' in element:
                shape = element['shape']
                if 'text' in shape:
                    text_elements = shape['text'].get('textElements', [])
                    for text_element in text_elements:
                        if 'textRun' in text_element:
                            content = text_element['textRun']['content']
                            # ローマ字を訂正
                            for name, roman in ROMAN_MAPPING.items():
                                if name in content:
                                    # 既存のローマ字を削除し、新しいローマ字を追加
                                    new_content = content.replace(content, f"{name} {roman}")
                                    requests.append({
                                        "replaceAllText": {
                                            "containsText": {
                                                "text": content,
                                                "matchCase": True
                                            },
                                            "replaceText": new_content,
                                            "pageObjectIds": [slide['objectId']]
                                        }
                                    })
                                    print(f"Updated: {content} -> {new_content}")

    # 一括更新
    if requests:
        update_slide_text(service, SLIDE_ID, requests)
        print("Successfully updated the slide.")
    else:
        print("No updates were made.")


if __name__ == '__main__':
    main()
