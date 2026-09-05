"""
mcp_bigquery.py — BigQuery MCP Server
======================================
Claude Code から BigQuery に接続するMCPサーバー。
OAuth2認証を使用（client_secret.json + token.json）。

初回セットアップ:
  python setup_bq_auth.py  ← ブラウザ認証でtoken.jsonを生成

起動方法 (Claude Code settings.json で設定):
  "command": "C:\\Users\\Loser\\AppData\\Local\\Programs\\Python\\Python314\\python.exe",
  "args": ["\\\\wsl$\\Ubuntu\\home\\loser\\wsl-projects\\Medicaldepartment\\mcp_bigquery.py"]

提供ツール:
  bq_query        — SQLクエリを実行して結果を返す
  bq_list_datasets — プロジェクト内のデータセット一覧
  bq_list_tables  — データセット内のテーブル一覧
  bq_describe_table — テーブルのスキーマ詳細
"""

import asyncio
import os
import sys
from pathlib import Path

import google.auth
from google.auth.transport.requests import Request
from google.cloud import bigquery
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

DEFAULT_PROJECT = "stream-443709"
MAX_ROWS = 500

server = Server("bigquery-mcp")


def _get_credentials():
    # GOOGLE_APPLICATION_CREDENTIALS か gcloud ADC から自動取得
    creds, project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    if creds.expired and hasattr(creds, "refresh_token") and creds.refresh_token:
        creds.refresh(Request())
    # gcloud configの現在プロジェクトがquota_project_idとして埋め込まれ、
    # そのプロジェクトへのserviceusage権限がないと403になるため、
    # quota projectを送らずクエリ対象プロジェクト自身の権限だけで認可させる
    if hasattr(creds, "with_quota_project"):
        creds = creds.with_quota_project(None)
    return creds


def _get_client(project_id: str = DEFAULT_PROJECT) -> bigquery.Client:
    creds = _get_credentials()
    return bigquery.Client(project=project_id, credentials=creds)


# ════════════════════════════════════════════════════════════════
# ツール定義
# ════════════════════════════════════════════════════════════════
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="bq_query",
            description=(
                "BigQueryでSQLクエリを実行して結果を返す。\n"
                f"最大{MAX_ROWS}行まで返す。それ以上はLIMITを使うこと。\n"
                "例: SELECT * FROM `stream-443709.dataset.table` LIMIT 10"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "実行するSQL（標準SQL形式）"
                    },
                    "project_id": {
                        "type": "string",
                        "description": f"GCPプロジェクトID（デフォルト: {DEFAULT_PROJECT}）",
                        "default": DEFAULT_PROJECT
                    }
                },
                "required": ["sql"]
            }
        ),
        Tool(
            name="bq_list_datasets",
            description="BigQueryプロジェクト内のデータセット一覧を返す。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": f"GCPプロジェクトID（デフォルト: {DEFAULT_PROJECT}）",
                        "default": DEFAULT_PROJECT
                    }
                }
            }
        ),
        Tool(
            name="bq_list_tables",
            description="指定したデータセット内のテーブル一覧を返す。",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "データセットID"
                    },
                    "project_id": {
                        "type": "string",
                        "description": f"GCPプロジェクトID（デフォルト: {DEFAULT_PROJECT}）",
                        "default": DEFAULT_PROJECT
                    }
                },
                "required": ["dataset_id"]
            }
        ),
        Tool(
            name="bq_describe_table",
            description="テーブルのスキーマ（カラム名・型・説明）を返す。",
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "データセットID"
                    },
                    "table_id": {
                        "type": "string",
                        "description": "テーブルID"
                    },
                    "project_id": {
                        "type": "string",
                        "description": f"GCPプロジェクトID（デフォルト: {DEFAULT_PROJECT}）",
                        "default": DEFAULT_PROJECT
                    }
                },
                "required": ["dataset_id", "table_id"]
            }
        ),
    ]


# ════════════════════════════════════════════════════════════════
# ツール実行
# ════════════════════════════════════════════════════════════════
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_event_loop()

    if name == "bq_query":
        result = await loop.run_in_executor(None, _bq_query,
            arguments.get("sql", ""),
            arguments.get("project_id", DEFAULT_PROJECT)
        )
    elif name == "bq_list_datasets":
        result = await loop.run_in_executor(None, _bq_list_datasets,
            arguments.get("project_id", DEFAULT_PROJECT)
        )
    elif name == "bq_list_tables":
        result = await loop.run_in_executor(None, _bq_list_tables,
            arguments.get("dataset_id", ""),
            arguments.get("project_id", DEFAULT_PROJECT)
        )
    elif name == "bq_describe_table":
        result = await loop.run_in_executor(None, _bq_describe_table,
            arguments.get("dataset_id", ""),
            arguments.get("table_id", ""),
            arguments.get("project_id", DEFAULT_PROJECT)
        )
    else:
        result = f"未知のツール: {name}"

    return [TextContent(type="text", text=result)]


# ════════════════════════════════════════════════════════════════
# 実装
# ════════════════════════════════════════════════════════════════
def _bq_query(sql: str, project_id: str) -> str:
    try:
        client = _get_client(project_id)
        job = client.query(sql)
        result = job.result()
        rows = list(result)
        if not rows:
            return "クエリ結果: 0件"

        fields = [field.name for field in result.schema]
        trimmed = rows[:MAX_ROWS]

        lines = ["\t".join(fields)]
        for row in trimmed:
            lines.append("\t".join(str(row[f]) if row[f] is not None else "NULL" for f in fields))

        suffix = f"\n（{len(rows)}件中{len(trimmed)}件表示）" if len(rows) > MAX_ROWS else f"\n合計: {len(rows)}件"
        return "\n".join(lines) + suffix

    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"クエリエラー: {type(e).__name__}: {e}"


def _bq_list_datasets(project_id: str) -> str:
    try:
        client = _get_client(project_id)
        datasets = list(client.list_datasets())
        if not datasets:
            return f"プロジェクト {project_id} にデータセットがありません。"
        return "\n".join(f"  {d.dataset_id}" for d in datasets)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"エラー: {type(e).__name__}: {e}"


def _bq_list_tables(dataset_id: str, project_id: str) -> str:
    try:
        client = _get_client(project_id)
        tables = list(client.list_tables(dataset_id))
        if not tables:
            return f"データセット {dataset_id} にテーブルがありません。"
        return "\n".join(f"  {t.table_id}  ({t.table_type})" for t in tables)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"エラー: {type(e).__name__}: {e}"


def _bq_describe_table(dataset_id: str, table_id: str, project_id: str) -> str:
    try:
        client = _get_client(project_id)
        table_ref = client.get_table(f"{project_id}.{dataset_id}.{table_id}")
        lines = [
            f"テーブル: {project_id}.{dataset_id}.{table_id}",
            f"行数: {table_ref.num_rows:,}",
            f"作成日: {table_ref.created}",
            "",
            "スキーマ:",
        ]
        for field in table_ref.schema:
            mode = f" [{field.mode}]" if field.mode != "NULLABLE" else ""
            desc = f" — {field.description}" if field.description else ""
            lines.append(f"  {field.name}  {field.field_type}{mode}{desc}")
        return "\n".join(lines)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"エラー: {type(e).__name__}: {e}"


# ════════════════════════════════════════════════════════════════
# エントリポイント
# ════════════════════════════════════════════════════════════════
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )

if __name__ == "__main__":
    asyncio.run(main())
