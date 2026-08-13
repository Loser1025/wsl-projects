# -*- coding: utf-8 -*-
"""Phase 2+3: create & style the new UNLOCK-night layout."""
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

DISPLAY = 'Archivo Black'
SERIF = 'Noto Serif JP'
SANS = 'Noto Sans JP'
MONO = 'Roboto Mono'

SLIDES = {
    'cover': 'p',
    's1': 'g3f6752b87ae_0_0',
    's2': 'g3f6752b87ae_0_7',
    's3': 'g3f6752b87ae_0_14',
    's4': 'g3f6752b87ae_0_19',
    'close': 'g3f6752b87ae_0_25',
}


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


def para_align(obj_id, alignment):
    return {'updateParagraphStyle': {'objectId': obj_id, 'style': {'alignment': alignment}, 'fields': 'alignment'}}


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


reqs = []

# ---- backgrounds (all slides night) ----
for sid in SLIDES.values():
    reqs.append({
        'updatePageProperties': {
            'objectId': sid, 'fields': 'pageBackgroundFill',
            'pageProperties': {'pageBackgroundFill': {'solidFill': {'color': rgb_wrap(NIGHT)}}}
        }
    })

# ---- recolor existing keyhole rings (cover + closing) to brass-soft, thin ----
for rid in ['ring_p_bl', 'ring_p_tr', 'ring_c_bl', 'ring_c_tr']:
    pass  # these were deleted in phase 1; rebuilt below

# cover keyhole rings (recreate)
reqs.append(create_rect('ring_p_tr', SLIDES['cover'], 7550000, -650000, 1800000, 1800000, 'ELLIPSE'))
reqs.append(no_fill('ring_p_tr'))
reqs.append(outline('ring_p_tr', BRASS_SOFT, 1.0, 0.6))
reqs.append(create_rect('ring_p_bl', SLIDES['cover'], -650000, 4200000, 1400000, 1400000, 'ELLIPSE'))
reqs.append(no_fill('ring_p_bl'))
reqs.append(outline('ring_p_bl', BRASS_SOFT, 1.0, 0.6))
# small keyhole motif near wordmark
reqs.append(create_rect('keyhole_circle', SLIDES['cover'], 6300000, 1150000, 950000, 950000, 'ELLIPSE'))
reqs.append(no_fill('keyhole_circle'))
reqs.append(outline('keyhole_circle', BRASS_SOFT, 1.25, 0.7))
reqs.append(create_rect('keyhole_wedge', SLIDES['cover'], 6520000, 2000000, 510000, 620000, 'TRIANGLE'))
reqs.append(no_fill('keyhole_wedge'))
reqs.append(outline('keyhole_wedge', BRASS_SOFT, 1.25, 0.7))

# closing keyhole rings
reqs.append(create_rect('ring_c_tr', SLIDES['close'], 7550000, -650000, 1800000, 1800000, 'ELLIPSE'))
reqs.append(no_fill('ring_c_tr'))
reqs.append(outline('ring_c_tr', BRASS_SOFT, 1.0, 0.6))
reqs.append(create_rect('ring_c_bl', SLIDES['close'], -650000, 4200000, 1400000, 1400000, 'ELLIPSE'))
reqs.append(no_fill('ring_c_bl'))
reqs.append(outline('ring_c_bl', BRASS_SOFT, 1.0, 0.6))
# the "opened light line" bookend
reqs.append(create_rect('open_line', SLIDES['close'], MARGIN, 2550000, CW, 9525, 'RECTANGLE'))
reqs.append(fill('open_line', BRASS, 0.8))
reqs.append(no_outline('open_line'))

# =====================================================================
# COVER
# =====================================================================
reqs.append(insert_text('i0', 'UNLOCK'))
reqs.append(style_text('i0', size=80, bold=True, color=BRASS, font=DISPLAY))
reqs.append({
    'updatePageElementTransform': {
        'objectId': 'i0', 'applyMode': 'ABSOLUTE',
        'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': MARGIN, 'translateY': 1550000, 'unit': 'EMU'}
    }
})
reqs.append({
    'updateShapeProperties': {
        'objectId': 'i0', 'fields': 'contentAlignment', 'shapeProperties': {'contentAlignment': 'MIDDLE'}
    }
})

