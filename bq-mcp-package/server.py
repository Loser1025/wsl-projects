import asyncio
import google.auth
from google.cloud import bigquery
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# 対象プロジェクト一覧
TARGET_PROJECTS = [
    "autocresta",
    "consulting-report",
    "pmm-report",
    "se-leadu",
    "se-saihai-looker"
]

MAX_ROWS = 500

server = Server("multi-project-bq-mcp")

def _get_client(project_id: str) -> bigquery.Client:
    """ADC認証を使用して指定プロジェクトのクライアントを生成"""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/bigquery"])
    return bigquery.Client(project=project_id, credentials=creds)

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="bq_list_all_projects_assets",
            description="全5プロジェクト（autocresta, consulting-report, pmm-report, se-leadu, se-saihai-looker）のデータセットとテーブルを一覧取得します。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="bq_query",
            description="指定したプロジェクトでSQLを実行します。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "enum": TARGET_PROJECTS,
                        "description": "対象プロジェクトID"
                    },
                    "sql": {"type": "string", "description": "標準SQLクエリ"}
                },
                "required": ["project_id", "sql"]
            }
        ),
        Tool(
            name="bq_describe_table",
            description="指定プロジェクトのテーブル詳細（スキーマ）を取得します。",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "enum": TARGET_PROJECTS},
                    "dataset_id": {"type": "string"},
                    "table_id": {"type": "string"}
                },
                "required": ["project_id", "dataset_id", "table_id"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    loop = asyncio.get_event_loop()

    try:
        if name == "bq_list_all_projects_assets":
            results = []
            for pid in TARGET_PROJECTS:
                client = await loop.run_in_executor(None, _get_client, pid)
                datasets = list(client.list_datasets())
                results.append(f"=== Project: {pid} ===")
                if not datasets:
                    results.append("  (No datasets found)")
                for ds in datasets:
                    results.append(f"  Dataset: {ds.dataset_id}")
                    tables = list(client.list_tables(ds.dataset_id))
                    for t in tables:
                        results.append(f"    - {t.table_id} ({t.table_type})")
                results.append("")
            res_text = "\n".join(results)

        elif name == "bq_query":
            pid = arguments["project_id"]
            client = await loop.run_in_executor(None, _get_client, pid)
            job = client.query(arguments["sql"])
            rows = list(job.result())[:MAX_ROWS]
            if not rows:
                res_text = "クエリ成功: 0件"
            else:
                # 簡易的なタブ区切り形式
                header = "\t".join(rows[0].keys())
                data = "\n".join(["\t".join(str(v) for v in row.values()) for row in rows])
                res_text = f"{header}\n{data}\n\n(Max {MAX_ROWS} rows displayed)"

        elif name == "bq_describe_table":
            pid = arguments["project_id"]
            dsid = arguments["dataset_id"]
            tbid = arguments["table_id"]
            client = await loop.run_in_executor(None, _get_client, pid)
            table = client.get_table(f"{pid}.{dsid}.{tbid}")
            schema = "\n".join([f"{f.name}: {f.field_type} ({f.mode})" for f in table.schema])
            res_text = f"Table: {pid}.{dsid}.{tbid}\nRows: {table.num_rows}\n\nSchema:\n{schema}"

        else:
            res_text = f"Unknown tool: {name}"

    except Exception as e:
        res_text = f"Error: {type(e).__name__}: {str(e)}"

    return [TextContent(type="text", text=res_text)]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
