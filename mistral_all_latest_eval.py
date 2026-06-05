"""
Mistral "latest" 全モデル診断スクリプト
15モデル × 8テスト = 120 API呼び出し
RPM制限: 45 → インターバル 1.4s
"""

import json, time, re, statistics
from datetime import datetime
from mistralai.client.sdk import Mistral

KEY = "ui1a9mH0OwlSdHzN1fXsA0sG3gepdlb9"
client = Mistral(api_key=KEY)

MODELS = [
    "codestral-latest",
    "devstral-latest",
    "devstral-medium-latest",
    "magistral-medium-latest",
    "magistral-small-latest",
    "ministral-14b-latest",
    "ministral-3b-latest",
    "ministral-8b-latest",
    "mistral-code-agent-latest",
    "mistral-code-latest",
    "mistral-large-latest",
    "mistral-medium-latest",
    "mistral-small-latest",
    "mistral-tiny-latest",
    "mistral-vibe-cli-latest",
]

# モデルの想定カテゴリ（分析用）
MODEL_CATEGORY = {
    "codestral-latest":        "code",
    "devstral-latest":         "code",
    "devstral-medium-latest":  "code",
    "mistral-code-latest":     "code",
    "mistral-code-agent-latest":"code",
    "mistral-vibe-cli-latest": "code",
    "magistral-medium-latest": "reasoning",
    "magistral-small-latest":  "reasoning",
    "ministral-3b-latest":     "mini",
    "ministral-8b-latest":     "mini",
    "ministral-14b-latest":    "mini",
    "mistral-tiny-latest":     "mini",
    "mistral-small-latest":    "general",
    "mistral-medium-latest":   "general",
    "mistral-large-latest":    "general",
}

