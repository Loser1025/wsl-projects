#!/usr/bin/env python3
"""
API Model List - ディレクトリを探索し、検出されたAPIのモデル一覧を取得・表示する。
"""

import os
import re
import json
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
from rich.console import Console
from rich.table import Table
from rich import box


# ──────────────────────────────────────────────
# API定義
# ──────────────────────────────────────────────
API_CONFIGS = {
    "OpenAI": {
        "models_endpoint": "/v1/models",
        "base_url": "https://api.openai.com",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer",
        "env_key": "OPENAI_API_KEY",
        "model_id_field": "id",
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
        "rate_limit_headers": {
            "requests": "x-ratelimit-limit-req-minute",
            "tokens": "x-ratelimit-limit-tokens-minute",
        },
    },
    "Anthropic": {
        "models_endpoint": "/v1/models",
        "base_url": "https://api.anthropic.com",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "env_key": "ANTHROPIC_API_KEY",
        "model_id_field": "id",
        "extra_headers": {"anthropic-version": "2023-06-01"},
        "rate_limit_headers": {
            "requests": "anthropic-ratelimit-requests-limit",
            "tokens": "anthropic-ratelimit-tokens-limit",
        },
    },
    "Gemini": {
        "models_endpoint": "/v1beta/models",
        "base_url": "https://generativelanguage.googleapis.com",
        "auth_header": "",
        "auth_prefix": "",
        "env_key": "GOOGLE_API_KEY",
        "model_id_field": "name",
        "rate_limit_headers": {},
    },
    "HuggingFace": {
        "models_endpoint": "/models",
        "base_url": "https://api-inference.huggingface.co",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer",
        "env_key": "HUGGINGFACE_API_KEY",
        "model_id_field": "id",
        "rate_limit_headers": {
            "requests": "x-ratelimit-limit-requests",
            "tokens": "x-ratelimit-limit-tokens",
        },
    },
}

TEXT_EXTENSIONS = {
    ".py", ".json", ".env", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".md",
    ".js", ".ts", ".jsx", ".tsx", ".cjs", ".mjs",
}

EXCLUDE_DIRS = {
    ".venv", "node_modules", "__pycache__", ".git", "site-packages", "lib", "bin", "include",
    ".mimic",
}

API_KEYWORDS = {
    "openrouter": {"name": "OpenRouter", "endpoint_patterns": [r"https://openrouter\.ai/api"], "key_patterns": [r"OPENROUTER_API_KEY"]},
    "OPENROUTER_API_KEY": {"name": "OpenRouter", "endpoint_patterns": [r"https://openrouter\.ai/api"], "key_patterns": [r"OPENROUTER_API_KEY"]},
    "openrouter.ai/api": {"name": "OpenRouter", "endpoint_patterns": [r"https://openrouter\.ai/api"], "key_patterns": [r"OPENROUTER_API_KEY"]},
    "mistral": {"name": "Mistral", "endpoint_patterns": [r"https://api\.mistral\.ai"], "key_patterns": [r"MISTRAL_API_KEY"]},
    "MISTRAL_API_KEY": {"name": "Mistral", "endpoint_patterns": [r"https://api\.mistral\.ai"], "key_patterns": [r"MISTRAL_API_KEY"]},
    "api.mistral.ai": {"name": "Mistral", "endpoint_patterns": [r"https://api\.mistral\.ai"], "key_patterns": [r"MISTRAL_API_KEY"]},
    "anthropic": {"name": "Anthropic", "endpoint_patterns": [r"https://api\.anthropic\.com"], "key_patterns": [r"ANTHROPIC_API_KEY"]},
    "ANTHROPIC_API_KEY": {"name": "Anthropic", "endpoint_patterns": [r"https://api\.anthropic\.com"], "key_patterns": [r"ANTHROPIC_API_KEY"]},
    "gemini": {"name": "Gemini", "endpoint_patterns": [r"https://generativelanguage\.googleapis\.com"], "key_patterns": [r"GOOGLE_API_KEY"]},
    "GOOGLE_API_KEY": {"name": "Gemini", "endpoint_patterns": [r"https://generativelanguage\.googleapis\.com"], "key_patterns": [r"GOOGLE_API_KEY"]},
    "generativelanguage.googleapis.com": {"name": "Gemini", "endpoint_patterns": [r"https://generativelanguage\.googleapis\.com"], "key_patterns": [r"GOOGLE_API_KEY"]},
    "huggingface": {"name": "HuggingFace", "endpoint_patterns": [r"https://api-inference\.huggingface\.co"], "key_patterns": [r"HUGGINGFACE_API_KEY"]},
    "HUGGINGFACE_API_KEY": {"name": "HuggingFace", "endpoint_patterns": [r"https://api-inference\.huggingface\.co"], "key_patterns": [r"HUGGINGFACE_API_KEY"]},
    "api.openai.com": {"name": "OpenAI", "endpoint_patterns": [r"https://api\.openai\.com"], "key_patterns": [r"OPENAI_API_KEY"]},
}


