"""
マルチエージェント役割適性試験
各モデルを Architect / Operator / Scribe の3役割でテストし、最適配置を考察する
"""
import sys, os, time, json
sys.path.insert(0, '/home/loser/wsl-projects')
os.chdir('/home/loser/wsl-projects')

from mimic_tui.config import load_config, OpenRouterConfig, GoogleAIConfig, MistralConfig
from pathlib import Path

or_c, gem_c, mis_c, _ = load_config('mimic_tui')

# Mistral モデルを vibe-cli-latest に差し替え
if mis_c:
    mis_c.model = "mistral-vibe-cli-latest"

MODELS = {
    "Owl-Alpha (OpenRouter)":   or_c,
    "Vibe-CLI-Latest (Mistral)": mis_c,
    "Gemma4-31B (Google)":      gem_c,
}

# ── テストプロンプト ──────────────────────────────────────────────

ARCHITECT_PROMPT = """あなたはコード設計の専門エージェントです。

以下のPythonコードにはバグが1つあります。
バグを特定し、edit_file形式（old_string/new_string）で修正案を示してください。

```python
def calculate_average(numbers: list) -> float:
    if not numbers:
        return 0
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers) - 1  # ← バグあり

print(calculate_average([10, 20, 30]))  # 期待値: 20.0
```

回答形式:
1. バグの原因（1-2行で）
2. edit_file での修正:
   old_string: ...
   new_string: ...
3. 修正後の動作確認"""

OPERATOR_PROMPT = """あなたはコマンド実行・テスト検証の専門エージェントです。

以下の要件をすべて満たすbashコマンド群を書いてください:
- Pythonプロジェクト（/home/user/myproject）でpytestを実行
- 失敗したテストのみ詳細表示
- テストカバレッジを計測して80%未満なら警告を出力
- 実行時間を計測して表示
- すべて1回のrun_bashで実行できる形式で

実用性・効率性・エラーハンドリングを重視してください。"""

SCRIBE_PROMPT = """あなたは作業記憶管理の専門エージェントです。

以下の作業ログを800文字以内に圧縮し、update_scratchpadに渡す形式で出力してください。
必ず【ゴール】【完了済み】【次のステップ】【発見・注意】の4セクション形式を守ること。

--- 作業ログ ---
セッション開始: 2026-06-05 10:00
タスク: mimic_tuiのマルチエージェント機能を実装する

10:05 - multi_agent.pyを新規作成。BaseRoleAgent基底クラス、ArchitectAgent、OperatorAgent、ScribeAgentを実装。各エージェントに役割特化ツールセットを割り当てた。Architectは10ツール、Operatorは11ツール、Scribeは3ツール。
10:30 - tools.pyにupdate_scratchpad_smart関数を追加。800文字超過時に末尾切り捨てではなく先頭優先で保持する実装。
10:45 - __main__.pyを修正。全プロバイダー合計キー3本以上の場合にマルチエージェントを有効化。
11:00 - app.pyに/mode multiコマンドを追加。_run_multi()ワーカーを実装。
11:15 - 動作確認完了。全ツール正常に割り当てられることを確認。
発見事項: AccountRotatorが全エージェントで共有されるため、現時点では全エージェントが同一モデルを使用する。将来的には役割ごとに異なるモデルを割り当てる設計拡張が必要。
11:30 - セッション終了。コミット: "feat: multi-agent system implementation"
"""

# ── API 呼び出し ──────────────────────────────────────────────────

import urllib.request, urllib.error

def call_api(config, prompt: str, max_tokens: int = 800) -> tuple[str, float]:
    """APIを呼び出してレスポンスと経過時間を返す"""
    if config is None:
        return "設定なし", 0.0

    key = config.api_keys[0]
    model = config.model

    # エンドポイントをプロバイダーで判定
    name = config.name.lower()
    if "openrouter" in name or "or" in name:
        url = "https://openrouter.ai/api/v1/chat/completions"
    elif "gemini" in name or "google" in name:
        url = f"https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    elif "mistral" in name:
        url = "https://api.mistral.ai/v1/chat/completions"
    else:
        return "不明なプロバイダー", 0.0

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            elapsed = time.time() - t0
            content = data["choices"][0]["message"]["content"]
            return content.strip(), elapsed
    except Exception as e:
        return f"ERROR: {e}", time.time() - t0


# ── 評価基準 ──────────────────────────────────────────────────────

def score_architect(response: str) -> dict:
    """Architect役割の評価"""
    s = {}
    # バグ特定
    s["bug_identified"] = "- 1" in response or "マイナス" in response or "引き算" in response or "- 1" in response
    # edit_file形式
    s["edit_format"]    = "old_string" in response and "new_string" in response
    # コードブロック
    s["has_code"]       = "```" in response
    # 簡潔さ (1000文字以内)
    s["concise"]        = len(response) <= 1500
    s["score"] = sum(s.values())
    return s

