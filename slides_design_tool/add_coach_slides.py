# -*- coding: utf-8 -*-
"""Add 2 coach-profile slides matching the UNLOCK-night design system."""
from slides_design_tool import GoogleSlidesTool

PID = '1A9AUnUZGmq4YCb-rKPPUgvFTArNHjgyjLuJXKff5XEU'
tool = GoogleSlidesTool(credentials_path='credentials.json')

W, H = 9144000, 5143500
MARGIN = 450000
CW = W - 2 * MARGIN

NIGHT = (0.071, 0.078, 0.110)
BRASS = (0.753, 0.541, 0.275)
BRASS_SOFT = (0.561, 0.439, 0.282)
EMBER = (0.886, 0.341, 0.173)
PARCH = (0.925, 0.902, 0.847)
PARCH_DIM = (0.812, 0.788, 0.737)
MUTED = (0.525, 0.545, 0.627)

SERIF = 'Noto Serif JP'
SANS = 'Noto Sans JP'
MONO = 'Roboto Mono'


def rgb(c):
    return {'red': c[0], 'green': c[1], 'blue': c[2]}


def rgb_wrap(c):
    return {'rgbColor': rgb(c)}


def color_field(c):
    return {'opaqueColor': {'rgbColor': rgb(c)}}


def create_textbox(obj_id, slide_id, x, y, w, h):
    return {
        'createShape': {
            'objectId': obj_id, 'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': w, 'unit': 'EMU'}, 'height': {'magnitude': h, 'unit': 'EMU'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': x, 'translateY': y, 'unit': 'EMU'}
            }
        }
    }


def create_rect(obj_id, slide_id, x, y, w, h, shape_type='RECTANGLE'):
    return {
        'createShape': {
            'objectId': obj_id, 'shapeType': shape_type,
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': w, 'unit': 'EMU'}, 'height': {'magnitude': h, 'unit': 'EMU'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': x, 'translateY': y, 'unit': 'EMU'}
            }
        }
    }


def insert_text(obj_id, text):
    return {'insertText': {'objectId': obj_id, 'text': text}}


def style_text(obj_id, size=None, bold=None, color=None, font=None):
    style = {}
    fields = []
    if size is not None:
        style['fontSize'] = {'magnitude': size, 'unit': 'PT'}; fields.append('fontSize')
    if bold is not None:
        style['bold'] = bold; fields.append('bold')
    if font is not None:
        style['fontFamily'] = font
        style['weightedFontFamily'] = {'fontFamily': font, 'weight': 700 if bold else 400}
        fields.append('fontFamily'); fields.append('weightedFontFamily')
    if color is not None:
        style['foregroundColor'] = color_field(color); fields.append('foregroundColor')
    return {'updateTextStyle': {'objectId': obj_id, 'style': style, 'fields': ','.join(fields)}}


def fill(obj_id, color, alpha=1.0):
    return {
        'updateShapeProperties': {
            'objectId': obj_id, 'fields': 'shapeBackgroundFill.solidFill.color,shapeBackgroundFill.solidFill.alpha',
            'shapeProperties': {'shapeBackgroundFill': {'solidFill': {'color': rgb_wrap(color), 'alpha': alpha}}}
        }
    }


def no_fill(obj_id):
    return {
        'updateShapeProperties': {
            'objectId': obj_id, 'fields': 'shapeBackgroundFill.propertyState',
            'shapeProperties': {'shapeBackgroundFill': {'propertyState': 'NOT_RENDERED'}}
        }
    }


def outline(obj_id, color, weight_pt=1.0, alpha=1.0, dash='SOLID'):
    return {
        'updateShapeProperties': {
            'objectId': obj_id,
            'fields': 'outline.propertyState,outline.weight,outline.dashStyle,outline.outlineFill.solidFill.color,outline.outlineFill.solidFill.alpha',
            'shapeProperties': {
                'outline': {
                    'propertyState': 'RENDERED',
                    'weight': {'magnitude': weight_pt, 'unit': 'PT'},
                    'dashStyle': dash,
                    'outlineFill': {'solidFill': {'color': rgb_wrap(color), 'alpha': alpha}}
                }
            }
        }
    }


def no_outline(obj_id):
    return {
        'updateShapeProperties': {
            'objectId': obj_id, 'fields': 'outline.propertyState',
            'shapeProperties': {'outline': {'propertyState': 'NOT_RENDERED'}}
        }
    }


def zorder(obj_id, op):
    return {'updatePageElementsZOrder': {'pageElementObjectIds': [obj_id], 'operation': op}}


COACHES = [
    {
        'tag': 'coach1',
        'slide_num': '06',
        'sub_idx': '01 / 02',
        'name': '水澤七彩（28歳）',
        'type': '可能性フォーカス・伴走型タイプ',
        'desc': '相手の隠れた強みや本音にピント（Focus）を合わせ、時間を惜しまず寄り添いながら、現状の枠を越えた未来へと共に走り抜ける。',
        'results': [
            '女性初の事業部長へ抜擢',
            '全社営業成績ランキング1位獲得',
            '担当顧客が1年目から最優秀新人賞獲得',
        ],
        'audience': [
            '何かを変えたいと思っている人',
            '現状に満足していない人',
            '自分が誇れる成果や実績を獲得したい人',
        ],
    },
    {
        'tag': 'coach2',
        'slide_num': '06',
        'sub_idx': '02 / 02',
        'name': '鈴木貴大（31歳）',
        'type': 'エンパワー伴走型タイプ',
        'desc': '顧客自身よりも顧客の可能性、GOALを信じ抜き、エンパワーで人生を前進させます。',
        'results': [
            '所属現場の統括になる',
            '社内グループコーチング運営へ',
            '昇進',
        ],
        'audience': [
            '人生と自分を達観している人',
            '自分のキャリアを本気であきらめたくない人',
            '本気で人生を良くしたいと思ってる人',
        ],
    },
]

