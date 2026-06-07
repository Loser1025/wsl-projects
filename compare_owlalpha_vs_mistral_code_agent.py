"""
性能比較テスト（3モデル対決）:
  - OpenRouter "openrouter/owl-alpha"
  - Mistral    "mistral-code-agent-latest"
  - Mistral    "mistral-vibe-cli-fast"

3者とも OpenAI 互換の /chat/completions REST エンドポイントを持つため、
SDK に依存せず requests で直接呼び出す（mistralai/openai パッケージ未導入環境向け）。

APIキーは mimic_tui/.env (OpenRouter) / .env.example (Mistral) から取得。
"""

import json, os, re, time, statistics
from datetime import datetime
import requests

# ─── APIキー（mimic_tui/.env より） ───────────────────────────
OPENROUTER_KEY = "***REMOVED_OPENROUTER_KEY***"
MISTRAL_KEY = "***REMOVED_MISTRAL_KEY***"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"

MODELS = {
    "owl-alpha":  {"provider": "openrouter", "model": "openrouter/owl-alpha"},
    "code-agent": {"provider": "mistral",    "model": "mistral-code-agent-latest"},
    "vibe-fast":  {"provider": "mistral",    "model": "mistral-vibe-cli-fast"},
}

# ─── ツール定義（function calling テスト用） ─────────────────
TOOLS = [
    {"type": "function", "function": {
        "name": "run_bash",
        "description": "Bashコマンドを実行する。ファイル操作・システム情報取得に使う。一般知識の質問には使わない。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "実行するbashコマンド"},
        }, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "ファイルの内容を読み込む。パスが既知の場合に使う。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "ファイル名・パターンでファイルを検索する。",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "directory": {"type": "string", "default": "."},
        }, "required": ["pattern"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "ファイルに内容を書き込む・上書きする。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["path", "content"]},
    }},
]


def _is_valid_json(text: str) -> bool:
    text = text.strip()
    text = re.sub(r"```(?:json)?\n?(.*?)```", r"\1", text, flags=re.DOTALL).strip()
    try:
        json.loads(text)
        return True
    except Exception:
        return False