# ──────────────────────────────────────────────
# ディレクトリスキャン
# ──────────────────────────────────────────────
def scan_directory(root_dir: Path) -> List[Dict[str, Any]]:
    all_apis: List[Dict[str, Any]] = []

    for file_path in root_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in file_path.parts):
            continue
        suffix = file_path.suffix.lower()
        if suffix not in TEXT_EXTENSIONS and not file_path.name.startswith(".env"):
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except (UnicodeDecodeError, PermissionError, OSError):
            continue

        for api_keyword, api_config in API_KEYWORDS.items():
            if not re.search(re.escape(api_keyword), content, re.IGNORECASE):
                continue
            endpoint = None
            for pattern in api_config["endpoint_patterns"]:
                m = re.search(pattern, content, re.IGNORECASE)
                if m:
                    endpoint = m.group(0)
                    break
            has_key = any(re.search(p, content, re.IGNORECASE) for p in api_config["key_patterns"])
            all_apis.append({"name": api_config["name"], "endpoint": endpoint, "has_key": has_key})

    merged: Dict[str, Dict[str, Any]] = {}
    for api in all_apis:
        key = api["name"]
        if key not in merged:
            merged[key] = api.copy()
        else:
            if api["endpoint"] and not merged[key]["endpoint"]:
                merged[key]["endpoint"] = api["endpoint"]
            if api["has_key"]:
                merged[key]["has_key"] = True

    return list(merged.values())


# ──────────────────────────────────────────────
# モデル一覧取得
# ──────────────────────────────────────────────
def fetch_models(api_name: str, api_key: str) -> List[Dict[str, Any]]:
    config = API_CONFIGS.get(api_name)
    if not config:
        return []

    base_url = config["base_url"]
    endpoint = config["models_endpoint"]
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    headers: Dict[str, str] = {}
    headers.update(config.get("extra_headers", {}))
    params: Dict[str, str] = {}

    auth_header = config["auth_header"]
    auth_prefix = config["auth_prefix"]
    if not auth_header:
        params["key"] = api_key
    elif auth_prefix:
        headers[auth_header] = f"{auth_prefix} {api_key}"
    else:
        headers[auth_header] = api_key

    try:
        resp = requests.get(url, headers=headers, params=params or None, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError):
        return []

    if isinstance(data, dict):
        models = data.get("data") or data.get("models") or []
    else:
        models = data if isinstance(data, list) else []
    if not isinstance(models, list):
        return []

    result = []
    seen_ids: set = set()

    for model in models:
        model_id = model.get(config["model_id_field"], "")
        if not model_id:
            continue

        if api_name == "Gemini" and model_id.startswith("models/"):
            model_id = model_id[len("models/"):]

        # 同一IDの重複を除去（Mistralは同IDを複数capabilityで返す）
        if model_id in seen_ids:
            continue
        seen_ids.add(model_id)

        if api_name == "OpenRouter":
            name_or_id = model.get("name", model_id) + model_id
            if "free" not in name_or_id.lower():
                continue

        if api_name == "Gemini":
            model_name = model.get("displayName", model_id)
        else:
            model_name = model.get("name", model_id)

        # エイリアス（別名）を抽出
        raw_aliases = model.get("aliases", [])
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        aliases = ", ".join(raw_aliases) if raw_aliases else ""

        result.append({
            "id": model_id,
            "name": model_name,
            "aliases": aliases,
            "rate_limit_requests": None,
            "rate_limit_tokens": None,
            "api_name": api_name,
        })

    return result


