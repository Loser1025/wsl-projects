#!/usr/bin/env python3
"""
OpenAI SDKを使用してGitHub Modelsにリクエストを送るスクリプト
"""
import os
from openai import OpenAI

# 発行したトークンをセット
client = OpenAI(
    base_url="https://models.inference.ai.azure.com",  # GitHub Modelsのエンドポイント
    api_key=os.environ.get("GITHUB_TOKEN")  # 環境変数からトークンを取得
)

# モデル一覧を取得
try:
    response = client.models.list()
    print("利用可能なモデル一覧:")
    if hasattr(response, 'data'):
        for model in response.data:
            print(f"- {model.id}")
    else:
        print(response)
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"エラーが発生しました: {e}")
