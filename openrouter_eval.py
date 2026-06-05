"""
OpenRouter モデル評価スクリプト v2
nvidia/nemotron-3-super-120b-a12b:free  vs  openrouter/owl-alpha
テストケース数: 15 （推論・コード・ツール・言語・指示追従・構造出力）
"""

import json, time, re, statistics
from datetime import datetime
from openai import OpenAI

KEYS = [
    "OPENROUTER_KEY_REMOVED",
    "OPENROUTER_KEY_REMOVED",
    "OPENROUTER_KEY_REMOVED",
]

MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/owl-alpha",
]

BASE_URL = "https://openrouter.ai/api/v1"

# キーをラウンドロビンで使う
_key_idx = 0
def next_client():
    global _key_idx
    c = OpenAI(base_url=BASE_URL, api_key=KEYS[_key_idx % len(KEYS)])
    _key_idx += 1
    return c

# ─── ツール定義 ──────────────────────────────────────────────
TOOLS = [
    {"type": "function", "function": {
        "name": "run_bash",
        "description": "Bashコマンドを実行する。ファイル操作・システム情報取得・パッケージ実行に使う。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "実行するbashコマンド"},
            "timeout": {"type": "integer", "description": "タイムアウト秒数（デフォルト60）"},
        }, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "ファイルの内容を読み込む。パスが既知の場合に使う。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "encoding": {"type": "string", "default": "utf-8"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "ファイルに内容を書き込む・上書きする。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["path", "content"]},
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
        "name": "web_search",
        "description": "インターネットで情報を検索する。最新情報が必要な場合に使う。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "patch_file",
        "description": "ファイルの一部をold→newテキスト置換で編集する。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        }, "required": ["path", "old_text", "new_text"]},
    }},
]

# ─── テストケース定義 ─────────────────────────────────────────
def score(results: dict) -> int:
    """True/正の値のみカウント"""
    return sum(
        1 for v in results.values()
        if (isinstance(v, bool) and v) or (isinstance(v, (int, float)) and v > 0 and not isinstance(v, bool))
    )