# ──────────────────────────────────────────────
# モデルごとのレートリミット取得
# ──────────────────────────────────────────────
def _model_endpoint_type(api_name: str, model_id: str) -> str:
    """モデルIDから適切なエンドポイント種別を推定する。"""
    lower = model_id.lower()
    if api_name == "Mistral":
        if "embed" in lower:
            return "embedding"
        # 音声・OCR・モデレーション系はチャット不可
        if any(k in lower for k in ("voxtral", "tts", "transcribe", "ocr", "moderation", "labs-")):
            return "unsupported"
        return "chat"
    if api_name == "OpenAI":
        if "embedding" in lower:
            return "embedding"
        if any(k in lower for k in ("tts", "whisper", "dall-e")):
            return "unsupported"
        return "chat"
    if api_name == "Anthropic":
        return "chat"
    if api_name == "OpenRouter":
        return "chat"
    if api_name == "Gemini":
        # Gemini はレートリミットをAPIで公開していないので全モデル対象外
        return "unsupported"
    return "chat"


def probe_model_rate_limits(api_name: str, api_key: str, model_id: str) -> Dict[str, Optional[int]]:
    """指定モデルへの最小リクエストでRPM/TPMをレスポンスヘッダーから取得する。"""
    endpoint_type = _model_endpoint_type(api_name, model_id)
    if endpoint_type == "unsupported":
        return {"rpm": None, "tpm": None}

    try:
        if api_name == "Mistral":
            if endpoint_type == "embedding":
                resp = requests.post(
                    "https://api.mistral.ai/v1/embeddings",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model_id, "input": ["hi"]},
                    timeout=10,
                )
            else:
                resp = requests.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                    timeout=10,
                )
            if resp.status_code == 200:
                h = resp.headers
                rpm = h.get("x-ratelimit-limit-req-minute")
                tpm = h.get("x-ratelimit-limit-tokens-minute")
                return {"rpm": int(rpm) if rpm else None, "tpm": int(tpm) if tpm else None}

        elif api_name == "Anthropic":
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                h = resp.headers
                rpm = h.get("anthropic-ratelimit-requests-limit")
                tpm = h.get("anthropic-ratelimit-tokens-limit")
                return {"rpm": int(rpm) if rpm else None, "tpm": int(tpm) if tpm else None}

        elif api_name == "OpenAI":
            if endpoint_type == "embedding":
                resp = requests.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model_id, "input": "hi"},
                    timeout=10,
                )
            else:
                resp = requests.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                    timeout=10,
                )
            if resp.status_code == 200:
                h = resp.headers
                rpm = h.get("x-ratelimit-limit-requests")
                tpm = h.get("x-ratelimit-limit-tokens")
                return {"rpm": int(rpm) if rpm else None, "tpm": int(tpm) if tpm else None}

        elif api_name == "OpenRouter":
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                h = resp.headers
                rpm = h.get("x-ratelimit-limit-requests")
                tpm = h.get("x-ratelimit-limit-tokens")
                return {"rpm": int(rpm) if rpm else None, "tpm": int(tpm) if tpm else None}

    except (requests.exceptions.RequestException, ValueError):
        pass

    return {"rpm": None, "tpm": None}


def probe_models_parallel(
    api_name: str,
    api_key: str,
    models: List[Dict[str, Any]],
    max_workers: int = 10,
) -> None:
    """モデルリストへの並列プローブでRPM/TPMをモデルdictに書き込む（in-place）。"""
    def _worker(model: Dict[str, Any]) -> Dict[str, Any]:
        rl = probe_model_rate_limits(api_name, api_key, model["id"])
        return {"id": model["id"], **rl}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_worker, m): m for m in models}
        for future in concurrent.futures.as_completed(futures):
            model = futures[future]
            try:
                result = future.result()
                model["rate_limit_requests"] = result["rpm"]
                model["rate_limit_tokens"] = result["tpm"]
            except Exception:
                pass


