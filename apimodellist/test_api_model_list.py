#!/usr/bin/env python3
"""
テストスクリプト: api_model_list.py の動作確認
プロジェクト内のファイルからスキャンしたAPIキーを使用して、
各サービスのRPM/TPMリミット情報を取得する。

環境変数は使用せず、search_api_keys の結果を使用する。

実行方法:
  python3 test_api_model_list.py
"""

import os
import sys

# プロジェクトディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_model_list import (
    fetch_key_info_openrouter,
    fetch_key_info_mistral,
    fetch_key_info_gemini,
    search_api_keys,
    _mask_key,
)
from pathlib import Path


def test_service(name: str, fetch_func):
    """指定サービスのキー情報を取得して表示する。

    Args:
        name: サービス名（例: "OpenRouter"）
        fetch_func: キー情報取得関数
    """
    print(f"=== {name} ===")

    # スキャン結果からキーを確認
    root_dir = Path("/home/loser/wsl-projects")
    scanned_keys = search_api_keys(root_dir)
    matching_keys = [k for k in scanned_keys if k["api_name"] == name]

    print(f"  [DEBUG] スキャン結果: {len(scanned_keys)} キー検出, {name} に一致: {len(matching_keys)} 件")
    if matching_keys:
        for k in matching_keys:
            print(f"  [DEBUG]   env_key={k['env_key']}, key={_mask_key(k['key'])}, file={k['file_path']}")

    try:
        result = fetch_func(name)
        print(f"  [DEBUG] レスポンス: {result}")
        if result.get("status") == "success":
            if result.get("rpm") is not None:
                print(f"  RPM Limit: {result.get('rpm', 'N/A')}")
                print(f"  RPM Remaining: {result.get('rpm_remaining', 'N/A')}")
            if result.get("tpm") is not None:
                print(f"  TPM Limit: {result.get('tpm', 'N/A')}")
                print(f"  TPM Remaining: {result.get('tpm_remaining', 'N/A')}")
            if result.get("reset"):
                print(f"  Reset: {result['reset']}")
            print(f"  ✓ {name} の情報取得に成功しました")
        else:
            msg = result.get("message", "Unknown error")
            print(f"  ✗ ERROR: {msg}")
    except Exception as e:
        print(f"  ✗ EXCEPTION: {type(e).__name__}: {e}")
    print()


def main():
    print("Testing API rate-limit key info functions...")
    print("Using scanned API keys from project files.\n")
    test_service("OpenRouter", fetch_key_info_openrouter)
    test_service("Mistral", fetch_key_info_mistral)
    test_service("Gemini", fetch_key_info_gemini)
    print("Done.")


if __name__ == "__main__":
    main()
