#!/usr/bin/env python3
"""
メンリストにいるがスライドに名前のない24名分のスライドを作成する
既存のSTAFFテンプレートスライド（秋山 匠 / g3e59e49d1cd_2_700）を複製し、
名前とローマ字を差し替えて追加する。

英名変換は 姓 SPACE 名 の大文字ローマ字（例: TAKUMI AKIYAMA）で自動生成。
"""

import re
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
PRESENTATION_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'
SCOPES = ['https://www.googleapis.com/auth/presentations']

# テンプレートスライドのobjectId（秋山 匠 / STAFF）
TEMPLATE_SLIDE_ID = 'g3e59e49d1cd_2_700'

# スライドに載っていない24名
MISSING_MEMBERS = [
    "廣田珠輝",
    "吉村行雲",
    "塩見慎太郎",
    "本田顕士",
    "藤村俊枝",
    "石井晴",
    "熊谷侑輝",
    "安藤優世",
    "星野優輝",
    "栗原堅太",
    "村中媛香",
    "島田優",
    "並河真一",
    "進藤彪",
    "熊倉空大",
    "吉房つばさ",
    "大関秀",
    "髙未佳",
    "堀野昌樹",
    "森本風子",
    "大村愛咲",
    "宮良高基",
    "吉川秀斗",
    "幡野智也",
]


def kanji_to_romaji(name: str) -> str:
    """
    姓・名をスペースで区切り、それぞれを大文字アルファベットに変換する
    （漢字→ローマ字 の簡易マッピング）。既存スライドとの整合性を取る。
    """
    # 姓と名の分割（1文字目=姓、残り=名 で単純分割は危険なので
    # よくある姓の文字数で判断。большинの場合: 1文字姓 or 2文字姓）
    # → 既存スライドの確認:
    #   秋山匠 → TAKUMI AKIYAMA (名 first, then 姓) これを採用
    #   田本翔真 → SYOMA TAMOTO → これも 名→順? いや SYOMA=翔真(名), TAMOTO=田本(姓)
    #   つまり "名 姓" の順で大文字ローマ字

    # 漢字→ローマ字 マッピング（既存スライドから収集 + メンリスト用に拡張）
    kanji_map = {}
    # 姓
    kanji_map.update({
        "廣田": "HIROTA", "吉村": "YOSHIMURA", "塩見": "SHIOMI",
        "本田": "HONDA", "藤村": "FUJIMURA", "石井": "ISHII",
        "熊谷": "KUMAGAI", "安藤": "ANDO", "星野": "HOSHINO",
        "栗原": "KURIHARA", "村中": "MURANAKA", "島田": "SHIMADA",
        "並河": "NAMIKAWA", "進藤": "SHINDO", "熊倉": "KURAKURA",
        "吉房": "YOSHIBUSA", "大関": "OSEKI", "髙未": "TAKAMI",
        "堀野": "HORINO", "森本": "MORIMOTO", "大村": "OMURA",
        "宮良": "MIYARA", "吉川": "YOSHIKAWA", "幡野": "HATANO",
        # 名前用（名の部分）
        "珠輝": "SHUKI", "行雲": "YUKUMO", "慎太郎": "SHENTARO",
        "顕士": "AKASHI", "俊枝": "TOSHIE", "晴": "HARU",
        "侑輝": "YUKI", "優世": "YUSEI", "優輝": "YUKI",
        "堅太": "KENTA", "媛香": "ERIKA", "優": "YU/MASSA",
        "真一": "SHINICHI", "彪": "HYO/TAKESHI", "空大": "KODAI/SORA",
        "つばさ": "TSUBASA", "秀": "SHU/HIDEKI", "未佳": "MIKA",
        "昌樹": "MASAKI", "風子": "FUJIKO/FUKOKO", "愛咲": "ASAKI/ASARI",
        "高基": "TAKAKI", "秀斗": "SHUTO/HIDETO", "智也": "TOMOYA",
    })

    # 2文字姓优先匹配
    surname_2 = name[:2]
    surname_1 = name[:1]
    if surname_2 in kanji_map:
        family = kanji_map[surname_2]
        given = name[2:]
    elif surname_1 in kanji_map:
        family = kanji_map[surname_1]
        given = name[1:]
    else:
        family = surname_2
        given = name[2:]

    # 名の部分
    if given in kanji_map:
        given_romaji = kanji_map[given]
    else:
        given_romaji = given

    return f"{given_romaji} {family}"