TOOLS = [
    {"type": "function", "function": {
        "name": "run_bash",
        "description": "Bashコマンドを実行する。ファイル操作・プロセス実行に使う。一般知識の質問には使わない。",
        "parameters": {"type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "ファイルの内容を読み込む。パスが既知の場合に使う。",
        "parameters": {"type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "search_files",
        "description": "ファイル名・パターンでファイルを検索する。パスが不明な場合に使う。",
        "parameters": {"type": "object",
            "properties": {"pattern": {"type": "string"}, "directory": {"type": "string"}},
            "required": ["pattern"]},
    }},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Webを検索する。最新情報・外部情報が必要なときのみ使う。一般知識には使わない。",
        "parameters": {"type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]},
    }},
]

def _valid_json(text):
    t = re.sub(r"```(?:json)?\n?(.*?)```", r"\1", text.strip(), flags=re.DOTALL).strip()
    try: json.loads(t); return True
    except: return False

TEST_CASES = {
    "code_gen": {
        "label": "コード生成", "category": "code",
        "messages": [{"role":"user","content":"Python で FizzBuzz (1〜30) を書け。コードのみ。"}],
        "use_tools": False,
        "eval": lambda r: {
            "has_code":     bool(re.search(r"\bfor\b|\brange\b", r)),
            "has_fizzbuzz": "fizzbuzz" in r.lower() or "FizzBuzz" in r,
            "no_bloat":     len(r) < 500,
        },
    },
    "code_debug": {
        "label": "デバッグ", "category": "code",
        "messages": [{"role":"user","content":
            "このコードのバグを指摘して修正版を示せ。\n"
            "```python\nresult = [i*2 for i in range(5)]\nprint(result[5])\n```"}],
        "use_tools": False,
        "eval": lambda r: {
            "finds_index_error": any(w in r for w in ["IndexError","インデックス","範囲外","5番目","[4]","result[4]"]),
            "shows_fix":         "result[4]" in r or "range(6)" in r or "[0]" in r or "[-1]" in r,
            "explains":          len(r) > 60,
        },
    },
    "reasoning": {
        "label": "論理推論", "category": "reasoning",
        "messages": [{"role":"user","content":
            "5Lと3Lの容器でちょうど4Lを測る手順を番号付きで答えよ。"}],
        "use_tools": False,
        "eval": lambda r: {
            "numbered":    bool(re.search(r"[1-9][\.）]", r)),
            "uses_volumes": "5" in r and "3" in r,
            "mentions_action": any(w in r for w in ["移す","注ぐ","捨てる","満た","入れる"]),
            "concise":     len(r) < 700,
        },
    },
    "japanese": {
        "label": "日本語品質", "category": "language",
        "messages": [{"role":"user","content":
            "トランスフォーマーの自己注意機構を高校生向けに2文で説明せよ。"}],
        "use_tools": False,
        "eval": lambda r: {
            "in_japanese":  sum(1 for c in r if ord(c) > 0x3000) > 15,
            "within_3sent": r.count("。") <= 3,
            "has_attention": any(w in r for w in ["注意","重み","関係","スコア","attention"]),
        },
    },
    "tool_call": {
        "label": "ツール発動", "category": "tool",
        "messages": [{"role":"user","content":
            "カレントディレクトリのPythonファイル一覧を取得してください。"}],
        "use_tools": True,
        "eval": lambda r: {
            "calls_tool":   "[TOOL]" in r,
            "right_tool":   "run_bash" in r or "search_files" in r,
            "py_pattern":   ".py" in r or "*.py" in r,
        },
    },
    "tool_no_call": {
        "label": "ツール不使用判断", "category": "tool",
        "messages": [{"role":"user","content":
            "Pythonのリストとタプルの違いを教えてください。"}],
        "use_tools": True,
        "eval": lambda r: {
            "no_tool":      "[TOOL]" not in r,
            "answers_list": "リスト" in r or "list" in r.lower(),
            "answers_tuple": "タプル" in r or "tuple" in r.lower(),
        },
    },
    "format_json": {
        "label": "JSON出力", "category": "format",
        "messages": [{"role":"user","content":
            "名前:山田花子、年齢:25、スキル:[Python,SQL] をJSONで出力せよ。JSONのみ。"}],
        "use_tools": False,
        "eval": lambda r: {
            "valid_json":   _valid_json(r),
            "has_name":     "山田" in r or "Yamada" in r,
            "has_skills":   "Python" in r and "SQL" in r,
            "no_bloat":     len(r.strip()) < 300,
        },
    },
    "instruction": {
        "label": "指示追従", "category": "instruction",
        "messages": [{"role":"user","content":
            "次の3点を箇条書きで答えよ。①Gitとは ②commitとは ③pushとは"}],
        "use_tools": False,
        "eval": lambda r: {
            "has_bullets":  bool(re.search(r"[-・①②③1-3][\.）\s]", r)),
            "covers_git":   "git" in r.lower() or "Git" in r,
            "covers_commit": "commit" in r.lower() or "コミット" in r,
            "covers_push":  "push" in r.lower() or "プッシュ" in r,
            "concise":      len(r) < 600,
        },
    },
}

def call_model(model, messages, use_tools):
    kwargs = {"model": model, "messages": messages, "max_tokens": 600}
    if use_tools:
        kwargs["tools"] = TOOLS
        kwargs["tool_choice"] = "auto"
    t0 = time.time()
    try:
        resp = client.chat.complete(**kwargs)
        elapsed = time.time() - t0
        msg = resp.choices[0].message
        # Magistral 等の推論モデルはcontentがオブジェクトリストで返る
        raw = msg.content or ""
        if isinstance(raw, list):
            text_parts, think_parts = [], []
            for chunk in raw:
                ctype = type(chunk).__name__
                if ctype == "TextChunk":
                    text_parts.append(chunk.text or "")
                elif ctype == "ThinkChunk":
                    # thinking は TextChunk のリスト
                    for tc in (chunk.thinking or []):
                        think_parts.append(getattr(tc, "text", ""))
            content  = "\n".join(text_parts).strip()
            thinking = "\n".join(think_parts).strip()
        else:
            content  = raw
            thinking = ""
        tool_calls = []
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                fn = tc.function
                content += f"\n[TOOL] {fn.name}({fn.arguments})"
                tool_calls.append(fn.name)
        usage = resp.usage
        return {
            "ok": True, "content": content, "thinking": thinking,
            "tool_calls": tool_calls, "elapsed": elapsed,
            "input_tok": usage.prompt_tokens if usage else 0,
            "output_tok": usage.completion_tokens if usage else 0,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:80], "content": "", "tool_calls": [],
                "elapsed": time.time() - t0, "input_tok": 0, "output_tok": 0}