# ─── テストケース定義 ─────────────────────────────────────────
TEST_CASES = {
    "logic_water": {
        "label": "論理推論（水問題）",
        "category": "reasoning",
        "messages": [{"role": "user", "content":
            "5リットルと3リットルの容器がある。水道から水を自由に汲める。"
            "ちょうど4リットルを計る最短手順を、番号付きステップで日本語で答えよ。"}],
        "use_tools": False,
        "eval": lambda r: {
            "has_numbered_steps": bool(re.search(r"[1-9][\.．\)]", r)),
            "correct_volumes": "5" in r and "3" in r and "4" in r,
            "mentions_pour": any(w in r for w in ["移す", "注ぐ", "流す", "捨てる", "空にする"]),
            "concise": len(r) < 800,
        },
    },
    "code_fizzbuzz": {
        "label": "コード生成（FizzBuzz）",
        "category": "code",
        "messages": [{"role": "user", "content":
            "Python で FizzBuzz (1〜30) を書け。コードのみ、説明不要。"}],
        "use_tools": False,
        "eval": lambda r: {
            "has_code": "for" in r or "range" in r,
            "has_fizzbuzz": "FizzBuzz" in r or "fizzbuzz" in r.lower(),
            "no_explanation": len(r) < 400,
        },
    },
    "code_debug": {
        "label": "コードデバッグ",
        "category": "code",
        "messages": [{"role": "user", "content":
            "以下のPythonコードのバグを指摘し、修正版を示せ。\n"
            "```python\ndef fibonacci(n):\n    if n <= 1:\n        return n\n"
            "    return fibonacci(n-1) + fibonacci(n-2)\n\nresult = [fibonacci(i) for i in range(10)]\n"
            "print(result[10])  # 10番目の値を表示\n```"}],
        "use_tools": False,
        "eval": lambda r: {
            "identifies_index_error": "IndexError" in r or "インデックス" in r or "範囲外" in r or "10" in r,
            "shows_fix": "result[9]" in r or "range(11)" in r or "range(10)" in r,
            "explains_cause": len(r) > 80,
        },
    },
    "code_refactor": {
        "label": "コードリファクタリング",
        "category": "code",
        "messages": [{"role": "user", "content":
            "以下をPython的に書き直せ（リスト内包表記・f-string等を使用）。コードのみ。\n"
            "```python\nresult = []\nfor i in range(1, 11):\n    if i % 2 == 0:\n"
            "        result.append('even: ' + str(i))\n```"}],
        "use_tools": False,
        "eval": lambda r: {
            "uses_comprehension": "[" in r and "for" in r and "if" in r,
            "uses_fstring": "f'" in r or 'f"' in r,
            "correct_logic": "even" in r and ("% 2" in r or "%2" in r),
        },
    },
    "tool_explicit": {
        "label": "ツール呼び出し（明示指示）",
        "category": "tool",
        "messages": [{"role": "user", "content":
            "カレントディレクトリのPythonファイル一覧を取得してください。"}],
        "use_tools": True,
        "eval": lambda r: {
            "calls_tool": "[TOOL]" in r,
            "uses_bash_or_search": "run_bash" in r or "search_files" in r,
            "correct_pattern": ".py" in r or "python" in r.lower() or "*.py" in r,
        },
    },
    "tool_chain": {
        "label": "ツール選択（探索→読み込み）",
        "category": "tool",
        "messages": [{"role": "user", "content":
            "config.py というファイルを探して、その中身を読んでください。"}],
        "use_tools": True,
        "eval": lambda r: {
            "calls_tool": "[TOOL]" in r,
            "searches_first": "search_files" in r or ("run_bash" in r and "find" in r.lower()),
            "plans_to_read": "read_file" in r or "読む" in r or "確認" in r,
        },
    },
    "tool_no_call": {
        "label": "ツール不使用判断（知識で答えられる）",
        "category": "tool",
        "messages": [{"role": "user", "content":
            "Pythonのリストとタプルの違いを教えてください。"}],
        "use_tools": True,
        "eval": lambda r: {
            "no_tool_call": "[TOOL]" not in r,
            "answers_directly": "リスト" in r and "タプル" in r,
            "mentions_mutable": "変更" in r or "mutable" in r or "immutable" in r or "不変" in r,
        },
    },
    "format_json": {
        "label": "JSON出力フォーマット",
        "category": "format",
        "messages": [{"role": "user", "content":
            "以下の情報をJSONで出力せよ。説明不要、JSONのみ。\n"
            "名前: 田中太郎、年齢: 30、スキル: [Python, Go, SQL]"}],
        "use_tools": False,
        "eval": lambda r: {
            "valid_json": _is_valid_json(r),
            "has_name": "田中" in r or "Tanaka" in r,
            "has_skills": "Python" in r and "Go" in r,
            "no_extra_text": len(r.strip()) < 300,
        },
    },
    "japanese_quality": {
        "label": "日本語品質（専門説明）",
        "category": "language",
        "messages": [{"role": "user", "content":
            "トランスフォーマーアーキテクチャにおける自己注意機構を、"
            "高校生に分かるよう3文以内で説明してください。"}],
        "use_tools": False,
        "eval": lambda r: {
            "in_japanese": sum(1 for c in r if ord(c) > 0x3000) > 20,
            "within_3sentences": r.count("。") <= 4,
            "mentions_attention": "注意" in r or "attention" in r.lower() or "重み" in r,
        },
    },
    "context_retain": {
        "label": "コンテキスト保持（多ターン）",
        "category": "context",
        "messages": [
            {"role": "user", "content": "私の名前はアキラで、好きな言語はRustです。"},
            {"role": "assistant", "content": "承知しました。アキラさん、Rustがお好きなんですね。"},
            {"role": "user", "content": "私の名前と好きな言語を教えてください。"},
        ],
        "use_tools": False,
        "eval": lambda r: {
            "recalls_name": "アキラ" in r,
            "recalls_lang": "Rust" in r,
            "doesnt_hallucinate": "Python" not in r and "Java" not in r,
        },
    },
}


def score(results: dict) -> int:
    return sum(
        1 for v in results.values()
        if (isinstance(v, bool) and v) or (isinstance(v, (int, float)) and v > 0 and not isinstance(v, bool))
    )


# ─── API呼び出し ──────────────────────────────────────────────
def call_model(short_name: str, messages: list, use_tools: bool, timeout_s: int = 90) -> dict:
    info = MODELS[short_name]
    if info["provider"] == "openrouter":
        url, key = OPENROUTER_URL, OPENROUTER_KEY
    else:
        url, key = MISTRAL_URL, MISTRAL_KEY

    body = {"model": info["model"], "messages": messages, "max_tokens": 1000}
    if use_tools:
        body["tools"] = TOOLS
        body["tool_choice"] = "auto"

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    t0 = time.time()
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout_s)
        elapsed = time.time() - t0
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""

        tool_calls_info = []
        for tc in (msg.get("tool_calls") or []):
            fn = tc["function"]
            content += f"\n[TOOL] {fn['name']}({fn['arguments']})"
            tool_calls_info.append({"name": fn["name"], "args": fn["arguments"]})

        usage = data.get("usage") or {}
        return {
            "ok": True,
            "content": content,
            "tool_calls": tool_calls_info,
            "elapsed": elapsed,
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "finish_reason": data["choices"][0].get("finish_reason"),
        }
    except Exception as e:
        return {
            "ok": False, "error": str(e),
            "content": "", "tool_calls": [],
            "elapsed": time.time() - t0,
            "input_tokens": 0, "output_tokens": 0,
        }