def make_batch_update_requests(members: list, template_slide_id: str) -> list:
    """
    テンプレートスライドを複製し、テキスト（名前・ローマ字）を差し替える
    batchUpdateリクエストのリストを生成。
    """
    requests = []
    for i, name in enumerate(members):
        new_slide_id = f"gNEWMEMBER_{i}_{name}"

        # 1) スライドを複製
        requests.append({
            "duplicateObject": {
                "objectId": template_slide_id,
                "objectIds": {
                    template_slide_id: new_slide_id
                }
            }
        })

        # テンプレート上のテキストボックスのobjectIdを取得し
        # 新しいスライドのテキストを更新する。
        # APIレスポンス待ちで新しいslideとその要素IDを取得するため、
        # ここでは「新規プレースホルダ→応答で取得」ではなく、
        # 「replaceAllText」で一括置換を使う。
        # duplicationで生成された名前をPLACEHOLDERとして使い、後でdelete→insertで書き換える。

        # replaceAllText を使う：プレースホルダー文字列を探して置換
        # テンプレートのテキスト:
        #   - "秋山　匠" → name
        #   - "TAKUMI AKIYAMA" → romaji
        #   - "STAFF" → "STAFF" (そのまま)

        romaji = kanji_to_romaji(name)

        # テキスト置換リクエスト（新規スライド内のみ）
        requests.append({
            "replaceAllText": {
                "containsText": {
                    "text": "秋山　匠",   # テンプレート内の旧名前
                    "matchCase": True
                },
                "replaceText": name,
                "pageObjectIds": [new_slide_id]
            }
        })
        requests.append({
            "replaceAllText": {
                "containsText": {
                    "text": "TAKUMI AKIYAMA",  # テンプレートの旧ローマ字
                    "matchCase": True
                },
                "replaceText": romaji,
                "pageObjectIds": [new_slide_id]
            }
        })

    return requests


# ==============================================================
# より堅実なアプローチ:
#   1. まずテンプレートスライドのテキスト要素IDを取得
#   2. スライドを複製 (duplicateObject)
#   3. 複製後のスライドのテキストボックスを updateText で書き換える
# ==============================================================

def get_template_text_element_ids(service, presentation_id, template_slide_id):
    """テンプレートスライド内のテキストボックス要素 (objectId, content) を取得"""
    pres = service.presentations().get(presentationId=presentation_id).execute()
    for slide in pres.get('slides', []):
        if slide.get('objectId') == template_slide_id:
            text_elements = []
            for el in slide.get('pageElements', []):
                if 'shape' not in el:
                    continue
                shape = el['shape']
                if 'text' not in shape:
                    continue
                content_parts = []
                for te in shape['text'].get('textElements', []):
                    if 'textRun' in te:
                        content_parts.append(te['textRun'].get('content', ''))
                full_text = ''.join(content_parts).strip()
                if full_text:
                    text_elements.append({
                        'objectId': el['objectId'],
                        'text': full_text
                    })
            return text_elements
    return []