reqs.append(insert_text('i1', 'グループコーチング　ご説明資料'))
reqs.append(style_text('i1', size=17, bold=False, color=PARCH, font=SERIF))
reqs.append({
    'updatePageElementTransform': {
        'objectId': 'i1', 'applyMode': 'ABSOLUTE',
        'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': MARGIN, 'translateY': 2650000, 'unit': 'EMU'}
    }
})

reqs.append(create_textbox('cover_kicker', SLIDES['cover'], MARGIN, 4550000, 6000000, 300000))
reqs.append(insert_text('cover_kicker', 'KEY PROGRAM  ·  毎週水曜 20:00 START'))
reqs.append(style_text('cover_kicker', size=10, bold=False, color=MUTED, font=MONO))

# =====================================================================
# helper for a standard "kicker + title" header used on slides 1-4
# =====================================================================

def header(tag, slide_id, num, label, title_id, title_size=26):
    r = []
    kicker_id = f'kicker_{tag}'
    r.append(create_textbox(kicker_id, slide_id, MARGIN, 380000, 6500000, 260000))
    r.append(insert_text(kicker_id, f'{num} — {label}'))
    r.append(style_text(kicker_id, size=10, bold=False, color=BRASS, font=MONO))
    r.append(style_text(title_id, size=title_size, bold=True, color=PARCH, font=SERIF))
    r.append({
        'updatePageElementTransform': {
            'objectId': title_id, 'applyMode': 'ABSOLUTE',
            'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': MARGIN, 'translateY': 700000, 'unit': 'EMU'}
        }
    })
    return r


reqs += header('s1', SLIDES['s1'], '01', '当プログラムの特徴', 'g3f6752b87ae_0_1')
reqs += header('s2', SLIDES['s2'], '02', 'セッションの4つの柱', 'g3f6752b87ae_0_8')
reqs += header('s3', SLIDES['s3'], '03', '料金システムとサポート体制', 'g3f6752b87ae_0_15')
reqs += header('s4', SLIDES['s4'], '04', '基本スケジュール（毎週水曜20時）', 'g3f6752b87ae_0_20', title_size=22)
reqs += header('close', SLIDES['close'], '05', 'さあ、はじめよう', 'g3f6752b87ae_0_26', title_size=30)

# =====================================================================
# SLIDE 1 — features (lede paragraphs, reuse original textbox g3f6752b87ae_0_2 is deleted; recreate)
# =====================================================================
reqs.append(create_textbox('s1_body', SLIDES['s1'], MARGIN, 1500000, CW - 300000, 2600000))
body1 = ('セッションから個人サポートまでを包括的に提供する、全く新しいキャリアコーチングプログラムです。\n\n'
         '一方的なインプットで終わらせず、あなたのキャリアと人生に専任コーチが徹底的に向き合います。\n\n'
         '「変わりたい」という想いを、具体的な「決断」と「行動」へと昇華させるためのハイブリッド形式を採用しています。')
reqs.append(insert_text('s1_body', body1))
reqs.append(style_text('s1_body', size=13.5, bold=False, color=PARCH_DIM, font=SANS))

