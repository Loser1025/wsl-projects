#!/usr/bin/env python3
"""
テストスクリプト: api_model_list.py の動作確認
各サービスのAPIキー情報を環境変数から取得し、APIを呼び出してRPM/TPMリミット情報を取得する。

実行方法:
  export OPENROUTER_API_KEY="sk-or-..."
  export MISTRAL_API_KEY="..."
  export GOOGLE_API_KEY="AIza..."
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
)


def test_service(name: str, env_var: str, fetch_func):
    """指定サービスのキー情報を取得して表示する。"""
    print(f"=== {name} ===")
    api_key = os.getenv(env_var)
    if not api_key:
        print(f"SKIP: 環境変数 {env_var} が設定されていません。\n")
        return

    try:
        result = fetch_func(api_key)
        if result.get("status") == "success":
            if "rpm" in result:
                print(f"  RPM Limit: {result.get('rpm', 'N/A')}")
                print(f"  RPM Remaining: {result.get('rpm_remaining', 'N/A')}")
            if "tpm" in result:
                print(f"  TPM Limit: {result.get('tpm', 'N/A')}")
                print(f"  TPM Remaining: {result.get('tpm_remaining', 'N/A')}")
            if result.get("reset"):
                print(f"  Reset: {result['reset']}")
        else:
            msg = result.get("message", "Unknown error")
            print(f"  ERROR: {msg}")
    except Exception as e:
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
    print()


def main():
    print("Testing API rate-limit key info functions...\n")
    test_service("OpenRouter", "OPENROUTER_API_KEY", fetch_key_info_openrouter)
    test_service("Mistral", "MISTRAL_API_KEY", fetch_key_info_mistral)
    test_service("Gemini", "GOOGLE_API_KEY", fetch_key_info_gemini)
    print("Done.")


if __name__ == "__main__":
    main()