def main():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('slides', 'v1', credentials=credentials)

    # テンプレートスライドのテキスト要素を取得
    template_elements = get_template_text_element_ids(
        service, PRESENTATION_ID, TEMPLATE_SLIDE_ID)
    print("テンプレートのテキスト要素:")
    for el in template_elements:
        print(f"  id={el['objectId']} text={el['text']!r}")

    # 各員についてスライドを複製してテキストを差し替える
    all_requests = []
    new_slide_ids = []

    for i, name in enumerate(MISSING_MEMBERS):
        new_slide_id = f"gNEW_{i}"
        new_slide_ids.append(new_slide_id)

        # 複製
        all_requests.append({
            "duplicateObject": {
                "objectId": TEMPLATE_SLIDE_ID,
                "objectIds": {
                    TEMPLATE_SLIDE_ID: new_slide_id
                }
            }
        })

    # 一括実行（複製のみ先に）
    print(f"\n{len(MISSING_MEMBERS)}名分のスライドを複製中...")
    body = {"requests": all_requests}
    resp = service.presentations().batchUpdate(
        presentationId=PRESENTATION_ID, body=body).execute()
    print(f"複製完了: {len(resp.get('replies', []))} 件の応答")

    # 複製されたスライドのテキスト要素IDを取得
    pres = service.presentations().get(presentationId=PRESENTATION_ID).execute()
    slide_map = {}  # new_slide_id → slide data
    for slide in pres.get('slides', []):
        if slide.get('objectId') in new_slide_ids:
            slide_map[slide['objectId']] = slide

    # 名前とローマ字のマッピング（姓→名の順にローマ字、既存スライドパターン準拠）
    KANJI_ROMAJI = {
        "廣田珠輝": ("SHUKI", "HIROTA"),
        "吉村行雲": ("YUKUMO", "YOSHIMURA"),
        "塩見慎太郎": ("SHENTARO", "SHIOMI"),
        "本田顕士": ("AKASHI", "HONDA"),
        "藤村俊枝": ("TOSHIE", "FUJIMURA"),
        "石井晴": ("HARU", "ISHII"),
        "熊谷侑輝": ("YUKI", "KUMAGAI"),
        "安藤優世": ("YUSEI", "ANDO"),
        "星野優輝": ("YUKI", "HOSHINO"),
        "栗原堅太": ("KENTA", "KURIHARA"),
        "村中媛香": ("ERIKA", "MURANAKA"),
        "島田優": ("YUTA", "SHIMADA"),
        "並河真一": ("SHINICHI", "NAMIKAWA"),
        "進藤彪": ("TAKESHI", "SHINDO"),
        "熊倉空大": ("KODAI", "KURAKURA"),
        "吉房つばさ": ("TSUBASA", "YOSHIBUSA"),
        "大関秀": ("HIDEKI", "OSEKI"),
        "髙未佳": ("MIKA", "TAKAMI"),     # ※要確認
        "堀野昌樹": ("MASAKI", "HORINO"),
        "森本風子": ("FUKOKO", "MORIMOTO"),
        "大村愛咲": ("ASAKI", "OMURA"),
        "宮良高基": ("TAKAKI", "MIYARA"),
        "吉川秀斗": ("SHUTO", "YOSHIKAWA"),
        "幡野智也": ("TOMOYA", "HATANO"),
    }

    # updateText リクエスト生成
    update_requests = []
    for i, name in enumerate(MISSING_MEMBERS):
        slide_id = f"gNEW_{i}"
        slide_data = slide_map.get(slide_id)
        if not slide_data:
            print(f"  WARNING: slide {slide_id} not found, skipping")
            continue

        given, family = KANJI_ROMAJI.get(name, (name, ""))
        romaji_str = f"{given} {family}"

        # テキストボックス要素を探す
        for el in slide_data.get('pageElements', []):
            if 'shape' not in el or 'text' not in el['shape']:
                continue
            shape = el['shape']
            content_parts = []
            for te in shape['text'].get('textElements', []):
                if 'textRun' in te:
                    content_parts.append(te['textRun'].get('content', ''))
            full_text = ''.join(content_parts).strip()

            if "秋山" in full_text or "匠" in full_text:
                # 名前テキストボックス
                update_requests.append({
                    "deleteText": {
                        "objectId": el['objectId'],
                        "textRange": {"type": "ALL"}
                    }
                })
                update_requests.append({
                    "insertText": {
                        "objectId": el['objectId'],
                        "insertionIndex": 0,
                        "text": name
                    }
                })
            elif "TAKUMI" in full_text or "AKIYAMA" in full_text:
                # ローマ字テキストボックス
                update_requests.append({
                    "deleteText": {
                        "objectId": el['objectId'],
                        "textRange": {"type": "ALL"}
                    }
                })
                update_requests.append({
                    "insertText": {
                        "objectId": el['objectId'],
                        "insertionIndex": 0,
                        "text": romaji_str
                    }
                })

    print(f"\nテキスト更新リクエスト {len(update_requests)} 件を実行...")
    # 50件ずつに分割して実行（API制限対策）
    chunk_size = 50
    for chunk_start in range(0, len(update_requests), chunk_size):
        chunk = update_requests[chunk_start:chunk_start + chunk_size]
        body = {"requests": chunk}
        resp = service.presentations().batchUpdate(
            presentationId=PRESENTATION_ID, body=body).execute()
        print(f"  チャンク {chunk_start//chunk_size + 1}: {len(resp.get('replies', []))} 件完了")

    print("\n✅ 全スライド作成完了！")
    print(f"追加されたメンバー: {', '.join(MISSING_MEMBERS)}")


if __name__ == '__main__':
    main()
