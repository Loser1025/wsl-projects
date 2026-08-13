# -*- coding: utf-8 -*-
from slides_design_tool import GoogleSlidesTool

PID = '1A9AUnUZGmq4YCb-rKPPUgvFTArNHjgyjLuJXKff5XEU'
tool = GoogleSlidesTool(credentials_path='credentials.json')

reqs = [
    {'deleteText': {'objectId': 'i0', 'textRange': {'type': 'ALL'}}},
    {'insertText': {'objectId': 'i0', 'text': 'UNLOCK'}},
    {'updateTextStyle': {
        'objectId': 'i0',
        'style': {
            'fontSize': {'magnitude': 80, 'unit': 'PT'}, 'bold': True,
            'foregroundColor': {'opaqueColor': {'rgbColor': {'red': 0.753, 'green': 0.541, 'blue': 0.275}}},
            'fontFamily': 'Archivo Black',
            'weightedFontFamily': {'fontFamily': 'Archivo Black', 'weight': 700},
        },
        'fields': 'fontSize,bold,foregroundColor,fontFamily,weightedFontFamily'
    }},

    {'deleteText': {'objectId': 'i1', 'textRange': {'type': 'ALL'}}},
    {'insertText': {'objectId': 'i1', 'text': 'グループコーチング　ご説明資料'}},
    {'updateTextStyle': {
        'objectId': 'i1',
        'style': {
            'fontSize': {'magnitude': 17, 'unit': 'PT'}, 'bold': False,
            'foregroundColor': {'opaqueColor': {'rgbColor': {'red': 0.925, 'green': 0.902, 'blue': 0.847}}},
            'fontFamily': 'Noto Serif JP',
            'weightedFontFamily': {'fontFamily': 'Noto Serif JP', 'weight': 400},
        },
        'fields': 'fontSize,bold,foregroundColor,fontFamily,weightedFontFamily'
    }},
]
r = tool.batch_update(PID, reqs)
print('fixed cover text:', r is not None)