# =====================================================================
# SLIDE 2 — 4 pillars grid
# =====================================================================
pillars = [
    ('01', '自分は源', '全ての出来事の源泉は自分にあるという、ブレない当事者意識と主体性を養います。'),
    ('02', '表層と深層', '言葉の概念を理解し、根本的に日常に変革を起こすやり方をお伝えします。'),
    ('03', 'ピークステート', '常に最高のパフォーマンスを発揮するための、心身の高度な状態管理術を習得します。'),
    ('04', '決断', '迷いを断ち切り、自らのキャリアを力強く切り拓くための強靰な「決断」までサポート致します。'),
]
grid_y0 = 1550000
cell_w = CW // 2
cell_h = 1450000
for i, (num, title, desc) in enumerate(pillars):
    col = i % 2
    row = i // 2
    x = MARGIN + col * cell_w
    y = grid_y0 + row * cell_h
    cell_id = f'pillar_cell_{i}'
    reqs.append(create_rect(cell_id, SLIDES['s2'], x, y, cell_w, cell_h))
    reqs.append(no_fill(cell_id))
    reqs.append(outline(cell_id, PARCH, 0.75, 0.15))
    reqs.append(zorder(cell_id, 'SEND_TO_BACK'))

    pad = 260000
    num_id = f'pillar_num_{i}'
    reqs.append(create_textbox(num_id, SLIDES['s2'], x + pad, y + 140000, 800000, 260000))
    reqs.append(insert_text(num_id, num))
    reqs.append(style_text(num_id, size=10, bold=False, color=BRASS_SOFT, font=MONO))

    title_id = f'pillar_title_{i}'
    reqs.append(create_textbox(title_id, SLIDES['s2'], x + pad, y + 420000, cell_w - 2 * pad, 380000))
    reqs.append(insert_text(title_id, title))
    reqs.append(style_text(title_id, size=15, bold=False, color=PARCH, font=SERIF))

    desc_id = f'pillar_desc_{i}'
    reqs.append(create_textbox(desc_id, SLIDES['s2'], x + pad, y + 780000, cell_w - 2 * pad, cell_h - 900000))
    reqs.append(insert_text(desc_id, desc))
    reqs.append(style_text(desc_id, size=10.5, bold=False, color=PARCH_DIM, font=SANS))

# =====================================================================
# SLIDE 3 — investment (price tag + lede)
# =====================================================================
price_x, price_y = MARGIN, 1600000
price_w, price_h = 2900000, 2500000
reqs.append(create_rect('price_box', SLIDES['s3'], price_x, price_y, price_w, price_h))
reqs.append(no_fill('price_box'))
reqs.append(outline('price_box', BRASS_SOFT, 1.25, 1.0))

reqs.append(create_textbox('price_label', SLIDES['s3'], price_x + 220000, price_y + 220000, price_w - 440000, 260000))
reqs.append(insert_text('price_label', 'MONTHLY / 1名様'))
reqs.append(style_text('price_label', size=9, bold=False, color=MUTED, font=MONO))

reqs.append(create_textbox('price_amount', SLIDES['s3'], price_x + 220000, price_y + 500000, price_w - 440000, 900000))
reqs.append(insert_text('price_amount', '￥980'))
reqs.append(style_text('price_amount', size=52, bold=True, color=EMBER, font=MONO))

reqs.append(create_textbox('price_unit', SLIDES['s3'], price_x + 220000, price_y + 1420000, price_w - 440000, 260000))
reqs.append(insert_text('price_unit', '全て込み（税込）'))
reqs.append(style_text('price_unit', size=11, bold=False, color=PARCH_DIM, font=SANS))

reqs.append(create_rect('price_div', SLIDES['s3'], price_x + 220000, price_y + 1780000, price_w - 440000, 6350))
reqs.append(fill('price_div', PARCH, 0.18))
reqs.append(no_outline('price_div'))

reqs.append(create_textbox('price_kicker', SLIDES['s3'], price_x + 220000, price_y + 1900000, price_w - 440000, 400000))
reqs.append(insert_text('price_kicker', '圧倒的なコストパフォーマンス'))
reqs.append(style_text('price_kicker', size=12, bold=False, color=BRASS, font=SERIF))

lede_x = price_x + price_w + 500000
lede_w = W - MARGIN - lede_x
reqs.append(create_textbox('invest_lede', SLIDES['s3'], lede_x, price_y + 200000, lede_w, price_h - 200000))
lede3 = ('隔週でのグループセッション参加と、その間の週での1on1個別面談。'
          'this_placeholder')
lede3 = ('隔週でのグループセッション参加と、その間の週での1on1個別面談。'
          'この綻密で継続的なサポート体制を、どなたでも挑戦しやすい価格設定で提供いたします。\n\n'
          '「本気の自己変革」に向けた自己投資の第一歩として、最適な環境をご用意してお待ちしております。')
reqs.append(insert_text('invest_lede', lede3))
reqs.append(style_text('invest_lede', size=12.5, bold=False, color=PARCH_DIM, font=SANS))