def score(sc):
    return sum(1 for v in sc.values() if isinstance(v, bool) and v)

def run_eval():
    results = {m: {"cases": {}, "latencies": [], "output_toks": []} for m in MODELS}

    for case_id, case in TEST_CASES.items():
        print(f"\n{'─'*66}")
        print(f"[{case['category'].upper()}] {case['label']}")
        print(f"{'─'*66}")
        for model in MODELS:
            short = model.replace("-latest","")
            print(f"  {short:35s} ", end="", flush=True)
            res = call_model(model, case["messages"], case["use_tools"])
            time.sleep(1.4)  # RPM 45制限対策
            if res["ok"]:
                sc = case["eval"](res["content"])
                h, t = score(sc), len(sc)
                bar = "█"*h + "░"*(t-h)
                results[model]["cases"][case_id] = {
                    "scores": sc, "content": res["content"][:300],
                    "elapsed": res["elapsed"], "tool_calls": res["tool_calls"],
                    "output_tok": res["output_tok"],
                }
                results[model]["latencies"].append(res["elapsed"])
                results[model]["output_toks"].append(res["output_tok"])
                think_note = f"  thinking:{len(res.get('thinking',''))}c" if res.get("thinking") else ""
                print(f"[{bar}] {h}/{t}  {res['elapsed']:.1f}s  {res['output_tok']}tok{think_note}")
            else:
                results[model]["cases"][case_id] = {"scores": {}, "error": res["error"]}
                print(f"ERROR: {res['error']}")
    return results