# ──────────────────────────────────────────────
# データ整理
# ──────────────────────────────────────────────
def organize_models(all_models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique: Dict[str, Dict[str, Any]] = {}
    for model in all_models:
        model_id = model["id"]
        if model_id not in unique:
            unique[model_id] = model.copy()
        else:
            existing = unique[model_id]
            if (model["api_name"] != existing["api_name"]
                    and model["api_name"] not in existing.get("extra_api_names", [])):
                existing.setdefault("extra_api_names", []).append(model["api_name"])

    result = []
    for model_id, model in unique.items():
        extra = model.get("extra_api_names", [])
        all_names = [model["api_name"]] + extra
        result.append({
            "id": model_id,
            "name": model["name"],
            "aliases": model.get("aliases", ""),
            "api_name": model["api_name"],
            "api_names": ", ".join(all_names),
            "rate_limit_requests": model.get("rate_limit_requests"),
            "rate_limit_tokens": model.get("rate_limit_tokens"),
        })

    return result


# ──────────────────────────────────────────────
# 表示
# ──────────────────────────────────────────────
def display_models(models: List[Dict[str, Any]]) -> None:
    console = Console()

    if not models:
        console.print("[yellow]No models found.[/yellow]")
        return

    provider_models: Dict[str, List[Dict[str, Any]]] = {}
    for model in models:
        api_name = model.get("api_names", model.get("api_name", "Unknown"))
        provider_models.setdefault(api_name, []).append(model)

    console.print("\n[bold]Detected API Models[/bold]")
    for api_name, api_models in provider_models.items():
        table = Table(
            title=api_name,
            box=box.SIMPLE_HEAD,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Model", style="white", min_width=40)
        table.add_column("Aliases", style="dim", min_width=20)
        table.add_column("RPM", justify="right", width=10)
        table.add_column("TPM", justify="right", width=14)

        for model in api_models:
            model_name = model.get("name", model.get("id", "N/A"))
            aliases = model.get("aliases", "") or "-"
            rpm = model.get("rate_limit_requests")
            tpm = model.get("rate_limit_tokens")
            rpm_str = str(rpm) if rpm is not None else "N/A"
            tpm_str = str(tpm) if tpm is not None else "N/A"
            table.add_row(model_name, aliases, rpm_str, tpm_str)

        console.print(table)


# ──────────────────────────────────────────────
# APIキー検索
# ──────────────────────────────────────────────
def _mask_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-4:]


def _is_placeholder(value: str) -> bool:
    stripped = value.strip().rstrip("\\n").rstrip("\\r")
    if not stripped or len(stripped) < 8:
        return True
    lower = stripped.lower()
    placeholder_keywords = [
        "your_api_key", "your-key", "your_key", "xxx", "example", "here",
        "removed", "todo", "placeholder", "test_key", "dummy", "fake",
        "changeme", "change-me", "insert-here", "insert_here",
        "your_api-key", "api_key_here", "key_here",
    ]
    if any(kw in lower for kw in placeholder_keywords):
        return True
    if lower.startswith(("http://", "https://", "/", "./", "~/")):
        return True
    if any(p in lower for p in ("os.getenv", "config.settings", "environ[", "process.env")):
        return True
    if "," in stripped and len(stripped.split(",")) > 2:
        return True
    if re.match(r"^[a-z\-]+$", stripped):
        return True
    if "${{" in stripped or "}}" in stripped:
        return True
    if re.match(r"^\$\{.*\}$", stripped):
        return True
    if re.match(r"^sk-ant-\.\.\.$", stripped):
        return True
    return False


def _build_alias_patterns(api_name: str, env_key: str) -> List[str]:
    aliases = {env_key}
    extra_bases = {"Gemini": ["GOOGLE", "GEMINI"]}
    base = env_key
    for suffix in ["_API_KEY", "_ACCESS_KEY", "_SECRET_KEY", "_TOKEN_KEY"]:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if base == env_key:
        parts = base.rsplit("_", 1)
        if len(parts) == 2:
            base = parts[0]
    for b in [base] + extra_bases.get(api_name, []):
        aliases.add(b + "_KEY")
        aliases.add(b + "_API_KEY")
        for i in range(1, 10):
            aliases.add(f"{b}_{i}")
            aliases.add(f"{b}_KEY_{i}")
    return list(aliases)


def _validate_key(provider: str, key: str) -> bool:
    try:
        if provider == "Mistral":
            resp = requests.get("https://api.mistral.ai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
            return resp.status_code < 400
        elif provider == "Gemini":
            resp = requests.get("https://generativelanguage.googleapis.com/v1/models", headers={"x-goog-api-key": key}, timeout=10)
            return resp.status_code < 400
        elif provider == "OpenRouter":
            resp = requests.get("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
            return resp.status_code < 400
        elif provider == "OpenAI":
            resp = requests.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=10)
            return resp.status_code < 400
    except Exception:
        return False
    return False


def search_api_keys(root_dir: Path) -> List[Dict[str, Any]]:
    script_names = {"api_model_list.py", "api_scanner.py"}

    def _file_priority(fp: Path) -> int:
        if fp.name == ".env" or fp.name.startswith(".env."):
            return 0
        if fp.suffix.lower() in (".log", ".md", ".txt"):
            return 2
        return 1

    alias_to_canonical: Dict[str, str] = {}
    for api_name, api_config in API_CONFIGS.items():
        env_key = api_config.get("env_key", "")
        if not env_key:
            continue
        for alias in _build_alias_patterns(api_name, env_key):
            alias_to_canonical[alias.upper()] = env_key

    all_alias_names = sorted(alias_to_canonical.keys(), key=lambda x: -len(x))
    alias_pattern = re.compile(
        r"(?:^|[\s])(?:" + "|".join(re.escape(a) for a in all_alias_names) + r")"
        r"\s*[=:]\s*(?:['\"]([^'\"]{8,})['\"]|([^\s'\"#]{8,}))",
        re.IGNORECASE | re.MULTILINE,
    )

    candidates: Dict[str, List[Dict[str, Any]]] = {}

    for file_path in root_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in file_path.parts):
            continue
        if file_path.name in script_names:
            continue
        suffix = file_path.suffix.lower()
        if suffix not in TEXT_EXTENSIONS and not file_path.name.startswith(".env"):
            continue
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except (UnicodeDecodeError, PermissionError, OSError):
            continue

        for match in alias_pattern.finditer(content):
            matched_env_name = match.group(0).split("=")[0].split(":")[0].strip()
            if not matched_env_name:
                continue
            upper_name = matched_env_name.upper()
            canonical = alias_to_canonical.get(upper_name)
            if not canonical:
                continue
            value = match.group(1) if match.group(1) else match.group(2)
            if not value:
                continue
            value = value.strip()
            if value.upper() == upper_name:
                continue
            if _is_placeholder(value):
                continue

            api_name_for_key = next(
                (n for n, c in API_CONFIGS.items() if c.get("env_key") == canonical), "Unknown"
            )
            candidates.setdefault(canonical, []).append({
                "api_name": api_name_for_key,
                "env_key": canonical,
                "key": value,
                "file_path": str(file_path.resolve()),
                "file_priority": _file_priority(file_path),
            })

    results = []
    for canonical, cands in candidates.items():
        if not cands:
            continue
        cands.sort(key=lambda c: c["file_priority"])
        api_name_for_key = cands[0]["api_name"]

        selected = None
        priority_groups: Dict[int, List[Dict]] = {}
        for c in cands:
            priority_groups.setdefault(c["file_priority"], []).append(c)
        for priority in sorted(priority_groups.keys()):
            for c in priority_groups[priority]:
                if _validate_key(api_name_for_key, c["key"]):
                    selected = c
                    break
            if selected:
                break
        if not selected:
            selected = cands[0]

        results.append({
            "api_name": selected["api_name"],
            "env_key": selected["env_key"],
            "key": selected["key"],
            "file_path": selected["file_path"],
        })

    return results


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────
def main() -> None:
    console = Console()
    root_dir = Path("/home/loser/wsl-projects")

    # APIキーをスキャンして環境変数に設定
    for key_info in search_api_keys(root_dir):
        os.environ[key_info["env_key"]] = key_info["key"]

    # ディレクトリからAPIを検出
    detected_apis = scan_directory(root_dir)
    detected_api_names = {api["name"] for api in detected_apis}
    for api_name, config in API_CONFIGS.items():
        if api_name in detected_api_names:
            continue
        env_key = config.get("env_key")
        if env_key and os.getenv(env_key):
            detected_apis.append({"name": api_name, "has_key": True})

    if not detected_apis:
        console.print("[yellow]No APIs detected.[/yellow]")
        return

    all_models: List[Dict[str, Any]] = []

    for api in detected_apis:
        api_name = api["name"]
        env_key = API_CONFIGS.get(api_name, {}).get("env_key")
        if not env_key:
            continue
        api_key = os.getenv(env_key)
        if not api_key:
            continue

        # モデル一覧を取得
        models = fetch_models(api_name, api_key)
        if not models:
            continue

        # 各モデルのRPM/TPMを並列プローブ
        console.print(f"[dim]Probing {len(models)} models for {api_name}...[/dim]")
        probe_models_parallel(api_name, api_key, models, max_workers=10)

        all_models.extend(models)

    organized_models = organize_models(all_models)
    display_models(organized_models)


if __name__ == "__main__":
    main()
