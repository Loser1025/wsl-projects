# -*- coding: utf-8 -*-
from slides_design_tool import GoogleSlidesTool

PID = '1A9AUnUZGmq4YCb-rKPPUgvFTArNHjgyjLuJXKff5XEU'
tool = GoogleSlidesTool(credentials_path='credentials.json')

BASE = 3000000  # base createShape size in EMU


def transform(obj_id, x, y, w, h):
    return {
        'updatePageElementTransform': {
            'objectId': obj_id, 'applyMode': 'ABSOLUTE',
            'transform': {
                'scaleX': w / BASE, 'scaleY': h / BASE,
                'translateX': x, 'translateY': y, 'unit': 'EMU'
            }
        }
    }


reqs = [
    # cover wordmark + subtitle
    transform('i0', 450000, 1500000, 4600000, 1100000),
    transform('i1', 450000, 2750000, 3800000, 480000),

    # section titles (single line, full content width)
    transform('g3f6752b87ae_0_1', 450000, 700000, 8244000, 700000),   # 当プログラムの特徴
    transform('g3f6752b87ae_0_8', 450000, 700000, 8244000, 700000),   # セッションの4つの柱
    transform('g3f6752b87ae_0_15', 450000, 700000, 8244000, 700000),  # 料金システムとサポート体制
    transform('g3f6752b87ae_0_20', 450000, 700000, 8244000, 700000),  # 基本スケジュール
    transform('g3f6752b87ae_0_26', 450000, 1250000, 8244000, 1000000),  # closing headline (2 lines)
]

r = tool.batch_update(PID, reqs)
print('fix boxes:', r is not None)