def summarize(results):
    cat_label = {"code":"コード","reasoning":"推論","language":"言語",
                 "tool":"ツール","format":"フォーマット","instruction":"指示追従"}

    print(f"\n{'='*72}")
    print("  総合スコアランキング")
    print(f"{'='*72}")

    ranking = []
    for model in MODELS:
        cases = results[model]["cases"]
        total_h = sum(score(c.get("scores",{})) for c in cases.values())
        total_t = sum(len(c.get("scores",{})) for c in cases.values())
        lats = results[model]["latencies"]
        otoks = results[model]["output_toks"]
        ranking.append((model, total_h, total_t, lats, otoks))
    ranking.sort(key=lambda x: -x[1])

    print(f"\n  {'モデル':38s} {'スコア':8s} {'レイテンシ':10s} {'出力tok':8s} カテゴリ")
    print(f"  {'─'*38} {'─'*8} {'─'*10} {'─'*8} {'─'*10}")
    for i, (model, h, t, lats, otoks) in enumerate(ranking, 1):
        pct  = 100*h//max(t,1)
        lat  = f"{statistics.mean(lats):.1f}s" if lats else "─"
        otok = f"{statistics.mean(otoks):.0f}" if otoks else "─"
        cat  = MODEL_CATEGORY.get(model,"─")
        short = model.replace("-latest","")
        marker = " ★" if i <= 3 else ""
        print(f"  {i:2d}. {short:34s} {h}/{t}({pct}%) {lat:10s} {otok:8s} [{cat}]{marker}")

    # カテゴリ別集計
    print(f"\n{'='*72}")
    print("  カテゴリ別平均スコア（モデルカテゴリ × テストカテゴリ）")
    print(f"{'='*72}")

    model_cats = ["code","reasoning","mini","general"]
    test_cats  = list({c["category"] for c in TEST_CASES.values()})

    header = f"  {'':12s}"
    for tc in test_cats:
        header += f" {cat_label.get(tc,tc):8s}"
    print(header)
    print("  " + "─"*60)

    for mc in model_cats:
        mc_models = [m for m in MODELS if MODEL_CATEGORY.get(m)==mc]
        if not mc_models: continue
        row = f"  {mc:12s}"
        for tc in test_cats:
            tc_case_ids = [cid for cid, c in TEST_CASES.items() if c["category"]==tc]
            hits, tots = 0, 0
            for m in mc_models:
                for cid in tc_case_ids:
                    sc = results[m]["cases"].get(cid, {}).get("scores", {})
                    hits += score(sc)
                    tots += len(sc)
            pct = 100*hits//max(tots,1)
            bar = "█"*(pct//10) + "░"*(10-pct//10)
            row += f" {pct:3d}%    "
        print(row)

    # ツール診断
    print(f"\n{'='*72}")
    print("  ツール挙動診断（エージェント適合性）")
    print(f"{'='*72}")
    print(f"\n  {'モデル':35s} {'ツール発動':10s} {'不使用判断':10s} 総合")
    print(f"  {'─'*35} {'─'*10} {'─'*10} {'─'*6}")
    for model in MODELS:
        cases = results[model]["cases"]
        call_ok  = cases.get("tool_call",{}).get("scores",{}).get("calls_tool", False)
        nocall_ok = cases.get("tool_no_call",{}).get("scores",{}).get("no_tool", False)
        both = "◎ 両立" if call_ok and nocall_ok else (
               "△ 発動のみ" if call_ok else (
               "△ 抑制のみ" if nocall_ok else "✗ 両方失敗"))
        short = model.replace("-latest","")
        print(f"  {short:35s} {'✓' if call_ok else '✗':10s} {'✓' if nocall_ok else '✗':10s} {both}")

    # フォーマット安定性
    print(f"\n{'='*72}")
    print("  モデル別 診断サマリー")
    print(f"{'='*72}")

    for model, h, t, lats, otoks in ranking:
        cat = MODEL_CATEGORY.get(model, "─")
        short = model.replace("-latest","")
        cases = results[model]["cases"]
        avg_lat = statistics.mean(lats) if lats else 0
        avg_tok = statistics.mean(otoks) if otoks else 0
        pct = 100*h//max(t,1)

        tags = []
        if avg_lat < 2:   tags.append("高速")
        elif avg_lat > 6: tags.append("低速")
        if avg_tok < 100: tags.append("簡潔")
        elif avg_tok > 400: tags.append("冗長")
        if cases.get("code_gen",{}).get("scores",{}).get("has_code",False): tags.append("コード○")
        if cases.get("reasoning",{}).get("scores",{}).get("numbered",False): tags.append("推論○")
        if cases.get("format_json",{}).get("scores",{}).get("valid_json",False): tags.append("JSON○")
        call_ok  = cases.get("tool_call",{}).get("scores",{}).get("calls_tool",False)
        nocall_ok= cases.get("tool_no_call",{}).get("scores",{}).get("no_tool",False)
        if call_ok and nocall_ok: tags.append("ツール◎")
        elif call_ok:             tags.append("ツール△発動のみ")
        elif nocall_ok:           tags.append("ツール△抑制のみ")

        print(f"\n  [{cat:9s}] {short}")
        print(f"    スコア {h}/{t}({pct}%)  レイテンシ avg {avg_lat:.1f}s  出力 avg {avg_tok:.0f}tok")
        print(f"    特徴: {', '.join(tags) if tags else '─'}")

def save(results):
    path = "/home/loser/wsl-projects/mistral_all_latest_report.json"
    out = {}
    for m, d in results.items():
        out[m] = {
            "category": MODEL_CATEGORY.get(m),
            "latencies": d["latencies"],
            "output_toks": d["output_toks"],
            "cases": {cid: {"scores": c.get("scores",{}), "elapsed": c.get("elapsed"),
                             "tool_calls": c.get("tool_calls",[]),
                             "content_preview": c.get("content","")[:200]}
                      for cid, c in d["cases"].items()},
        }
    with open(path,"w",encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n  レポート保存: {path}")

if __name__ == "__main__":
    print(f"Mistral latest 全モデル診断: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"対象: {len(MODELS)}モデル × {len(TEST_CASES)}テスト = {len(MODELS)*len(TEST_CASES)}回")
    results = run_eval()
    summarize(results)
    save(results)
    print("\n完了。")
