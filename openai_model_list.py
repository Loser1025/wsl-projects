import os
import requests
from rich.console import Console
from rich.table import Table
from typing import Dict, List, Optional, Any


def make_api_request(
    endpoint: str,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    params: Optional[Dict] = None,
) -> Optional[requests.Response]:
    """OpenAPI APIにGETリクエストを送信し、レスポンスを返す。"""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{base_url}{endpoint}"
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        print(f"Error making API request to {url}: {e}")
        return None


def fetch_models(api_key: str) -> Optional[List[Dict[str, Any]]]:
    """GET /v1/models からモデル一覧を取得する。"""
    response = make_api_request("/models", api_key)
    if response is None:
        return None
    return response.json().get("data", [])


def fetch_model_details(api_key: str, model_id: str) -> Optional[Dict[str, Any]]:
    """GET /v1/models/{model_id} から各モデルの詳細情報を取得する。"""
    response = make_api_request(f"/models/{model_id}", api_key)
    if response is None:
        return None
    model_data = response.json()
    rate_limit_requests = response.headers.get("x-ratelimit-limit-requests", "N/A")
    rate_limit_tokens = response.headers.get("x-ratelimit-limit-tokens", "N/A")
    return {
        "id": model_data.get("id"),
        "context_length": model_data.get("context_length"),
        "owned_by": model_data.get("owned_by"),
        "rate_limit_requests": rate_limit_requests,
        "rate_limit_tokens": rate_limit_tokens,
    }


def organize_models(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """重複するモデルをユニークに整理し、openai / openai-internal のみを対象とする。"""
    unique_models: Dict[str, Dict[str, Any]] = {}
    for model in models:
        model_id = model.get("id", "")
        owned_by = model.get("owned_by", "")
        if owned_by in ("openai", "openai-internal") and model_id not in unique_models:
            unique_models[model_id] = model
    return list(unique_models.values())


def fetch_and_organize_model_details(
    api_key: str, models: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """モデル一覧から詳細情報を取得し、整理して返す。"""
    organized_models = organize_models(models)
    detailed_models: List[Dict[str, Any]] = []
    for model in organized_models:
        model_id = model.get("id", "")
        details = fetch_model_details(api_key, model_id)
        if details:
            detailed_models.append(details)
    return detailed_models


def display_models(models: List[Dict[str, Any]], console: Console) -> None:
    """rich ライブラリを使用してモデル情報を表形式で表示する。"""
    table = Table(title="OpenAI Models", show_header=True, header_style="bold magenta")
    table.add_column("Model Name", style="cyan")
    table.add_column("Max Tokens", justify="right")
    table.add_column("RPM (Requests per Minute)", justify="right")
    table.add_column("TPM (Tokens per Minute)", justify="right")

    for model in models:
        model_name = model.get("id", "N/A")
        context_length = model.get("context_length", "N/A")
        rate_limit_requests = model.get("rate_limit_requests", "N/A")
        rate_limit_tokens = model.get("rate_limit_tokens", "N/A")
        table.add_row(
            model_name,
            str(context_length),
            str(rate_limit_requests),
            str(rate_limit_tokens),
        )

    console.print(table)


def create_summary(api_key: str, models: List[Dict[str, Any]], console: Console) -> None:
    """モデルデータが複雑な場合、OpenAI APIを使用してサマリを作成する。"""
    model_data = "\n".join(
        f'- {model.get("id")}: Context Length={model.get("context_length")}, '
        f'RPM={model.get("rate_limit_requests")}, TPM={model.get("rate_limit_tokens")}'
        for model in models
    )
    prompt = f"Please summarize the following OpenAI model data:\n{model_data}"

    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
            },
        )
        response.raise_for_status()
        summary = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        console.print("\n[bold green]Summary:[/bold green]")
        console.print(summary)
    except requests.exceptions.RequestException as e:
        console.print(f"[bold red]Error creating summary:[/bold red] {e}")


def main() -> None:
    console = Console()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        console.print("[bold red]Error:[/bold red] OPENAI_API_KEY environment variable is not set.")
        return

    models = fetch_models(api_key)
    if not models:
        console.print("[bold red]Error:[/bold red] Failed to fetch models.")
        return

    detailed_models = fetch_and_organize_model_details(api_key, models)
    if not detailed_models:
        console.print("[bold red]Error:[/bold red] Failed to fetch model details.")
        return

    display_models(detailed_models, console)

    # オプション: サマリを作成
    create_summary(api_key, detailed_models, console)


if __name__ == "__main__":
    main()