# ─── 評価実行 ─────────────────────────────────────────────────
def run_eval(repeat: int = 2) -> dict:
    results = {m: {"cases": {}, "latencies": [], "output_tokens": []} for m in MODELS}

    for case_id, case in TEST_CASES.items():
        print(f"\n{'─'*64}")
        print(f"[{case['category'].upper()}] {case['label']}")
        print(f"{'─'*64}")

        for short in MODELS:
            all_scores, all_contents = [], []
            total_elapsed = 0

            for run in range(repeat):
                print(f"  {short} run{run+1}... ", end="", flush=True)
                res = call_model(short, case["messages"], case["use_tools"])
                time.sleep(1.5)

                if res["ok"]:
                    sc = case["eval"](res["content"])
                    all_scores.append(sc)
                    all_contents.append(res["content"])
                    results[short]["latencies"].append(res["elapsed"])
                    results[short]["output_tokens"].append(res["output_tokens"])
                    total_elapsed += res["elapsed"]

                    hit, tot = score(sc), len(sc)
                    bar = "█" * hit + "░" * (tot - hit)
                    print(f"{res['elapsed']:.1f}s [{bar}]")
                else:
                    print(f"ERROR: {res['error'][:80]}")
                    all_scores.append({})

            if all_scores:
                merged = {}
                for key in (all_scores[0].keys() if all_scores[0] else []):
                    vals = [s[key] for s in all_scores if key in s]
                    if all(isinstance(v, bool) for v in vals):
                        merged[key] = sum(vals) > len(vals) / 2
                    else:
                        merged[key] = max(vals) if vals else 0

                results[short]["cases"][case_id] = {
                    "scores": merged,
                    "contents": all_contents,
                    "avg_elapsed": total_elapsed / max(len(all_scores), 1),
                }

    return results


# ─── サマリー表示 ─────────────────────────────────────────────
CATEGORY_LABELS = {
    "reasoning": "推論", "code": "コード", "tool": "ツール",
    "format": "フォーマット", "language": "言語", "context": "コンテキスト",
}


def summarize(results: dict):
    print(f"\n{'='*70}")
    print("  総合比較サマリー: owl-alpha vs code-agent vs vibe-fast")
    print(f"{'='*70}")

    for short in MODELS:
        m = results[short]
        cases = m["cases"]
        lats = m["latencies"]
        otoks = m["output_tokens"]

        total_hit = sum(score(c["scores"]) for c in cases.values())
        total_max = sum(len(c["scores"]) for c in cases.values())

        print(f"\n【{short}】 ({MODELS[short]['model']} @ {MODELS[short]['provider']})")
        print(f"  総合スコア     : {total_hit}/{total_max}  ({100*total_hit//max(total_max,1)}%)")
        if lats:
            print(f"  平均レイテンシ  : {statistics.mean(lats):.2f}s  (min {min(lats):.1f} / max {max(lats):.1f})")
        if otoks:
            print(f"  平均出力トークン: {statistics.mean(otoks):.0f}")

        cat_scores = {}
        for cid, c in cases.items():
            cat = TEST_CASES[cid]["category"]
            cat_scores.setdefault(cat, [0, 0])
            cat_scores[cat][0] += score(c["scores"])
            cat_scores[cat][1] += len(c["scores"])

        print("  カテゴリ別スコア:")
        for cat, (h, t) in cat_scores.items():
            pct = 100 * h // max(t, 1)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            print(f"    {CATEGORY_LABELS.get(cat, cat):12s} [{bar}] {h}/{t} ({pct}%)")

        print("  テスト別スコア:")
        for cid, case_def in TEST_CASES.items():
            c = cases.get(cid, {"scores": {}})
            sc = c["scores"]
            h, t = score(sc), len(sc)
            bar = "█" * h + "░" * (t - h)
            elapsed = c.get("avg_elapsed", 0)
            print(f"    {case_def['label']:28s} [{bar}] {h}/{t}  {elapsed:.1f}s")

    print(f"\n{'='*70}")
    print("  勝敗判定")
    print(f"{'='*70}")
    totals = {}
    for short in MODELS:
        cases = results[short]["cases"]
        totals[short] = sum(score(c["scores"]) for c in cases.values())
    winner = max(totals, key=totals.get)
    print(f"\n  総合最高スコア: {winner} ({totals[winner]}点)  ※ {totals}")


def save_report(results: dict):
    path = "/home/loser/wsl-projects/three_model_showdown_report.json"
    compact = {}
    for short, data in results.items():
        compact[short] = {
            "model": MODELS[short]["model"],
            "provider": MODELS[short]["provider"],
            "latencies": data["latencies"],
            "output_tokens": data["output_tokens"],
            "cases": {
                cid: {
                    "scores": c.get("scores", {}),
                    "avg_elapsed": c.get("avg_elapsed"),
                    "content_previews": [p[:200] for p in c.get("contents", [])],
                }
                for cid, c in data["cases"].items()
            },
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)
    print(f"\n  詳細レポート保存: {path}")


if __name__ == "__main__":
    print(f"性能比較テスト（3モデル対決）開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    for short, info in MODELS.items():
        print(f"  - {short}: {info['model']} ({info['provider']})")
    print(f"テストケース数: {len(TEST_CASES)}  ×  各2回実行（多数決スコアリング）")
    print(f"総API呼び出し: {len(MODELS) * len(TEST_CASES) * 2}回")

    results = run_eval(repeat=2)
    summarize(results)
    save_report(results)

    print("\n完了。")
