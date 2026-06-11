#!/usr/bin/env python3
"""
API Model List - ディレクトリを探索し、検出されたAPIのモデル一覧を取得・表示する。
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box


# ──────────────────────────────────────────────
# API定義（名前、エンドポイント、認証ヘッダー、環境変数名）
# ──────────────────────────────────────────────
API_CONFIGS = {
    "OpenAI": {
        "models_endpoint": "/v1/models",
        "base_url": "https://api.openai.com",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer",
        "env_key": "OPENAI_API_KEY",
        "model_id_field": "id",
        "context_length_field": "context_length",
        "rate_limit_headers": {
            "requests": "x-ratelimit-limit-requests",
            "tokens": "x-ratelimit-limit-tokens",
        },
    },
    "OpenRouter": {
        "models_endpoint": "/v1/models",
        "base_url": "https://openrouter.ai/api",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer",
        "env_key": "OPENROUTER_API_KEY",
        "model_id_field": "id",
        "context_length_field": "context_length",
        "rate_limit_headers": {
            "requests": "x-ratelimit-limit-requests",
            "tokens": "x-ratelimit-limit-tokens",
        },
    },
    "Mistral": {
        "models_endpoint": "/v1/models",
        "base_url": "https://api.mistral.ai",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer",
        "env_key": "MISTRAL_API_KEY",
        "model_id_field": "id",
        "context_length_field": "max_tokens",
        "rate_limit_headers": {
            "requests": "x-ratelimit-limit-requests",
            "tokens": "x-ratelimit-limit-tokens",
        },
    },
    "Anthropic": {
        "models_endpoint": "/v1/messages",
        "base_url": "https://api.anthropic.com",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "env_key": "ANTHROPIC_API_KEY",
        "model_id_field": "id",
        "context_length_field": "max_tokens",
        "rate_limit_headers": {
            "requests": "x-ratelimit-limit-requests",
            "tokens": "x-ratelimit-limit-tokens",
        },
    },
    "Gemini": {
        "models_endpoint": "/v1/models",
        "base_url": "https://generativelanguage.googleapis.com",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer",
        "env_key": "GOOGLE_API_KEY",
        "model_id_field": "name",
        "context_length_field": "inputTokenLimit",
        "rate_limit_headers": {
            "requests": "x-ratelimit-limit-requests",
            "tokens": "x-ratelimit-limit-tokens",
        },
    },
    "HuggingFace": {
        "models_endpoint": "/models",
        "base_url": "https://api-inference.huggingface.co",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer",
        "env_key": "HUGGINGFACE_API_KEY",
        "model_id_field": "id",
        "context_length_field": "max_tokens",
        "rate_limit_headers": {
            "requests": "x-ratelimit-limit-requests",
            "tokens": "x-ratelimit-limit-tokens",
        },
    },
}

# ファイル拡張子のホワイトリスト
TEXT_EXTENSIONS = {
    ".py", ".json", ".env", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".md"
}

# 除外ディレクトリ
EXCLUDE_DIRS = {
    ".venv", "node_modules", "__pycache__", ".git", "site-packages", "lib", "bin", "include"
}

# APIキーワード（api_scanner.py から流用）
API_KEYWORDS = {
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
    "api.openai.com": {
        "name": "OpenAI",
        "endpoint_patterns": [r"https://api\.openai\.com", r"api\.openai\.com"],
        "key_patterns": [r"OPENAI_API_KEY"],
    },
}


# ──────────────────────────────────────────────
# api_scanner.py からの機能流用
# ──────────────────────────────────────────────
def extract_api_info(file_path: Path) -> List[Dict[str, Any]]:
    """ファイルからAPI情報を抽出する（api_scanner.py から流用）。"""
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except (UnicodeDecodeError, PermissionError, OSError):
        return []

    found_apis = []

    for api_keyword, api_config in API_KEYWORDS.items():
        if not re.search(re.escape(api_keyword), content, re.IGNORECASE):
            continue

        endpoint = None
        for endpoint_pattern in api_config["endpoint_patterns"]:
            match = re.search(endpoint_pattern, content, re.IGNORECASE)
            if match:
                endpoint = match.group(0)
                break

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


def scan_directory(root_dir: Path) -> List[Dict[str, Any]]:
    """ディレクトリを再帰的に検索し、API情報を抽出する（api_scanner.py から流用）。"""
    all_apis = []

    for file_path in root_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
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
            if api["endpoint"] and not merged[key]["endpoint"]:
                merged[key]["endpoint"] = api["endpoint"]
            if api["has_key"]:
                merged[key]["has_key"] = True

    return list(merged.values())


# ──────────────────────────────────────────────
# APIリクエスト機能
# ──────────────────────────────────────────────
def make_api_request(
    api_name: str,
    endpoint: str,
    api_key: str,
    method: str = "GET",
    params: Optional[Dict] = None,
) -> Optional[requests.Response]:
    """APIにリクエストを送信する。"""
    config = API_CONFIGS.get(api_name)
    if not config:
        return None

    base_url = config["base_url"]
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    headers = {}
    auth_header = config["auth_header"]
    auth_prefix = config["auth_prefix"]
    if auth_prefix:
        headers[auth_header] = f"{auth_prefix} {api_key}"
    else:
        headers[auth_header] = api_key

    try:
        response = requests.request(method, url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        console = Console()
        console.print(f"[red]Error making API request to {url}: {e}[/red]")
        return None


# ──────────────────────────────────────────────
# モデル一覧取得機能
# ──────────────────────────────────────────────
def fetch_models(api_name: str, api_key: str) -> List[Dict[str, Any]]:
    """各APIのモデル一覧を取得する。"""
    config = API_CONFIGS.get(api_name)
    if not config:
        return []

    response = make_api_request(api_name, config["models_endpoint"], api_key)
    if not response:
        return []

    try:
        data = response.json()
        models = data.get("data", []) if isinstance(data, dict) else data
        if not isinstance(models, list):
            return []

        # レートリミット情報を取得
        rate_limit_requests = response.headers.get(config["rate_limit_headers"]["requests"])
        rate_limit_tokens = response.headers.get(config["rate_limit_headers"]["tokens"])

        result = []
        for model in models:
            model_id = model.get(config["model_id_field"], "")
            if not model_id:
                continue

            # モデル詳細を取得（必要に応じて）
            context_length = model.get(config["context_length_field"])
            if context_length is None:
                # モデル詳細エンドポイントを呼び出す
                detail_response = make_api_request(api_name, f"/models/{model_id}", api_key)
                if detail_response:
                    detail_data = detail_response.json()
                    context_length = detail_data.get(config["context_length_field"])

            result.append({
                "id": model_id,
                "name": model.get("name", model_id),
                "context_length": context_length,
                "rate_limit_requests": rate_limit_requests,
                "rate_limit_tokens": rate_limit_tokens,
                "api_name": api_name,
                "raw_data": model,
            })

        return result
    except (json.JSONDecodeError, KeyError) as e:
        console = Console()
        console.print(f"[red]Error parsing response from {api_name}: {e}[/red]")
        return []


def fetch_api_details(api_name: str, api_key: str) -> Dict[str, Any]:
    """APIキーを使用してリクエストを送り、リミットやエイリアスなどの情報を取得する。"""
    config = API_CONFIGS.get(api_name)
    if not config:
        return {}

    console = Console()

    # モデル一覧を取得
    models = fetch_models(api_name, api_key)
    if not models:
        return {}

    # レスポンスヘッダーからレートリミット情報を取得（fetch_models で取得済み）
    rate_limit_requests = models[0].get("rate_limit_requests", "N/A")
    rate_limit_tokens = models[0].get("rate_limit_tokens", "N/A")

    # 各モデルの詳細からレートリミット情報を取得（個別モデルエンドポイント）
    model_detail_requests = "N/A"
    model_detail_tokens = "N/A"
    for model in models[:1]:  # 最初のモデルだけ詳細取得
        model_id = model.get("id", "")
        if not model_id:
            continue
        endpoint = f"{config['models_endpoint'].rstrip('/')}/{model_id}"
        detail_response = make_api_request(api_name, endpoint.lstrip("/"), api_key)
        if detail_response:
            headers = detail_response.headers
            rl_header_requests = config["rate_limit_headers"]["requests"]
            rl_header_tokens = config["rate_limit_headers"]["tokens"]
            model_detail_requests = headers.get(rl_header_requests, rate_limit_requests)
            model_detail_tokens = headers.get(rl_header_tokens, rate_limit_tokens)
            break

    # エイリアス情報を取得
    aliases = []
    for model in models:
        model_aliases = extract_aliases(model)
        if model_aliases and model_aliases != "-":
            aliases.extend(
                alias.strip()
                for alias in model_aliases.split(",")
                if alias.strip() and alias.strip() not in aliases
            )

    return {
        "api_name": api_name,
        "rate_limit_requests": model_detail_requests if model_detail_requests != "N/A" else rate_limit_requests,
        "rate_limit_tokens": model_detail_tokens if model_detail_tokens != "N/A" else rate_limit_tokens,
        "aliases": ", ".join(aliases) if aliases else "-",
        "models_count": len(models),
    }


# ──────────────────────────────────────────────
# データ整理機能
# ──────────────────────────────────────────────
def organize_models(all_models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """重複するモデルをユニークに整理する。"""
    unique_models = {}
    for model in all_models:
        model_id = model["id"]
        if model_id not in unique_models:
            unique_models[model_id] = model.copy()
        else:
            # 既存のモデルとマージ（レートリミット情報を更新）
            existing = unique_models[model_id]
            if model.get("context_length") and not existing.get("context_length"):
                existing["context_length"] = model["context_length"]
            if model.get("rate_limit_requests") and not existing.get("rate_limit_requests"):
                existing["rate_limit_requests"] = model["rate_limit_requests"]
            if model.get("rate_limit_tokens") and not existing.get("rate_limit_tokens"):
                existing["rate_limit_tokens"] = model["rate_limit_tokens"]
            # API名を追加（カンマ区切り）
            if model["api_name"] not in existing.get("api_names", []):
                existing.setdefault("api_names", []).append(model["api_name"])

    # 表示用に整形
    result = []
    for model_id, model in unique_models.items():
        api_names = model.get("api_names", [model["api_name"]])
        result.append({
            "id": model_id,
            "name": model["name"],
            "api_names": ", ".join(api_names),
            "context_length": model.get("context_length", "N/A"),
            "rate_limit_requests": model.get("rate_limit_requests", "N/A"),
            "rate_limit_tokens": model.get("rate_limit_tokens", "N/A"),
            "aliases": extract_aliases(model),
        })

    return result


def extract_aliases(model: Dict[str, Any]) -> str:
    """モデルのエイリアスを抽出する。"""
    aliases = []
    raw_data = model.get("raw_data", {})
    if isinstance(raw_data, dict):
        if "id" in raw_data and raw_data["id"] != model["id"]:
            aliases.append(raw_data["id"])
        if "name" in raw_data and raw_data["name"] != model["name"]:
            aliases.append(raw_data["name"])
    return ", ".join(aliases) if aliases else "-"


# ──────────────────────────────────────────────
# TUI表示機能
# ──────────────────────────────────────────────
def display_models(models: List[Dict[str, Any]]) -> None:
    """モデル一覧をTUIで表示する。"""
    console = Console()

    if not models:
        console.print("[yellow]No models found.[/yellow]")
        return

    # 表の作成
    table = Table(
        title="API Model List",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        show_lines=True,
    )

    # 列の追加
    table.add_column("API Name(s)", style="magenta", width=20)
    table.add_column("Model Name", style="green", width=25)
    table.add_column("Max Tokens", justify="right", width=10)
    table.add_column("RPM", justify="right", width=10)
    table.add_column("TPM", justify="right", width=10)
    table.add_column("Aliases", style="dim", width=20)

    # データの追加
    for model in models:
        api_names = model.get("api_names", model.get("api_name", "N/A"))
        model_name = model.get("name", model.get("id", "N/A"))
        max_tokens = str(model.get("context_length", "N/A"))
        rpm = str(model.get("rate_limit_requests", "N/A"))
        tpm = str(model.get("rate_limit_tokens", "N/A"))
        aliases = model.get("aliases", "-")

        table.add_row(api_names, model_name, max_tokens, rpm, tpm, aliases)

    # 表の表示
    console.print(Panel(table, title="[bold]Detected API Models[/bold]", border_style="blue"))


# ──────────────────────────────────────────────
# APIキー検索機能
# ──────────────────────────────────────────────
def search_api_keys(root_dir: Path) -> List[Dict[str, Any]]:
    """ディレクトリ内のファイルからAPIキーのパターンを検索する。"""
    api_keys = []

    for file_path in root_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if any(part in EXCLUDE_DIRS for part in file_path.parts):
            continue

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except (UnicodeDecodeError, PermissionError, OSError):
            continue

        for api_name, api_config in API_CONFIGS.items():
            env_key = api_config.get("env_key")
            if not env_key:
                continue

            # APIキーのパターンを検索（ENV_KEY = 'value' or ENV_KEY = "value"）
            key_pattern = re.compile(
                rf"{re.escape(env_key)}\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE
            )
            match = key_pattern.search(content)
            if match:
                api_keys.append({
                    "api_name": api_name,
                    "env_key": env_key,
                    "key": match.group(1),
                    "file_path": str(file_path.resolve()),
                })

    return api_keys


def set_api_keys_from_files(root_dir: Path) -> None:
    """ディレクトリから検出されたAPIキーを環境変数に設定する。"""
    detected_api_keys = search_api_keys(root_dir)

    if not detected_api_keys:
        console = Console()
        console.print("[yellow]No API keys detected in the directory.[/yellow]")
        return

    for key_info in detected_api_keys:
        env_key = key_info["env_key"]
        api_key = key_info["key"]
        os.environ[env_key] = api_key
        console = Console()
        console.print(f"[green]Set {env_key} from file: {key_info['file_path']}[/green]")


def display_api_keys(api_keys: List[Dict[str, Any]]) -> None:
    """検出されたAPIキーを表形式で表示する。"""
    console = Console()

    if not api_keys:
        console.print("[yellow]No API keys found.[/yellow]")
        return

    table = Table(
        title="Detected API Keys",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        show_lines=True,
    )

    table.add_column("API Name", style="magenta", width=20)
    table.add_column("Env Key", style="yellow", width=25)
    table.add_column("API Key", style="green", width=40)
    table.add_column("File Path", style="dim", width=50)

    for key in api_keys:
        masked_key = key["key"][:8] + "..." if len(key["key"]) > 8 else key["key"]
        table.add_row(
            key["api_name"],
            key["env_key"],
            masked_key,
            key["file_path"],
        )

    console.print(Panel(table, title="[bold]Detected API Keys[/bold]", border_style="blue"))


def display_api_details(api_details: Dict[str, Any]) -> None:
    """取得したAPIの詳細情報を表示する。"""
    console = Console()

    table = Table(
        title="API Details",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        show_lines=True,
    )

    table.add_column("API Name", style="magenta", width=20)
    table.add_column("Models Count", style="green", width=15)
    table.add_column("Rate Limit (Requests)", justify="right", width=25)
    table.add_column("Rate Limit (Tokens)", justify="right", width=25)
    table.add_column("Aliases", style="dim", width=30)

    table.add_row(
        api_details.get("api_name", "N/A"),
        str(api_details.get("models_count", "N/A")),
        str(api_details.get("rate_limit_requests", "N/A")),
        str(api_details.get("rate_limit_tokens", "N/A")),
        api_details.get("aliases", "-"),
    )

    console.print(Panel(table, title="[bold]API Details[/bold]", border_style="blue"))


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────
def main() -> None:
    """メイン処理。"""
    console = Console()

    # 0. ディレクトリをスキャンしてAPIキーを検出し、環境変数に設定
    console.print("[bold blue]Scanning directory for API keys...[/bold blue]")
    root_dir = Path("/home/loser/wsl-projects")
    set_api_keys_from_files(root_dir)

    detected_api_keys = search_api_keys(root_dir)
    if detected_api_keys:
        display_api_keys(detected_api_keys)

    # 1. ディレクトリをスキャンしてAPIを検出
    console.print("[bold blue]Scanning directory for APIs...[/bold blue]")
    detected_apis = scan_directory(root_dir)

    if not detected_apis:
        console.print("[yellow]No APIs detected in the directory.[/yellow]")
        return

    console.print(f"[green]Detected {len(detected_apis)} API(s):[/green]")
    for api in detected_apis:
        console.print(
            f"  - {api['name']} (Endpoint: {api.get('endpoint', 'N/A')}, "
            f"Has Key: {api.get('has_key', False)})"
        )

    # 2. 各APIの詳細情報を取得・表示
    console.print("[bold blue]Fetching API details...[/bold blue]")
    for api in detected_apis:
        api_name = api["name"]
        env_key = API_CONFIGS.get(api_name, {}).get("env_key")
        if not env_key:
            console.print(f"[yellow]Skipping {api_name}: No environment variable configuration.[/yellow]")
            continue

        api_key = os.getenv(env_key)
        if not api_key:
            console.print(f"[yellow]Skipping {api_name}: {env_key} environment variable is not set.[/yellow]")
            continue

        console.print(f"[blue]Fetching details for {api_name}...[/blue]")
        api_details = fetch_api_details(api_name, api_key)
        if api_details:
            display_api_details(api_details)
        else:
            console.print(f"[red]Failed to fetch details for {api_name}.[/red]")

    # 3. 各APIのモデル一覧を取得
    all_models = []
    for api in detected_apis:
        api_name = api["name"]
        env_key = API_CONFIGS.get(api_name, {}).get("env_key")
        if not env_key:
            console.print(f"[yellow]Skipping {api_name}: No environment variable configuration.[/yellow]")
            continue

        api_key = os.getenv(env_key)
        if not api_key:
            console.print(f"[yellow]Skipping {api_name}: {env_key} environment variable is not set.[/yellow]")
            continue

        console.print(f"[blue]Fetching models for {api_name}...[/blue]")
        models = fetch_models(api_name, api_key)
        if models:
            console.print(f"[green]Found {len(models)} model(s) for {api_name}.[/green]")
            all_models.extend(models)
        else:
            console.print(f"[red]Failed to fetch models for {api_name}.[/red]")

    # 4. データを整理
    organized_models = organize_models(all_models)

    # 5. TUIで表示
    display_models(organized_models)


if __name__ == "__main__":
    main()
