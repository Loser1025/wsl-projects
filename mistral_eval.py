"""
Mistral モデル評価スクリプト
3モデルの特徴比較・ツール最適化分析
"""

import os, json, time, statistics
from datetime import datetime
from mistralai.client.sdk import Mistral

API_KEY = "ui1a9mH0OwlSdHzN1fXsA0sG3gepdlb9"
client = Mistral(api_key=API_KEY)

MODELS = [
    "mistral-vibe-cli-latest",
    "mistral-vibe-cli-with-tools",
    "mistral-large-latest",
]

# ── ツール定義（function calling テスト用）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Bashコマンドを実行する",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "実行するコマンド"},
                    "timeout": {"type": "integer", "description": "タイムアウト秒数"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "ファイルの内容を読み込む",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "ファイルパス"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "ファイルに内容を書き込む",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "ファイルパス"},
                    "content": {"type": "string", "description": "書き込む内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "ファイルを検索する",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "検索パターン"},
                    "directory": {"type": "string", "description": "検索対象ディレクトリ"},
                },
                "required": ["pattern"],
            },
        },
    },
]

# ── テストケース定義
TEST_CASES = {
    "reasoning": {
        "label": "推論能力",
        "messages": [{"role": "user", "content": "AとBの2つのバケツがある。Aに5リットル、Bに3リットル入る。水道から水を汲んで、ちょうど4リットルを測る手順を日本語で説明してください。"}],
        "use_tools": False,
        "eval": lambda r: {
            "has_steps": "1." in r or "手順" in r or "まず" in r,
            "mentions_fill": "満たす" in r or "入れる" in r or "いっぱい" in r,
            "mentions_pour": "移す" in r or "注ぐ" in r or "流す" in r,
        },
    },
    "code_gen": {
        "label": "コード生成",
        "messages": [{"role": "user", "content": "PythonでFizzBuzzを書いてください。1から30まで。コードのみ、説明不要。"}],
        "use_tools": False,
        "eval": lambda r: {
            "has_code_block": "```" in r or "def " in r or "for " in r,
            "has_fizzbuzz": "FizzBuzz" in r or "fizzbuzz" in r.lower(),
            "has_range": "range" in r,
            "length": len(r),
        },
    },
    "tool_call": {
        "label": "ツール呼び出し",
        "messages": [{"role": "user", "content": "カレントディレクトリのファイル一覧を表示して、その後 README.md の内容を読んでください。"}],
        "use_tools": True,
        "eval": lambda r: {
            "has_tool_call": "[TOOL_CALL]" in r,
            "mentions_ls_or_bash": "run_bash" in r or "ls" in r or "search_files" in r,
            "mentions_read": "read_file" in r,
        },
    },
    "tool_selection": {
        "label": "ツール選択精度",
        "messages": [{"role": "user", "content": "config.py というファイルを探して、その中の API_KEY という変数の値を確認してください。"}],
        "use_tools": True,
        "eval": lambda r: {
            "has_tool_call": "[TOOL_CALL]" in r,
            "selects_search": "search_files" in r,
            "selects_read": "read_file" in r,
            "avoids_bash_first": not (r.strip().startswith("run_bash") or r.strip().startswith("```bash")),
        },
    },
    "instruction_follow": {
        "label": "指示追従",
        "messages": [{"role": "user", "content": "以下の3点だけ答えてください。箇条書きで。\n1. Pythonのリストとタプルの違い\n2. Pythonのジェネレータとは\n3. デコレータとは"}],
        "use_tools": False,
        "eval": lambda r: {
            "has_bullets": "-" in r or "・" in r or "1." in r,
            "covers_all_3": sum([
                "リスト" in r and "タプル" in r,
                "ジェネレータ" in r,
                "デコレータ" in r,
            ]),
            "not_too_long": len(r) < 1500,
        },
    },
    "japanese": {
        "label": "日本語品質",
        "messages": [{"role": "user", "content": "エージェントシステムにおけるReActフレームワークとは何か、3文以内で説明してください。"}],
        "use_tools": False,
        "eval": lambda r: {
            "in_japanese": any(ord(c) > 0x3000 for c in r),
            "mentions_react": "ReAct" in r or "Reasoning" in r or "推論" in r,
            "mentions_act": "Action" in r or "行動" in r or "実行" in r,
            "concise": len(r) < 400,
        },
    },
    "ambiguous_tool": {
        "label": "曖昧指示でのツール判断",
        "messages": [{"role": "user", "content": "プロジェクトの状態を確認して。"}],
        "use_tools": True,
        "eval": lambda r: {
            "has_tool_call": "[TOOL_CALL]" in r,
            "reasonable_tool": any(t in r for t in ["run_bash", "read_file", "search_files", "list_directory"]),
            "no_hallucination": "エラー" not in r[:50] and len(r) > 10,
        },
    },
}