TEST_CASES = {
    # ── 推論 ──────────────────────────
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
    "logic_knights": {
        "label": "論理推論（騎士と悪人）",
        "category": "reasoning",
        "messages": [{"role": "user", "content":
            "AとBがいる。騎士は常に真実を言い、悪人は常に嘘をつく。"
            "AがBを指して「彼は悪人だ」と言った。AとBの正体（騎士/悪人）を答えよ。理由も示せ。"}],
        "use_tools": False,
        "eval": lambda r: {
            "gives_answer": "騎士" in r or "悪人" in r,
            "gives_reason": "なぜなら" in r or "場合" in r or "もし" in r or "仮定" in r or "とすると" in r,
            "correct": ("Aは悪人" in r or "AとBは同じ" in r or "どちらか一方" in r
                        or "AもBも悪人" in r or "A は悪人" in r),
        },
    },
    "math_reason": {
        "label": "数学的推論",
        "category": "reasoning",
        "messages": [{"role": "user", "content":
            "1から100までの整数の和を求めよ。ガウスの方法を使って計算過程を示せ。"}],
        "use_tools": False,
        "eval": lambda r: {
            "correct_answer": "5050" in r,
            "mentions_gauss": "ガウス" in r or "対称" in r or "100+1" in r or "101" in r,
            "shows_formula": "×" in r or "*" in r or "＊" in r or "=" in r,
            "concise": len(r) < 600,
        },
    },

    # ── コード生成 ─────────────────────
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
            "correct_range": "30" in r or "31" in r,
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

    # ── ツール呼び出し ────────────────
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
        "label": "ツール選択（ファイル探索→読み込み）",
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
    "tool_ambiguous": {
        "label": "ツール判断（曖昧指示）",
        "category": "tool",
        "messages": [{"role": "user", "content":
            "エラーログを確認して原因を調べてください。"}],
        "use_tools": True,
        "eval": lambda r: {
            "calls_tool": "[TOOL]" in r,
            "reasonable_choice": any(t in r for t in ["run_bash", "read_file", "search_files"]),
            "mentions_log": "log" in r.lower() or "ログ" in r,
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

    # ── 指示追従・フォーマット ─────────
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
    "format_strict": {
        "label": "厳密フォーマット（表形式）",
        "category": "format",
        "messages": [{"role": "user", "content":
            "以下3言語を比較するMarkdown表を作れ。列: 言語/型システム/主な用途。\n"
            "Python, Go, Rust"}],
        "use_tools": False,
        "eval": lambda r: {
            "has_table": "|" in r and "---" in r,
            "has_all_langs": "Python" in r and "Go" in r and "Rust" in r,
            "has_correct_cols": "型" in r and "用途" in r,
            "table_rows": r.count("|Python|") + r.count("| Python |") + r.count("Python |") > 0,
        },
    },

    # ── 日本語・多言語 ────────────────
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
            "approachable": "例えば" in r or "つまり" in r or "ように" in r or "みたいな" in r,
        },
    },
    "summarize": {
        "label": "要約能力",
        "category": "language",
        "messages": [{"role": "user", "content":
            "以下を2文で要約せよ。\n"
            "「機械学習とは、コンピュータがデータから自動的にパターンを学習し、"
            "予測や分類などのタスクを実行できるようにする技術である。"
            "教師あり学習、教師なし学習、強化学習の3種類に大別され、"
            "それぞれ異なるアプローチでモデルを訓練する。"
            "近年はディープラーニングの発展により、画像認識や自然言語処理など"
            "様々な分野で人間を超える性能を達成している。」"}],
        "use_tools": False,
        "eval": lambda r: {
            "exactly_2sentences": 1 <= r.count("。") <= 3,
            "covers_ml": "機械学習" in r or "学習" in r,
            "covers_types": "教師" in r or "強化" in r or "3種" in r,
            "shorter_than_original": len(r) < 200,
        },
    },

    # ── マルチターン（コンテキスト保持） ──
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

def _is_valid_json(text: str) -> bool:
    """テキストからJSONブロックを抽出してパース試行"""
    text = text.strip()
    # コードブロック除去
    text = re.sub(r"```(?:json)?\n?(.*?)```", r"\1", text, flags=re.DOTALL).strip()
    try:
        json.loads(text)
        return True
    except Exception:
        return False


# ─── API呼び出し ──────────────────────────────────────────────
def call_model(model: str, messages: list, use_tools: bool, timeout_s: int = 60) -> dict:
    client = next_client()
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": 1000,
        "timeout": timeout_s,
    }
    if use_tools:
        kwargs["tools"] = TOOLS
        kwargs["tool_choice"] = "auto"

    t0 = time.time()
    try:
        resp = client.chat.completions.create(**kwargs)
        elapsed = time.time() - t0
        msg = resp.choices[0].message

        content = msg.content or ""
        tool_calls_info = []

        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                fn = tc.function
                content += f"\n[TOOL] {fn.name}({fn.arguments})"
                tool_calls_info.append({"name": fn.name, "args": fn.arguments})

        usage = resp.usage or type("U", (), {"prompt_tokens": 0, "completion_tokens": 0,
                                              "completion_tokens_details": None})()
        reasoning = 0
        if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
            d = usage.completion_tokens_details
            if hasattr(d, "reasoning_tokens") and d.reasoning_tokens:
                reasoning = d.reasoning_tokens or 0

        return {
            "ok": True,
            "content": content,
            "tool_calls": tool_calls_info,
            "elapsed": elapsed,
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "reasoning_tokens": reasoning,
            "finish_reason": resp.choices[0].finish_reason,
        }
    except Exception as e:
        return {
            "ok": False, "error": str(e),
            "content": "", "tool_calls": [],
            "elapsed": time.time() - t0,
            "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
        }


# ─── 評価実行 ─────────────────────────────────────────────────
def run_eval(repeat: int = 2) -> dict:
    """各テストを repeat 回実行してスコアを安定させる"""
    results = {m: {"cases": {}, "latencies": [], "output_tokens": [], "reasoning_tokens": []}
               for m in MODELS}

    total = len(MODELS) * len(TEST_CASES) * repeat
    done = 0

    for case_id, case in TEST_CASES.items():
        print(f"\n{'─'*64}")
        print(f"[{case['category'].upper()}] {case['label']}")
        print(f"{'─'*64}")

        for model in MODELS:
            short = model.split("/")[-1].replace(":free", "")
            all_scores = []
            all_contents = []
            total_elapsed = 0

            for run in range(repeat):
                print(f"  {short} run{run+1}... ", end="", flush=True)
                res = call_model(model, case["messages"], case["use_tools"])
                time.sleep(1.5)

                if res["ok"]:
                    sc = case["eval"](res["content"])
                    all_scores.append(sc)
                    all_contents.append(res["content"])
                    results[model]["latencies"].append(res["elapsed"])
                    results[model]["output_tokens"].append(res["output_tokens"])
                    results[model]["reasoning_tokens"].append(res["reasoning_tokens"])
                    total_elapsed += res["elapsed"]

                    hit = score(sc)
                    tot = len(sc)
                    bar = "█" * hit + "░" * (tot - hit)
                    rtok = f" | reason:{res['reasoning_tokens']}tok" if res["reasoning_tokens"] > 0 else ""
                    print(f"{res['elapsed']:.1f}s [{bar}]{rtok}")
                else:
                    print(f"ERROR: {res['error'][:60]}")
                    all_scores.append({})
                done += 1

            # 複数実行のスコアを統合（多数決 for bool）
            if all_scores:
                merged = {}
                for key in all_scores[0]:
                    vals = [s[key] for s in all_scores if key in s]
                    if all(isinstance(v, bool) for v in vals):
                        merged[key] = sum(vals) > len(vals) / 2
                    else:
                        merged[key] = max(vals) if vals else 0

                results[model]["cases"][case_id] = {
                    "scores": merged,
                    "contents": all_contents,
                    "avg_elapsed": total_elapsed / max(len(all_scores), 1),
                    "reasoning_tokens": max(
                        (r["reasoning_tokens"] for r in [call_model.__dict__] if False), default=0
                    ),
                }

    return results


