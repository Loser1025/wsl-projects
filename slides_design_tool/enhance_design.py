from slides_design_tool import GoogleSlidesTool

PID = '1A9AUnUZGmq4YCb-rKPPUgvFTArNHjgyjLuJXKff5XEU'

NAVY = (0.086, 0.129, 0.243)
CARD_NAVY = (0.114, 0.157, 0.267)   # slightly lighter navy for card panels
GOLD = (0.788, 0.663, 0.380)
GOLD_SOFT = (0.859, 0.780, 0.596)

W, H = 9144000, 5143500  # slide size in EMU

tool = GoogleSlidesTool(credentials_path='credentials.json')

title_closing = [
    {'slide_id': 'p', 'idx': 1, 'total': 6},
    {'slide_id': 'g3f6752b87ae_0_25', 'idx': 6, 'total': 6},
]
content = [
    {'slide_id': 'g3f6752b87ae_0_0', 'body_id': 'g3f6752b87ae_0_2', 'idx': 2, 'total': 6},
    {'slide_id': 'g3f6752b87ae_0_7', 'body_id': 'g3f6752b87ae_0_9', 'idx': 3, 'total': 6},
    {'slide_id': 'g3f6752b87ae_0_14', 'body_id': 'g3f6752b87ae_0_16', 'idx': 4, 'total': 6},
    {'slide_id': 'g3f6752b87ae_0_19', 'body_id': 'g3f6752b87ae_0_21', 'idx': 5, 'total': 6},
]
all_slides = title_closing + content


def add_border_frame(slide_id, tag):
    obj_id = f"frame_{tag}"
    req = {
        'createShape': {
            'objectId': obj_id, 'shapeType': 'RECTANGLE',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': W - 120000, 'unit': 'EMU'}, 'height': {'magnitude': H - 120000, 'unit': 'EMU'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': 60000, 'translateY': 60000, 'unit': 'EMU'}
            }
        }
    }
    tool.batch_update(PID, [req])
    tool.batch_update(PID, [{
        'updateShapeProperties': {
            'objectId': obj_id,
            'fields': 'shapeBackgroundFill.propertyState,outline.propertyState,outline.weight,outline.outlineFill.solidFill.color',
            'shapeProperties': {
                'shapeBackgroundFill': {'propertyState': 'NOT_RENDERED'},
                'outline': {
                    'propertyState': 'RENDERED',
                    'weight': {'magnitude': 1.25, 'unit': 'PT'},
                    'outlineFill': {'solidFill': {'color': {'rgbColor': {'red': GOLD[0], 'green': GOLD[1], 'blue': GOLD[2]}}}}
                }
            }
        }
    }])


def add_corner_ring(slide_id, tag, cx, cy, r):
    obj_id = f"ring_{tag}"
    req = {
        'createShape': {
            'objectId': obj_id, 'shapeType': 'ELLIPSE',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': r * 2, 'unit': 'EMU'}, 'height': {'magnitude': r * 2, 'unit': 'EMU'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': cx - r, 'translateY': cy - r, 'unit': 'EMU'}
            }
        }
    }
    tool.batch_update(PID, [req])
    tool.batch_update(PID, [{
        'updateShapeProperties': {
            'objectId': obj_id,
            'fields': 'shapeBackgroundFill.propertyState,outline.propertyState,outline.weight,outline.outlineFill.solidFill.color',
            'shapeProperties': {
                'shapeBackgroundFill': {'propertyState': 'NOT_RENDERED'},
                'outline': {
                    'propertyState': 'RENDERED',
                    'weight': {'magnitude': 1, 'unit': 'PT'},
                    'outlineFill': {'solidFill': {'color': {'rgbColor': {'red': GOLD[0], 'green': GOLD[1], 'blue': GOLD[2]}}}}
                }
            }
        }
    }])
    tool.update_z_order(PID, obj_id, 'SEND_TO_BACK')


def add_card_panel(slide_id, tag, x, y, w, h):
    obj_id = f"card_{tag}"
    req = {
        'createShape': {
            'objectId': obj_id, 'shapeType': 'ROUND_RECTANGLE',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': w, 'unit': 'EMU'}, 'height': {'magnitude': h, 'unit': 'EMU'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': x, 'translateY': y, 'unit': 'EMU'}
            }
        }
    }
    tool.batch_update(PID, [req])
    tool.change_shape_color(PID, obj_id, *CARD_NAVY)
    tool.batch_update(PID, [{
        'updateShapeProperties': {
            'objectId': obj_id, 'fields': 'outline.propertyState',
            'shapeProperties': {'outline': {'propertyState': 'NOT_RENDERED'}}
        }
    }])
    tool.update_z_order(PID, obj_id, 'SEND_TO_BACK')
    return obj_id


def add_page_number(slide_id, tag, idx, total):
    obj_id = f"pagenum_{tag}"
    req = {
        'createShape': {
            'objectId': obj_id, 'shapeType': 'TEXT_BOX',
            'elementProperties': {
                'pageObjectId': slide_id,
                'size': {'width': {'magnitude': 700000, 'unit': 'EMU'}, 'height': {'magnitude': 200000, 'unit': 'EMU'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': W - 850000, 'translateY': H - 320000, 'unit': 'EMU'}
            }
        }
    }
    tool.batch_update(PID, [req])
    tool.batch_update(PID, [{'insertText': {'objectId': obj_id, 'text': f'{idx:02d} / {total:02d}'}}])
    tool.update_text_style(PID, obj_id, font_size=10, color_rgb=GOLD_SOFT, font_family='Noto Sans JP')


print("1. Adding gold border frame to all slides...")
for s in all_slides:
    add_border_frame(s['slide_id'], s['slide_id'][-8:])

print("2. Adding decorative corner rings to title/closing slides...")
add_corner_ring('p', 'p_tr', W - 200000, -400000, 900000)
add_corner_ring('p', 'p_bl', -300000, H + 200000, 700000)
add_corner_ring('g3f6752b87ae_0_25', 'c_tr', W - 200000, -400000, 900000)
add_corner_ring('g3f6752b87ae_0_25', 'c_bl', -300000, H + 200000, 700000)

print("3. Adding card panels behind body text on content slides...")
for s in content:
    add_card_panel(s['slide_id'], s['slide_id'][-8:], x=250000, y=1080000, w=8644000, h=3620000)

print("4. Adding page numbers...")
for s in content:
    add_page_number(s['slide_id'], s['slide_id'][-8:], s['idx'], s['total'])
add_page_number('g3f6752b87ae_0_25', 'closing', 6, 6)

print("Done.")