# ---------------------------------------------------------------
# 1) create the two new blank slides, inserted just before closing
# ---------------------------------------------------------------
create_slide_reqs = [
    {'createSlide': {'objectId': 'coach1_slide', 'insertionIndex': 5,
                      'slideLayoutReference': {'predefinedLayout': 'BLANK'}}},
    {'createSlide': {'objectId': 'coach2_slide', 'insertionIndex': 6,
                      'slideLayoutReference': {'predefinedLayout': 'BLANK'}}},
]
r = tool.batch_update(PID, create_slide_reqs)
print('create slides:', r is not None)

SLIDE_IDS = {'coach1': 'coach1_slide', 'coach2': 'coach2_slide'}

reqs = []

for c in COACHES:
    sid = SLIDE_IDS[c['tag']]
    t = c['tag']

    reqs.append({
        'updatePageProperties': {
            'objectId': sid, 'fields': 'pageBackgroundFill',
            'pageProperties': {'pageBackgroundFill': {'solidFill': {'color': rgb_wrap(NIGHT)}}}
        }
    })

    # decorative corner ring (same motif family as cover/closing)
    ring_id = f'{t}_ring'
    reqs.append(create_rect(ring_id, sid, 7750000, -700000, 1700000, 1700000, 'ELLIPSE'))
    reqs.append(no_fill(ring_id))
    reqs.append(outline(ring_id, BRASS_SOFT, 1.0, 0.55))

    # kicker
    kicker_id = f'{t}_kicker'
    reqs.append(create_textbox(kicker_id, sid, MARGIN, 380000, 6500000, 260000))
    reqs.append(insert_text(kicker_id, f"{c['slide_num']} — 講師紹介　{c['sub_idx']}"))
    reqs.append(style_text(kicker_id, size=10, bold=False, color=BRASS, font=MONO))

    # name (serif, large, parchment)
    name_id = f'{t}_name'
    reqs.append(create_textbox(name_id, sid, MARGIN, 680000, 6500000, 720000))
    reqs.append(insert_text(name_id, c['name']))
    reqs.append(style_text(name_id, size=34, bold=True, color=PARCH, font=SERIF))

    # type tag (bordered pill-like box)
    tag_id = f'{t}_tagbox'
    tag_w = min(5800000, 260000 + len(c['type']) * 165000)
    reqs.append(create_rect(tag_id, sid, MARGIN, 1480000, tag_w, 420000))
    reqs.append(no_fill(tag_id))
    reqs.append(outline(tag_id, BRASS_SOFT, 1.0, 1.0))
    tag_txt_id = f'{t}_tagtxt'
    reqs.append(create_textbox(tag_txt_id, sid, MARGIN + 180000, 1480000 + 90000, tag_w - 300000, 260000))
    reqs.append(insert_text(tag_txt_id, c['type']))
    reqs.append(style_text(tag_txt_id, size=12, bold=False, color=BRASS, font=SERIF))

    # description
    desc_id = f'{t}_desc'
    reqs.append(create_textbox(desc_id, sid, MARGIN, 2060000, CW - 300000, 700000))
    reqs.append(insert_text(desc_id, c['desc']))
    reqs.append(style_text(desc_id, size=12.5, bold=False, color=PARCH_DIM, font=SANS))

    # divider
    div_id = f'{t}_div'
    reqs.append(create_rect(div_id, sid, MARGIN, 2820000, CW, 6350))
    reqs.append(fill(div_id, PARCH, 0.14))
    reqs.append(no_outline(div_id))

    # two columns
    col_gap = 500000
    col_w = (CW - col_gap) / 2
    col_y = 3020000
    cols = [
        ('定量実績', c['results'], MARGIN, EMBER),
        ('コーチングを受けてほしい人', c['audience'], MARGIN + col_w + col_gap, BRASS),
    ]
    for ci, (head, items, x0, accent) in enumerate(cols):
        head_id = f'{t}_col{ci}_head'
        reqs.append(create_textbox(head_id, sid, x0, col_y, col_w, 300000))
        reqs.append(insert_text(head_id, head))
        reqs.append(style_text(head_id, size=12, bold=True, color=accent, font=SERIF))

        item_y = col_y + 380000
        for ii, item in enumerate(items):
            num_id = f'{t}_col{ci}_num{ii}'
            reqs.append(create_textbox(num_id, sid, x0, item_y, 260000, 260000))
            reqs.append(insert_text(num_id, str(ii + 1)))
            reqs.append(style_text(num_id, size=11, bold=False, color=accent, font=MONO))

            txt_id = f'{t}_col{ci}_txt{ii}'
            reqs.append(create_textbox(txt_id, sid, x0 + 300000, item_y - 20000, col_w - 300000, 340000))
            reqs.append(insert_text(txt_id, item))
            reqs.append(style_text(txt_id, size=11.5, bold=False, color=PARCH_DIM, font=SANS))

            item_y += 400000

print('Total element requests:', len(reqs))
CHUNK = 90
for i in range(0, len(reqs), CHUNK):
    chunk = reqs[i:i + CHUNK]
    rr = tool.batch_update(PID, chunk)
    print(f'  chunk {i}-{i+len(chunk)}: {"OK" if rr is not None else "FAILED"}')

print('Done.')