# ─── サマリー表示 ─────────────────────────────────────────────
CATEGORY_LABELS = {
    "reasoning": "推論",
    "code":      "コード",
    "tool":      "ツール",
    "format":    "フォーマット",
    "language":  "言語",
    "context":   "コンテキスト",
}

def summarize(results: dict):
    short_name = {
        "nvidia/nemotron-3-super-120b-a12b:free": "nemotron",
        "openrouter/owl-alpha": "owl-alpha",
    }

    print(f"\n{'='*70}")
    print("  総合比較サマリー")
    print(f"{'='*70}")

    for model in MODELS:
        m = results[model]
        cases = m["cases"]
        lats = m["latencies"]
        otoks = m["output_tokens"]
        rtoks = [x for x in m["reasoning_tokens"] if x > 0]

        total_hit = sum(score(c["scores"]) for c in cases.values())
        total_max = sum(len(c["scores"]) for c in cases.values())

        print(f"\n【{short_name[model]}】")
        print(f"  総合スコア     : {total_hit}/{total_max}  ({100*total_hit//max(total_max,1)}%)")
        if lats:
            print(f"  平均レイテンシ  : {statistics.mean(lats):.2f}s  (min {min(lats):.1f} / max {max(lats):.1f})")
        if otoks:
            print(f"  平均出力トークン: {statistics.mean(otoks):.0f}")
        if rtoks:
            print(f"  推論トークン   : avg {statistics.mean(rtoks):.0f}  (思考モデル)")

        # カテゴリ別スコア
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

        # テスト別詳細
        print("  テスト別スコア:")
        for cid, case_def in TEST_CASES.items():
            c = cases.get(cid, {"scores": {}})
            sc = c["scores"]
            h = score(sc)
            t = len(sc)
            bar = "█" * h + "░" * (t - h)
            elapsed = c.get("avg_elapsed", 0)
            print(f"    {case_def['label']:28s} [{bar}] {h}/{t}  {elapsed:.1f}s")


