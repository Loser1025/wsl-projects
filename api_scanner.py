#!/usr/bin/env python3
"""
API Scanner - ディレクトリを再帰的に検索し、AIモデルのAPIっぽいファイルを特定する。
"""

import re
import json
from pathlib import Path

# 検索キーワードとAPI名のマッピング
# キーは検索キーワード（ファイル内容との一致に使用）
# 値は API 名・エンドポイントパターン・APIキーパターン
API_KEYWORDS = {
    # --- OpenRouter ---
    "openrouter": {
        "name": "OpenRouter",
        "endpoint_patterns": [r"https://openrouter\.ai/api", r"openrouter\.ai/api"],
        "key_patterns": [r"OPENROUTER_API_KEY"],
    },
    "OPENROUTER_API_KEY": {
        "name": "OpenRouter",
        "endpoint_patterns": [r"https://openrouter\.ai/api", r"openrouter\.ai/api"],
        "key_patterns": [r"OPENROUTER_API_KEY"],
    },
    "openrouter.ai/api": {
        "name": "OpenRouter",
        "endpoint_patterns": [r"https://openrouter\.ai/api", r"openrouter\.ai/api"],
        "key_patterns": [r"OPENROUTER_API_KEY"],
    },
    # --- Mistral ---
    "mistral": {
        "name": "Mistral",
        "endpoint_patterns": [r"https://api\.mistral\.ai", r"api\.mistral\.ai"],
        "key_patterns": [r"MISTRAL_API_KEY"],
    },
    "MISTRAL_API_KEY": {
        "name": "Mistral",
        "endpoint_patterns": [r"https://api\.mistral\.ai", r"api\.mistral\.ai"],
        "key_patterns": [r"MISTRAL_API_KEY"],
    },
    "api.mistral.ai": {
        "name": "Mistral",
        "endpoint_patterns": [r"https://api\.mistral\.ai", r"api\.mistral\.ai"],
        "key_patterns": [r"MISTRAL_API_KEY"],
    },
    # --- Anthropic ---
    "anthropic": {
        "name": "Anthropic",
        "endpoint_patterns": [r"https://api\.anthropic\.com", r"api\.anthropic\.com"],
        "key_patterns": [r"ANTHROPIC_API_KEY"],
    },
    "ANTHROPIC_API_KEY": {
        "name": "Anthropic",
        "endpoint_patterns": [r"https://api\.anthropic\.com", r"api\.anthropic\.com"],
        "key_patterns": [r"ANTHROPIC_API_KEY"],
    },
    # --- Gemini ---
    "gemini": {
        "name": "Gemini",
        "endpoint_patterns": [r"https://generativelanguage\.googleapis\.com", r"generativelanguage\.googleapis\.com"],
        "key_patterns": [r"GOOGLE_API_KEY"],
    },
    "GOOGLE_API_KEY": {
        "name": "Gemini",
        "endpoint_patterns": [r"https://generativelanguage\.googleapis\.com", r"generativelanguage\.googleapis\.com"],
        "key_patterns": [r"GOOGLE_API_KEY"],
    },
    "generativelanguage.googleapis.com": {
        "name": "Gemini",
        "endpoint_patterns": [r"https://generativelanguage\.googleapis\.com", r"generativelanguage\.googleapis\.com"],
        "key_patterns": [r"GOOGLE_API_KEY"],
    },
    # --- HuggingFace ---
    "huggingface": {
        "name": "HuggingFace",
        "endpoint_patterns": [r"https://api-inference\.huggingface\.co", r"api-inference\.huggingface\.co"],
        "key_patterns": [r"HUGGINGFACE_API_KEY"],
    },
    "HUGGINGFACE_API_KEY": {
        "name": "HuggingFace",
        "endpoint_patterns": [r"https://api-inference\.huggingface\.co", r"api-inference\.huggingface\.co"],
        "key_patterns": [r"HUGGINGFACE_API_KEY"],
    },
    "api-inference.huggingface.co": {
        "name": "HuggingFace",
        "endpoint_patterns": [r"https://api-inference\.huggingface\.co", r"api-inference\.huggingface\.co"],
        "key_patterns": [r"HUGGINGFACE_API_KEY"],
    },
    # --- OpenAI ---
    "api.openai.com": {
        "name": "OpenAI",
        "endpoint_patterns": [r"https://api\.openai\.com", r"api\.openai\.com"],
        "key_patterns": [r"OPENAI_API_KEY"],
    },
}

# ファイル拡張子のホワイトリスト
TEXT_EXTENSIONS = {
    ".py", ".json", ".env", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".md"
}

# 除外ディレクトリ（検索スキップ）
EXCLUDE_DIRS = {
    ".venv", "node_modules", "__pycache__", ".git", "site-packages", "lib", "bin", "include"
}


def extract_api_info(file_path: Path) -> list:
    """ファイルからAPI情報を抽出する。"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except (UnicodeDecodeError, PermissionError, OSError):
        return []

    found_apis = []

    for api_keyword, api_config in API_KEYWORDS.items():
        # キーワード自体を検索（リテラルマッチ）
        if not re.search(re.escape(api_keyword), content, re.IGNORECASE):
            continue

        # エンドポイントを検索
        endpoint = None
        for endpoint_pattern in api_config["endpoint_patterns"]:
            match = re.search(endpoint_pattern, content, re.IGNORECASE)
            if match:
                endpoint = match.group(0)
                break

        # APIキーを検索
        has_key = False
        for key_pattern in api_config["key_patterns"]:
            if re.search(key_pattern, content, re.IGNORECASE):
                has_key = True
                break

        found_apis.append({
            "name": api_config["name"],
            "endpoint": endpoint,
            "has_key": has_key,
            "file_path": str(file_path.resolve()),
        })

    return found_apis


def scan_directory(root_dir: Path) -> list:
    """ディレクトリを再帰的に検索し、API情報を抽出する。"""
    all_apis = []

    for file_path in root_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        # 除外ディレクトリチェック
        if any(part in EXCLUDE_DIRS for part in file_path.parts):
            continue
        apis = extract_api_info(file_path)
        all_apis.extend(apis)

    # 重複を除去（同じAPI名 + ファイルパスの組み合わせをマージ）
    merged = {}
    for api in all_apis:
        key = (api["name"], api["file_path"])
        if key not in merged:
            merged[key] = api.copy()
        else:
            # エンドポイントが見つかっていれば優先
            if api["endpoint"] and not merged[key]["endpoint"]:
                merged[key]["endpoint"] = api["endpoint"]
            # キーが見つかっていれば優先
            if api["has_key"]:
                merged[key]["has_key"] = True

    return list(merged.values())


def test_scanner():
    """探索機能をテストする。"""
    root_dir = Path("/home/loser/wsl-projects")
    apis = scan_directory(root_dir)

    if not apis:
        print("API情報は見つかりませんでした。")
    else:
        print("見つかったAPI情報:")
        for api in apis:
            print(json.dumps(api, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    test_scanner()
