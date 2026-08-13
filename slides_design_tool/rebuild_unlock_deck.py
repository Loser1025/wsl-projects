# -*- coding: utf-8 -*-
"""Rebuild the Google Slides deck to match the 'UNLOCK night' HTML design."""
from slides_design_tool import GoogleSlidesTool

PID = '1A9AUnUZGmq4YCb-rKPPUgvFTArNHjgyjLuJXKff5XEU'
tool = GoogleSlidesTool(credentials_path='credentials.json')

W, H = 9144000, 5143500
MARGIN = 450000
CW = W - 2 * MARGIN  # content width

NIGHT = (0.071, 0.078, 0.110)
BRASS = (0.753, 0.541, 0.275)
BRASS_SOFT = (0.561, 0.439, 0.282)
EMBER = (0.886, 0.341, 0.173)
PARCH = (0.925, 0.902, 0.847)
PARCH_DIM = (0.812, 0.788, 0.737)
MUTED = (0.525, 0.545, 0.627)
HAIR = (0.925, 0.902, 0.847)  # used with low alpha for hairlines

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


def color_field(c, alpha=None):
    d = {'opaqueColor': {'rgbColor': rgb(c)}}
    return d


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


def style_text(obj_id, size=None, bold=None, color=None, font=None, alignment=None):
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
    reqs = [{'updateTextStyle': {'objectId': obj_id, 'style': style, 'fields': ','.join(fields)}}]
    if alignment:
        reqs.append({'updateParagraphStyle': {'objectId': obj_id, 'style': {'alignment': alignment}, 'fields': 'alignment'}})
    return reqs


def clear_text_bg(obj_id):
    return {'updateTextStyle': {'objectId': obj_id, 'style': {'backgroundColor': {}}, 'fields': 'backgroundColor'}}


def fill(obj_id, color, alpha=1.0):
    return {
        'updateShapeProperties': {
            'objectId': obj_id, 'fields': 'shapeBackgroundFill.solidFill.color,shapeBackgroundFill.solidFill.alpha',
            'shapeProperties': {'shapeBackgroundFill': {'solidFill': {'color': rgb_wrap(color), 'alpha': alpha}}}
        }
    }


def rgb_wrap(c):
    return {'rgbColor': rgb(c)}


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


def delete(obj_id):
    return {'deleteObject': {'objectId': obj_id}}


def zorder(obj_id, op):
    return {'updatePageElementsZOrder': {'pageElementObjectIds': [obj_id], 'operation': op}}


# =====================================================================
# PHASE 1 — delete everything we are going to replace / regenerate
# =====================================================================
delete_ids = [
    'ring_p_bl', 'ring_p_tr', 'frame_p',
    'card_87ae_0_0', 'accent_ae_0_0', 'frame_87ae_0_0', 'pagenum_87ae_0_0', 'g3f6752b87ae_0_2',
    'card_87ae_0_7', 'accent_ae_0_7', 'frame_87ae_0_7', 'pagenum_87ae_0_7', 'g3f6752b87ae_0_9',
    'card_7ae_0_14', 'accent_e_0_14', 'frame_7ae_0_14', 'pagenum_7ae_0_14', 'g3f6752b87ae_0_16',
    'card_7ae_0_19', 'accent_e_0_19', 'frame_7ae_0_19', 'pagenum_7ae_0_19', 'g3f6752b87ae_0_21',
    'ring_c_bl', 'ring_c_tr', 'frame_7ae_0_25', 'pagenum_closing', 'g3f6752b87ae_0_27',
]
phase1 = [delete(i) for i in delete_ids]
print('Phase 1: delete', len(phase1), 'objects')
r = tool.batch_update(PID, phase1)
print('  ->', r is not None)