# ─── 最適化提案 ───────────────────────────────────────────────
def optimization_report(results: dict):
    short_name = {
        "nvidia/nemotron-3-super-120b-a12b:free": "nemotron",
        "openrouter/owl-alpha": "owl-alpha",
    }

    print(f"\n{'='*70}")
    print("  エージェントツール最適化提案")
    print(f"{'='*70}")

    for model in MODELS:
        sn = short_name[model]
        m = results[model]
        cases = m["cases"]
        lats = m["latencies"]
        rtoks = [x for x in m["reasoning_tokens"] if x > 0]
        avg_lat = statistics.mean(lats) if lats else 99
        avg_out = statistics.mean(m["output_tokens"]) if m["output_tokens"] else 0

        # ツール系スコア
        tool_case_ids = [cid for cid, c in TEST_CASES.items() if c["category"] == "tool"]
        tool_hit = sum(score(cases[c]["scores"]) for c in tool_case_ids if c in cases)
        tool_max = sum(len(cases[c]["scores"]) for c in tool_case_ids if c in cases)
        tool_pct = 100 * tool_hit // max(tool_max, 1)

        # ツール不使用判断
        no_call_ok = cases.get("tool_no_call", {}).get("scores", {}).get("no_tool_call", False)

        # コード系
        code_hit = sum(score(cases[c]["scores"])
                       for c in cases if TEST_CASES.get(c, {}).get("category") == "code")

        # JSON
        json_ok = cases.get("format_json", {}).get("scores", {}).get("valid_json", False)

        # コンテキスト
        ctx_ok = cases.get("context_retain", {}).get("scores", {}).get("recalls_name", False)

        print(f"\n── {sn} ({'思考モデル' if rtoks else '通常モデル'}) ───────────────────────────────")
        print(f"  ツール精度: {tool_pct}% | レイテンシ: {avg_lat:.2f}s | 平均出力: {avg_out:.0f}tok")
        if rtoks:
            print(f"  ★ 推論トークンを使用（avg {statistics.mean(rtoks):.0f}tok）→ 複雑なタスク向き")
        print()

        recs = []

        # ツール過剰呼び出し
        if no_call_ok:
            recs.append(("✓", "知識で答えられる質問でツールを呼ばない → 無駄なツール実行が少ない"))
        else:
            recs.append(("⚠", "知識質問でもツールを呼ぶ傾向 → system prompt に\n"
                         "   「一般知識の質問にはツールを使わず直接回答せよ」を追加"))

        # ツール精度
        if tool_pct >= 80:
            recs.append(("✓", "ツール選択精度が高い → ツール数を増やしても安定動作が期待できる"))
        elif tool_pct >= 60:
            recs.append(("△", "ツール選択精度は中程度 → 各ツールの description に\n"
                         "   「いつ使うか」のトリガー例を具体的に書く"))
        else:
            recs.append(("⚠", "ツール選択精度が低い → ツール数を絞る（5個以下）か\n"
                         "   system prompt でデフォルトツールを明示する"))

        # レイテンシ
        if avg_lat > 8:
            recs.append(("⚠", f"レイテンシが高い ({avg_lat:.1f}s) → ストリーミング必須。\n"
                         "   max_tokens を 600 以下に制限してタイムアウトを下げる"))
        elif avg_lat > 4:
            recs.append(("△", f"レイテンシがやや高め ({avg_lat:.1f}s) → ストリーミングでUX改善推奨"))
        else:
            recs.append(("✓", f"レイテンシ良好 ({avg_lat:.1f}s) → 同期呼び出しで十分"))

        # 出力トークン
        if avg_out > 600:
            recs.append(("⚠", f"出力が冗長 (avg {avg_out:.0f}tok) → 「簡潔に答えよ」をシステムプロンプトに追加\n"
                         "   またはmax_tokens=500程度に制限する"))
        elif avg_out < 80:
            recs.append(("⚠", f"出力が短すぎる (avg {avg_out:.0f}tok) → ツール結果の解釈・説明を促すプロンプトを追加"))

        # JSON
        if json_ok:
            recs.append(("✓", "JSON出力が正確 → 構造化出力・設定ファイル生成タスクに適用可"))
        else:
            recs.append(("⚠", "JSON出力が不正確 → response_format={type:json_object} を使用する"))

        # コンテキスト
        if ctx_ok:
            recs.append(("✓", "多ターン会話でコンテキストを正確に保持 → 対話型エージェントに適している"))
        else:
            recs.append(("⚠", "コンテキスト保持が弱い → 重要情報はシステムプロンプトに都度注入する"))

        # 思考モデル固有の推奨
        if rtoks:
            recs.append(("★", "思考モデルのためシンプルなツール呼び出しより複雑な推論タスクで真価を発揮\n"
                         "   → 複雑なマルチステップタスクの計画・コードレビュー・デバッグに特に適している"))

        for icon, msg in recs:
            print(f"  {icon} {msg}")

    print(f"\n{'='*70}")
    print("  用途別モデル選定（mimic_linux エージェント向け）")
    print(f"{'='*70}")

    model_totals = {}
    for model in MODELS:
        cases = results[model]["cases"]
        model_totals[model] = sum(score(c["scores"]) for c in cases.values())

    best = max(model_totals, key=model_totals.get)
    print(f"\n  総合最高スコア: {short_name[best]} ({model_totals[best]}点)")
    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │ 用途                │ 推奨             │ 理由  │")
    print("  ├─────────────────────────────────────────────────┤")
    print("  │ 複雑推論・デバッグ    │ nemotron         │ 思考  │")
    print("  │ ファイル操作ループ    │ owl-alpha        │ 速度  │")
    print("  │ 構造化データ生成     │ (JSON精度高い方)  │ 精度  │")
    print("  │ 多ターン対話        │ (ctx保持高い方)   │ 記憶  │")
    print("  └─────────────────────────────────────────────────┘")


def save_report(results: dict):
    path = "/home/loser/wsl-projects/openrouter_eval_report.json"
    compact = {}
    for model, data in results.items():
        compact[model] = {
            "latencies": data["latencies"],
            "output_tokens": data["output_tokens"],
            "reasoning_tokens": data["reasoning_tokens"],
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


# ─── メイン ───────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"OpenRouter モデル評価開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"対象モデル: {', '.join(MODELS)}")
    print(f"テストケース数: {len(TEST_CASES)}  ×  各{2}回実行（多数決スコアリング）")
    print(f"総API呼び出し: {len(MODELS) * len(TEST_CASES) * 2}回")

    results = run_eval(repeat=2)
    summarize(results)
    optimization_report(results)
    save_report(results)

    print("\n完了。")