# =====================================================================
# SLIDE 4 — schedule timeline
# =====================================================================
weeks = [
    ('第1週（9/30～）', '【グループセッション】', 'コアとなるテーマのインプットと実践ワークを実施。'),
    ('第2週', '【1on1個別面談】', 'セッションの学びを個人のキャリア課題へ落とし込み。'),
    ('第3週', '【グループセッション】', '新たなテーマに挑戦し、さらなる視座を獲得。'),
    ('第4週以降', '【1on1個別面談】', '継続的な対話を通じ、確実な行動変容と自己変革を促進。'),
]
tl_x = MARGIN + 60000
tl_y0 = 1550000
tl_row_h = 780000
reqs.append(create_rect('tl_spine', SLIDES['s4'], tl_x, tl_y0 + 60000, 6350, tl_row_h * len(weeks) - 120000))
reqs.append(fill('tl_spine', BRASS_SOFT, 0.55))
reqs.append(no_outline('tl_spine'))

for i, (wk, tag, desc) in enumerate(weeks):
    y = tl_y0 + i * tl_row_h
    dot_id = f'tl_dot_{i}'
    reqs.append(create_rect(dot_id, SLIDES['s4'], tl_x - 65000, y + 40000, 140000, 140000, 'ELLIPSE'))
    reqs.append(fill(dot_id, NIGHT, 1.0))
    reqs.append(outline(dot_id, BRASS, 1.25, 1.0))

    wk_id = f'tl_wk_{i}'
    reqs.append(create_textbox(wk_id, SLIDES['s4'], tl_x + 260000, y, 2000000, 260000))
    reqs.append(insert_text(wk_id, wk))
    reqs.append(style_text(wk_id, size=10, bold=False, color=BRASS_SOFT, font=MONO))

    tag_id = f'tl_tag_{i}'
    reqs.append(create_textbox(tag_id, SLIDES['s4'], tl_x + 260000, y + 240000, 3000000, 300000))
    reqs.append(insert_text(tag_id, tag))
    reqs.append(style_text(tag_id, size=13, bold=False, color=PARCH, font=SERIF))

    desc_id = f'tl_desc_{i}'
    reqs.append(create_textbox(desc_id, SLIDES['s4'], tl_x + 260000, y + 520000, CW - 900000, 240000))
    reqs.append(insert_text(desc_id, desc))
    reqs.append(style_text(desc_id, size=10.5, bold=False, color=PARCH_DIM, font=SANS))

# =====================================================================
# SLIDE 5 — closing
# =====================================================================
reqs.append(style_text('g3f6752b87ae_0_26', size=34, bold=False, color=PARCH, font=SERIF))
reqs.append({
    'updatePageElementTransform': {
        'objectId': 'g3f6752b87ae_0_26', 'applyMode': 'ABSOLUTE',
        'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': MARGIN, 'translateY': 1250000, 'unit': 'EMU'}
    }
})

badge_x, badge_y = MARGIN, 2750000
badge_w, badge_h = 3200000, 620000
reqs.append(create_rect('close_badge', SLIDES['close'], badge_x, badge_y, badge_w, badge_h))
reqs.append(no_fill('close_badge'))
reqs.append(outline('close_badge', BRASS_SOFT, 1.0, 1.0))
reqs.append(create_textbox('close_badge_txt', SLIDES['close'], badge_x + 200000, badge_y + 140000, badge_w - 400000, 360000))
reqs.append(insert_text('close_badge_txt', '9月30日（水）　／　 20:00 START'))
reqs.append(style_text('close_badge_txt', size=13, bold=False, color=BRASS, font=MONO))

reqs.append(create_textbox('close_note', SLIDES['close'], MARGIN, 3650000, CW - 700000, 900000))
note5 = '皆様のキャリアへの本気の挑戦を、全力でサポートいたします。 ※お問い合わせ先入れたい'
reqs.append(insert_text('close_note', note5))
reqs.append(style_text('close_note', size=12, bold=False, color=PARCH_DIM, font=SANS))

print('Total requests:', len(reqs))

# send in chunks to respect the 60-writes/min quota while keeping few HTTP calls
CHUNK = 90
for i in range(0, len(reqs), CHUNK):
    chunk = reqs[i:i + CHUNK]
    r = tool.batch_update(PID, chunk)
    print(f'  chunk {i}-{i+len(chunk)}: {"OK" if r is not None else "FAILED"}')

print('Done.')
