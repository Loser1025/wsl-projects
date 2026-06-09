"""
アプリケーション設定
APIキーは環境変数で設定するか、このファイルに直接記述してください。
"""

import os
from typing import List

# ============================================================
# Gemini APIキー設定（複数アカウント対応）
# 以下のいずれかの方法で設定可能:
# 1. GEMINI_API_KEYS でカンマ区切り: export GEMINI_API_KEYS="key1,key2,key3"
# 2. GEMINI_KEY_1, GEMINI_KEY_2, GEMINI_KEY_3 で個別設定
# ============================================================

# 方法1: カンマ区切りで取得
_api_keys_env = os.environ.get("GEMINI_API_KEYS", "")

if _api_keys_env:
    API_KEYS: List[str] = [
        key.strip() for key in _api_keys_env.split(",") if key.strip()
    ]
else:
    # 方法2: 個別の環境変数から取得
    API_KEYS = []
    for i in range(1, 10):  # 最大9個まで対応
        key = os.environ.get(f"GEMINI_KEY_{i}", "")
        if key.strip():
            API_KEYS.append(key.strip())

# 現在のキーのインデックス（内部でフォールバック時に使用）
_current_key_index = 0

# ============================================================
# モデル設定
# ============================================================
MODEL_NAME = "gemma-3-27b-it"  # Gemma 4 31Bに更新予定
# 利用可能なモデル:
# - gemma-3-27b-it (Gemma 3 27B)
# - gemma-4-31b-it (Gemma 4 31B - 利用可能な場合)

# ============================================================
# 分析設定
# ============================================================
# 動画から抽出するフレーム数（多ほど精度は上がるが処理時間増）
FRAME_COUNT = 10

# フレーム画像の解像度
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# アップロード設定
MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB
ALLOWED_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm"}

# ============================================================
# サーバー設定
# ============================================================
HOST = "0.0.0.0"
PORT = 8080
DEBUG = True
