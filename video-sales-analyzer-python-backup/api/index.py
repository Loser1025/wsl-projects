"""
Vercel サーバーレス関数用エントリーポイント
"""
import sys
import os

# プロジェクトルートをパスに追加
project_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, project_root)

# テンプレートと静的ファイルのパスを設定
os.environ["FLASK_TEMPLATE_FOLDER"] = os.path.join(project_root, "templates")
os.environ["FLASK_STATIC_FOLDER"] = os.path.join(project_root, "static")

from app import app

# Vercel用のハンドラ
def handler(request, context):
    return app(request, context)
