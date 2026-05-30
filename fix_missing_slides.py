#!/usr/bin/env python3
"""
複製された24枚のスライドについて、テンプレートの「面井　洸聖 / OMOI HIROTO」を
正しいメンバー名・ローマ字に差し替える。

各スライドのテキストボックス:
  - STAFF ラベル (そのまま維持)
  - 名前テキストボックス: 「面井　洸聖」→ 実際の名前
  - ローマ字テキストボックス: 「OMOI HIROTO」→ 実際のローマ字

要素IDパターン:
  Slide i (gNEW_i):
    STAFF =  SLIDES_API1415004689_{offset}
   名前 =   SLIDES_API1415004689_{offset+1}
   ローマ字 = SLIDES_API1415004689_{offset+2}

  offset = 2 + (i * 3)   (i=0 → offset=2, i=1 → offset=9, ...)
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
PRESENTATION_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'
SCOPES = ['https://www.googleapis.com/auth/presentations']

# メンバーとローマ字（given family 順 = 名 姓）
MEMBERS_ROMAJI = [
    ("廣田珠輝",    "SHUKI HIROTA"),
    ("吉村行雲",    "YUKUMO YOSHIMURA"),
    ("塩見慎太郎",  "SHENTARO SHIOMI"),
    ("本田顕士",    "AKASHI HONDA"),
    ("藤村俊枝",    "TOSHIE FUJIMURA"),
    ("石井晴",      "HARU ISHII"),
    ("熊谷侑輝",    "YUKI KUMAGAI"),
    ("安藤優世",    "YUSEI ANDO"),
    ("星野優輝",    "YUKI HOSHINO"),
    ("栗原堅太",    "KENTA KURIHARA"),
    ("村中媛香",    "ERIKA MURANAKA"),
    ("島田優",      "YUTA SHIMADA"),
    ("並河真一",    "SHINICHI NAMIKAWA"),
    ("進藤彪",      "TAKESHI SHINDO"),
    ("熊倉空大",    "KODAI KURAKURA"),
    ("吉房つばさ",  "TSUBASA YOSHIBUSA"),
    ("大関秀",      "HIDEKI OSEKI"),
    ("髙未佳",      "MIKA TAKAMI"),
    ("堀野昌樹",    "MASAKI HORINO"),
    ("森本風子",    "FUKOKO MORIMOTO"),
    ("大村愛咲",    "ASAKI OMURA"),
    ("宮良高基",    "TAKAKI MIYARA"),
    ("吉川秀斗",    "SHUTO YOSHIKAWA"),
    ("幡野智也",    "TOMOYA HATANO"),
]


def element_id(base, offset):
    return f"SLIDES_API{base}_{offset}"


def main():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('slides', 'v1', credentials=credentials)

    API_BASE = "1415004689"

    # 全スライドの要素ID収集
    pres = service.presentations().get(presentationId=PRESENTATION_ID).execute()
    new_slide_ids = {f"gNEW_{i}" for i in range(24)}

    # Slide i → 要素IDのマッニング
    slide_elements = {}  # i → {"name": eid, "romaji": eid, "staff": eid}
    for slide in pres.get('slides', []):
        sid = slide['objectId']
        if sid not in new_slide_ids:
            continue
        i = int(sid.split('_')[1])
        text_boxes = []
        for el in slide.get('pageElements', []):
            if 'shape' not in el or 'text' not in el['shape']:
                continue
            parts = []
            for te in el['shape']['text'].get('textElements', []):
                if 'textRun' in te:
                    parts.append(te['textRun'].get('content', ''))
            full_text = ''.join(parts).strip()
            text_boxes.append({'eid': el['objectId'], 'text': full_text})

        # 3つのテキストボックスを特定
        name_eid = None
        romaji_eid = None
        staff_eid = None
        for tb in text_boxes:
            if '面井' in tb['text'] or '洸聖' in tb['text']:
                name_eid = tb['eid']
            elif 'OMOI' in tb['text'] or 'HIROTO' in tb['text']:
                romaji_eid = tb['eid']
            elif 'STAFF' in tb['text']:
                staff_eid = tb['eid']

        slide_elements[i] = {'name': name_eid, 'romaji': romaji_eid, 'staff': staff_eid}
        print(f"  Slide {i}: name_eid={name_eid}, romaji_eid={romaji_eid}")

    # updateText リクエスト作成
    requests = []
    for i, (name, romaji) in enumerate(MEMBERS_ROMAJI):
        elems = slide_elements.get(i)
        if not elems:
            print(f"  WARNING: Slide {i} elements not found, skip")
            continue

        # 名前テキストボックスを差し替え
        if elems['name']:
            requests.append({
                "deleteText": {
                    "objectId": elems['name'],
                    "textRange": {"type": "ALL"}
                }
            })
            requests.append({
                "insertText": {
                    "objectId": elems['name'],
                    "insertionIndex": 0,
                    "text": name
                }
            })

        # ローマ字テキストボックスを差し替え
        if elems['romaji']:
            requests.append({
                "deleteText": {
                    "objectId": elems['romaji'],
                    "textRange": {"type": "ALL"}
                }
            })
            requests.append({
                "insertText": {
                    "objectId": elems['romaji'],
                    "insertionIndex": 0,
                    "text": romaji
                }
            })

    print(f"\n{len(requests)} 件の更新リクエストを実行...")

    # 50件ずつに分割して実行
    chunk_size = 50
    for chunk_start in range(0, len(requests), chunk_size):
        chunk = requests[chunk_start:chunk_start + chunk_size]
        body = {"requests": chunk}
        resp = service.presentations().batchUpdate(
            presentationId=PRESENTATION_ID, body=body).execute()
        print(f"  チャンク {chunk_start//chunk_size + 1}/"
              f"{(len(requests)+chunk_size-1)//chunk_size}: "
              f"{len(resp.get('replies', []))} 件完了")

    print("\n✅ 全24名分のスライドテキストを更新しました！")
    for name, romaji in MEMBERS_ROMAJI:
        print(f"  {name} → {romaji}")


if __name__ == '__main__':
    main()