def score_operator(response: str) -> dict:
    """Operator役割の評価"""
    s = {}
    s["has_pytest"]     = "pytest" in response
    s["has_coverage"]   = "coverage" in response or "cov" in response
    s["has_timing"]     = "time" in response or "date" in response or "TIMEFORMAT" in response
    s["has_condition"]  = "if" in response and ("80" in response or "coverage" in response)
    s["has_bash_code"]  = "```bash" in response or "```sh" in response or "#!/" in response
    s["score"] = sum(s.values())
    return s

def score_scribe(response: str) -> dict:
    """Scribe役割の評価"""
    s = {}
    s["has_goal"]       = "ゴール" in response or "Goal" in response
    s["has_done"]       = "完了" in response or "Done" in response
    s["has_next"]       = "次" in response or "Next" in response
    s["has_notice"]     = "発見" in response or "注意" in response or "Note" in response
    s["within_800"]     = len(response) <= 800
    # 4セクション全部
    s["all_sections"]   = s["has_goal"] and s["has_done"] and s["has_next"] and s["has_notice"]
    s["score"] = sum(s.values())
    return s


# ── メインテスト実行 ──────────────────────────────────────────────

def main():
    tests = [
        ("Architect", ARCHITECT_PROMPT, score_architect, 1000),
        ("Operator",  OPERATOR_PROMPT,  score_operator,  800),
        ("Scribe",    SCRIBE_PROMPT,    score_scribe,    900),
    ]

    results = {}

    for model_name, config in MODELS.items():
        print(f"\n{'='*60}")
        print(f"🤖 {model_name}  (model: {config.model if config else 'N/A'})")
        print('='*60)
        results[model_name] = {}

        for role, prompt, scorer, max_tok in tests:
            print(f"\n  [{role}] テスト中...", end="", flush=True)
            response, elapsed = call_api(config, prompt, max_tok)
            scores = scorer(response)

            print(f" {elapsed:.1f}s  スコア: {scores['score']}/{len(scores)-1}")

            results[model_name][role] = {
                "score":    scores["score"],
                "max":      len(scores) - 1,
                "elapsed":  round(elapsed, 2),
                "details":  {k: v for k, v in scores.items() if k not in ("score",)},
                "response_len": len(response),
                "response_preview": response[:300] + "..." if len(response) > 300 else response,
            }

    # ── 結果サマリー ──────────────────────────────────────────────
    print(f"\n\n{'='*60}")
    print("📊 テスト結果サマリー")
    print('='*60)

    header = f"{'モデル':<28} {'Architect':>10} {'Operator':>10} {'Scribe':>10} {'合計':>8} {'平均速度':>10}"
    print(header)
    print('-'*78)

    for model_name, roles in results.items():
        a = roles.get("Architect", {})
        o = roles.get("Operator", {})
        s = roles.get("Scribe", {})

        a_str = f"{a.get('score',0)}/{a.get('max',0)}"
        o_str = f"{o.get('score',0)}/{o.get('max',0)}"
        s_str = f"{s.get('score',0)}/{s.get('max',0)}"
        total = a.get('score',0) + o.get('score',0) + s.get('score',0)
        avg_t = (a.get('elapsed',0) + o.get('elapsed',0) + s.get('elapsed',0)) / 3

        print(f"{model_name:<28} {a_str:>10} {o_str:>10} {s_str:>10} {total:>8} {avg_t:>9.1f}s")

    # ── 役割別最優秀 ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("🏆 役割別スコア最高モデル")
    print('='*60)

    for role in ("Architect", "Operator", "Scribe"):
        best = max(results.items(), key=lambda x: (
            x[1].get(role, {}).get('score', 0),
            -x[1].get(role, {}).get('elapsed', 999)  # スコア同点なら速いほうを優先
        ))
        best_score = best[1].get(role, {}).get('score', 0)
        best_max   = best[1].get(role, {}).get('max', 0)
        best_time  = best[1].get(role, {}).get('elapsed', 0)
        print(f"  {role:<12}: {best[0]:<28}  ({best_score}/{best_max}  {best_time:.1f}s)")

    # ── 詳細スコア ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("🔍 詳細スコアブレークダウン")
    print('='*60)
    for model_name, roles in results.items():
        print(f"\n  {model_name}")
        for role, data in roles.items():
            print(f"    [{role}] {data['score']}/{data['max']}  {data['elapsed']}s  {data['response_len']}chars")
            for k, v in data['details'].items():
                mark = "✓" if v else "✗"
                print(f"      {mark} {k}")

    # JSON 保存
    out_path = '/home/loser/wsl-projects/role_aptitude_result.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n結果を保存: {out_path}")


if __name__ == "__main__":
    main()
