"""
Vercel サーバーレス関数用エントリーポイント
"""
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app

# Vercel用のハンドラ
def handler(request, context):
    return app(request, context)