def call_model(model: str, messages: list, use_tools: bool) -> dict:
    """モデルを呼び出してメタデータと共に返す"""
    kwargs = {"model": model, "messages": messages, "max_tokens": 800}
    if use_tools:
        kwargs["tools"] = TOOLS
        kwargs["tool_choice"] = "auto"

    t0 = time.time()
    try:
        resp = client.chat.complete(**kwargs)
        elapsed = time.time() - t0
        msg = resp.choices[0].message

        # ツール呼び出しがあれば文字列に変換
        content = msg.content or ""
        tool_calls_info = []
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                fn = tc.function
                content += f"\n[TOOL_CALL] {fn.name}({fn.arguments})"
                tool_calls_info.append({
                    "name": fn.name,
                    "args": fn.arguments,
                })

        return {
            "ok": True,
            "content": content,
            "tool_calls": tool_calls_info,
            "elapsed": elapsed,
            "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "output_tokens": resp.usage.completion_tokens if resp.usage else 0,
            "finish_reason": resp.choices[0].finish_reason,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "elapsed": time.time() - t0,
                "content": "", "tool_calls": [], "input_tokens": 0, "output_tokens": 0}


def run_eval():
    results = {m: {"cases": {}, "latencies": [], "token_counts": []} for m in MODELS}

    total_calls = len(MODELS) * len(TEST_CASES)
    done = 0

    for case_id, case in TEST_CASES.items():
        print(f"\n{'─'*60}")
        print(f"テスト: {case['label']} ({case_id})")
        print(f"{'─'*60}")

        for model in MODELS:
            short = model.replace("mistral-", "").replace("-latest", "")
            print(f"  {short}... ", end="", flush=True)

            res = call_model(model, case["messages"], case["use_tools"])
            time.sleep(1.2)  # レート制限対策

            if res["ok"]:
                scores = case["eval"](res["content"])
                results[model]["cases"][case_id] = {
                    "content": res["content"],
                    "tool_calls": res["tool_calls"],
                    "elapsed": res["elapsed"],
                    "input_tokens": res["input_tokens"],
                    "output_tokens": res["output_tokens"],
                    "scores": scores,
                }
                results[model]["latencies"].append(res["elapsed"])
                results[model]["token_counts"].append(res["output_tokens"])
                score_str = ", ".join(f"{k}={'✓' if v else '✗' if isinstance(v, bool) else v}" for k, v in scores.items())
                print(f"{res['elapsed']:.1f}s | {score_str}")
            else:
                print(f"ERROR: {res['error']}")
                results[model]["cases"][case_id] = {"error": res["error"], "scores": {}}

            done += 1

    return results


def summarize(results):
    print(f"\n{'='*70}")
    print("  総合比較サマリー")
    print(f"{'='*70}")

    # モデル略称
    short = {
        "mistral-vibe-cli-latest": "vibe-cli",
        "mistral-vibe-cli-with-tools": "vibe-tools",
        "mistral-large-latest": "large",
    }

    for model in MODELS:
        m = results[model]
        lats = m["latencies"]
        toks = m["token_counts"]
        cases = m["cases"]

        total_score = 0
        max_score = 0
        for cid, c in cases.items():
            for v in c.get("scores", {}).values():
                if isinstance(v, bool):
                    total_score += int(v)
                    max_score += 1
                elif isinstance(v, int):
                    total_score += min(v, 1)
                    max_score += 1

        print(f"\n【{short[model]}】 ({model})")
        print(f"  総合スコア : {total_score}/{max_score} ({100*total_score//max(max_score,1)}%)")
        if lats:
            print(f"  平均レイテンシ: {statistics.mean(lats):.2f}s  (min {min(lats):.1f}s / max {max(lats):.1f}s)")
        if toks:
            print(f"  平均出力トークン: {statistics.mean(toks):.0f}")

        # ツール呼び出し能力まとめ
        tool_cases = ["tool_call", "tool_selection", "ambiguous_tool"]
        tool_hits = sum(
            bool(cases.get(c, {}).get("tool_calls"))
            for c in tool_cases
        )
        print(f"  ツール呼び出し: {tool_hits}/{len(tool_cases)} ケースで発動")

        # 各テストスコア
        print("  テスト別スコア:")
        for cid, case_def in TEST_CASES.items():
            c = cases.get(cid, {})
            if "error" in c:
                print(f"    {case_def['label']:20s} ERROR")
            else:
                sc = c.get("scores", {})
                hits = sum(1 for v in sc.values() if (v is True) or (isinstance(v, int) and v > 0 and v != len(sc)))
                tot = len(sc)
                bar = "█" * hits + "░" * (tot - hits)
                print(f"    {case_def['label']:20s} [{bar}] {hits}/{tot}")


