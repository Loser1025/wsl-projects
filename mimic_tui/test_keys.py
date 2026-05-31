"""APIキー疎通テスト — python mimic3/test_keys.py で実行"""
import io
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def parse_env(path):
    result = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        result[k.strip()] = v
    return result

def test_mistral(api_key, model):
    print(f"\n[Thinker] Mistral: {model}")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "日本語で「テスト成功」とだけ答えてください。"}],
        "max_tokens": 20,
    }).encode()
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            reply = data["choices"][0]["message"]["content"]
            print(f"  ✓ 応答: {reply}")
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTPError {e.code}: {e.read().decode(errors='replace')[:200]}")
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {e}")

def test_openrouter(api_key, model):
    print(f"\n[Actor] OpenRouter: {model}")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "日本語で「テスト成功」とだけ答えてください。"}],
        "max_tokens": 20,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            reply = data["choices"][0]["message"]["content"]
            print(f"  ✓ 応答: {reply}")
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTPError {e.code}: {e.read().decode(errors='replace')[:200]}")
    except Exception as e:
        print(f"  ✗ {type(e).__name__}: {e}")

env = parse_env(Path(__file__).parent / ".env")

mistral_key = env.get("MISTRAL_API_KEY", "")
mistral_model = env.get("MISTRAL_MODEL", "mistral-large-latest")
if mistral_key and not mistral_key.startswith("YOUR_"):
    test_mistral(mistral_key, mistral_model)
else:
    print("\n[Thinker] MISTRAL_API_KEY 未設定 — スキップ")

or_key = env.get("OPENROUTER_KEY_1", "")
or_model = env.get("OPENROUTER_MODEL", "openrouter/owl-alpha")
if or_key and not or_key.startswith("YOUR_"):
    test_openrouter(or_key, or_model)
else:
    print("\n[Actor] OPENROUTER_KEY_1 未設定 — スキップ")

print()
