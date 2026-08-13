from slides_design_tool import GoogleSlidesTool

PID = '1A9AUnUZGmq4YCb-rKPPUgvFTArNHjgyjLuJXKff5XEU'

NAVY = (0.086, 0.129, 0.243)      # #16213E background
GOLD = (0.788, 0.663, 0.380)      # #C9A961 accent
WHITE = (0.937, 0.937, 0.937)     # #EFEFEF body text
GOLD_SOFT = (0.859, 0.780, 0.596) # lighter gold for subtitles
FONT = 'Noto Sans JP'

tool = GoogleSlidesTool(credentials_path='credentials.json')

# ---- Title slide (0) & closing slide (5): big title + subtitle layout ----
title_closing_slides = [
    {'slide_id': 'p', 'title_id': 'i0', 'sub_id': 'i1'},
    {'slide_id': 'g3f6752b87ae_0_25', 'title_id': 'g3f6752b87ae_0_26', 'sub_id': 'g3f6752b87ae_0_27'},
]

# ---- Content slides (1-4): header + body layout ----
content_slides = [
    {'slide_id': 'g3f6752b87ae_0_0', 'title_id': 'g3f6752b87ae_0_1', 'body_id': 'g3f6752b87ae_0_2'},
    {'slide_id': 'g3f6752b87ae_0_7', 'title_id': 'g3f6752b87ae_0_8', 'body_id': 'g3f6752b87ae_0_9'},
    {'slide_id': 'g3f6752b87ae_0_14', 'title_id': 'g3f6752b87ae_0_15', 'body_id': 'g3f6752b87ae_0_16'},
    {'slide_id': 'g3f6752b87ae_0_19', 'title_id': 'g3f6752b87ae_0_20', 'body_id': 'g3f6752b87ae_0_21'},
]

all_slide_ids = [s['slide_id'] for s in title_closing_slides] + [s['slide_id'] for s in content_slides]

print("1. Setting navy background on all slides...")
for sid in all_slide_ids:
    tool.set_slide_background(PID, sid, *NAVY)

print("2. Styling title/closing slides...")
for s in title_closing_slides:
    tool.update_text_style(PID, s['title_id'], font_size=40, bold=True, color_rgb=GOLD, font_family=FONT)
    tool.update_text_style(PID, s['sub_id'], font_size=16, bold=False, color_rgb=GOLD_SOFT, font_family=FONT)

print("3. Styling content slides (header + body)...")
for s in content_slides:
    tool.update_text_style(PID, s['title_id'], font_size=24, bold=True, color_rgb=GOLD, font_family=FONT)
    tool.update_text_style(PID, s['body_id'], font_size=14, bold=False, color_rgb=WHITE, font_family=FONT)

print("4. Adding gold accent bars under content slide headers...")
for s in content_slides:
    obj_id = f"accent_{s['slide_id'][-6:]}"
    request = {
        'createShape': {
            'objectId': obj_id, 'shapeType': 'RECTANGLE',
            'elementProperties': {
                'pageObjectId': s['slide_id'],
                'size': {'width': {'magnitude': 700000, 'unit': 'EMU'}, 'height': {'magnitude': 38100, 'unit': 'EMU'}},
                'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': 311700, 'translateY': 1057725, 'unit': 'EMU'}
            }
        }
    }
    tool.batch_update(PID, [request])
    tool.change_shape_color(PID, obj_id, *GOLD)
    tool.batch_update(PID, [{
        'updateShapeProperties': {
            'objectId': obj_id, 'fields': 'outline.propertyState',
            'shapeProperties': {'outline': {'propertyState': 'NOT_RENDERED'}}
        }
    }])

print("Done.")