def optimization_recommendations(results):
    print(f"\n{'='*70}")
    print("  エージェントツール最適化案")
    print(f"{'='*70}")

    short = {
        "mistral-vibe-cli-latest": "vibe-cli",
        "mistral-vibe-cli-with-tools": "vibe-tools",
        "mistral-large-latest": "large",
    }

    for model in MODELS:
        m = results[model]
        cases = m["cases"]
        lats = m["latencies"]
        avg_lat = statistics.mean(lats) if lats else 99

        print(f"\n── {short[model]} ──────────────────────────────────")

        # ツール呼び出し頻度
        tool_cases = ["tool_call", "tool_selection", "ambiguous_tool"]
        tool_hit_rate = sum(
            bool(cases.get(c, {}).get("tool_calls"))
            for c in tool_cases
        ) / len(tool_cases)

        # 出力長の傾向
        lengths = [len(c.get("content","")) for c in cases.values() if "content" in c]
        avg_len = statistics.mean(lengths) if lengths else 0

        # コード生成スコア
        code_ok = cases.get("code_gen", {}).get("scores", {}).get("has_code_block", False)

        # 推論スコア
        reason_steps = cases.get("reasoning", {}).get("scores", {}).get("has_steps", False)

        print(f"  ツール発動率: {tool_hit_rate*100:.0f}%  |  平均レイテンシ: {avg_lat:.2f}s  |  平均応答長: {avg_len:.0f}文字")
        print()

        recs = []

        if tool_hit_rate < 0.5:
            recs.append("⚠ ツール発動率が低い → ツール説明文に具体的なトリガーフレーズを追記する")
            recs.append("   例: 'ユーザーがファイルに言及した場合は必ず read_file を使用'")
        elif tool_hit_rate >= 0.8:
            recs.append("✓ ツール発動率が高い → 不要なツール呼び出しを防ぐため system prompt に抑制条件を追加")

        if avg_lat > 3.5:
            recs.append("⚠ レイテンシ高め → max_tokens を制限 (400程度) または並列呼び出しを検討")
        elif avg_lat < 1.5:
            recs.append("✓ 高速 → ストリーミング有効化でUXをさらに改善可能")

        if avg_len > 800:
            recs.append("⚠ 応答が長い傾向 → system prompt に '簡潔に答えよ' 制約を追加")
        elif avg_len < 200:
            recs.append("⚠ 応答が短すぎる傾向 → ツール結果の要約を促すプロンプトを追加")

        if code_ok:
            recs.append("✓ コード生成良好 → コーディングタスクに積極的に割り当て可能")
        else:
            recs.append("⚠ コード生成に難あり → コーディング特化の system prompt が必要")

        if reason_steps:
            recs.append("✓ 推論・手順説明に強い → 複雑なマルチステップタスクに向いている")
        else:
            recs.append("⚠ 推論が弱め → シンプルなツール実行タスクに限定推奨")

        # ツール選択精度
        sel_scores = cases.get("tool_selection", {}).get("scores", {})
        if sel_scores.get("selects_search") and sel_scores.get("selects_read"):
            recs.append("✓ ツール選択精度良好 → ツール数を増やしても安定動作が期待できる")
        elif not sel_scores.get("selects_search"):
            recs.append("⚠ ファイル検索ツールを選択しない傾向 → search_files の description を強化")

        for r in recs:
            print(f"  {r}")

    print(f"\n{'='*70}")
    print("  モデル選定ガイド（mimic_linux エージェント向け）")
    print(f"{'='*70}")

    model_scores = {}
    for model in MODELS:
        cases = results[model]["cases"]
        total = sum(
            int(v) if isinstance(v, bool) else (min(v,1) if isinstance(v, int) else 0)
            for c in cases.values()
            for v in c.get("scores", {}).values()
        )
        model_scores[model] = total

    best = max(model_scores, key=model_scores.get)
    print(f"\n  最高スコアモデル: {short[best]} ({model_scores[best]}点)")
    print()
    print("  用途別推奨:")
    print("  ・シンプルなファイル操作タスク → vibe-cli (軽量・高速)")
    print("  ・ツール多用エージェントタスク → vibe-tools (ツール呼び出し最適化済み)")
    print("  ・複雑な推論・コード生成タスク → large (能力最優先)")


def save_report(results):
    path = "/home/loser/wsl-projects/mistral_eval_report.json"
    # contentが長い場合は切り詰め
    compact = {}
    for model, data in results.items():
        compact[model] = {
            "latencies": data["latencies"],
            "token_counts": data["token_counts"],
            "cases": {
                cid: {
                    "elapsed": c.get("elapsed"),
                    "scores": c.get("scores", {}),
                    "tool_calls": c.get("tool_calls", []),
                    "content_preview": c.get("content", "")[:300],
                }
                for cid, c in data["cases"].items()
            }
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)
    print(f"\n  詳細レポート保存: {path}")


if __name__ == "__main__":
    print(f"Mistral モデル評価開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"対象モデル: {', '.join(MODELS)}")
    print(f"テストケース数: {len(TEST_CASES)}")

    results = run_eval()
    summarize(results)
    optimization_recommendations(results)
    save_report(results)

    print("\n完了。")
