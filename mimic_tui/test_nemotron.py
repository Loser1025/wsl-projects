"""
Nemotron-3-Super (120B A12B) OpenRouter API レスポンス形式テスト
"""
from __future__ import annotations
import os, json, time, requests, sys, io
# Windows cp932 端末でも UTF-8 出力できるようにする
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
API_KEY   = os.getenv("OPENROUTER_KEY_1", "")
MODEL     = "nvidia/nemotron-3-super-120b-a12b"
BASE_URL  = "https://openrouter.ai/api/v1"
HEADERS   = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/mimic3-test",
}

SEP = "=" * 70

def call(payload: dict, label: str) -> dict | None:
    print(f"\n{SEP}")
    print(f"▶ {label}")
    print(SEP)
    t0 = time.time()
    try:
        r = requests.post(f"{BASE_URL}/chat/completions", headers=HEADERS,
                          json=payload, timeout=60)
        elapsed = time.time() - t0
        print(f"  HTTP {r.status_code}  ({elapsed:.2f}s)")
        raw = r.json()
        print(json.dumps(raw, ensure_ascii=False, indent=2))
        return raw
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

def stream_call(payload: dict, label: str):
    print(f"\n{SEP}")
    print(f"▶ {label}")
    print(SEP)
    payload = {**payload, "stream": True}
    t0 = time.time()
    try:
        with requests.post(f"{BASE_URL}/chat/completions", headers=HEADERS,
                           json=payload, stream=True, timeout=60) as r:
            print(f"  HTTP {r.status_code}")
            chunks = []
            for line in r.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    chunks.append(data)
            elapsed = time.time() - t0
            print(f"  受信チャンク数: {len(chunks)}  ({elapsed:.2f}s)")
            print("\n  最初の3チャンク:")
            for c in chunks[:3]:
                print(f"  {c}")
            print("\n  最後の3チャンク:")
            for c in chunks[-3:]:
                print(f"  {c}")
            print(f"\n  全チャンク数: {len(chunks)}")
    except Exception as e:
        print(f"  ERROR: {e}")


# ─── テスト 1: シンプルな1ターン ────────────────────────────────
call({
    "model": MODEL,
    "messages": [{"role": "user", "content": "1+1は？"}],
    "max_tokens": 100,
}, "テスト1: シンプル1ターン (max_tokens=100)")


# ─── テスト 2: system prompt あり ───────────────────────────────
call({
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "あなたは数学の専門家です。"},
        {"role": "user",   "content": "フィボナッチ数列とは何ですか？3行以内で。"},
    ],
    "max_tokens": 200,
    "temperature": 0.7,
}, "テスト2: system prompt + temperature=0.7")


# ─── テスト 3: function calling (tool use) ──────────────────────
call({
    "model": MODEL,
    "messages": [{"role": "user", "content": "東京の今日の天気を教えてください。"}],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "指定した都市の現在の天気を返す",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "都市名"},
                        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                    },
                    "required": ["city"],
                },
            },
        }
    ],
    "tool_choice": "auto",
    "max_tokens": 300,
}, "テスト3: function calling (tool_choice=auto)")


# ─── テスト 4: tool_choice=required ──────────────────────────────
call({
    "model": MODEL,
    "messages": [{"role": "user", "content": "天気を調べて。"}],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "天気を取得",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string"},
                    },
                    "required": ["city"],
                },
            },
        }
    ],
    "tool_choice": "required",
    "max_tokens": 200,
}, "テスト4: function calling (tool_choice=required)")


# ─── テスト 5: ストリーミング ────────────────────────────────────
stream_call({
    "model": MODEL,
    "messages": [{"role": "user", "content": "Pythonのリスト内包表記を例示して。"}],
    "max_tokens": 300,
}, "テスト5: ストリーミング")


# ─── テスト 6: temperature=0 (決定論的) ─────────────────────────
call({
    "model": MODEL,
    "messages": [{"role": "user", "content": "日本の首都は？"}],
    "max_tokens": 50,
    "temperature": 0,
}, "テスト6: temperature=0 (決定論的)")


# ─── テスト 7: response_format JSON ─────────────────────────────
call({
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "必ずJSONで返答してください。"},
        {"role": "user",   "content": '{"name": "田中", "age": 30} を受け取り、挨拶文をJSONで返して。'},
    ],
    "response_format": {"type": "json_object"},
    "max_tokens": 200,
}, "テスト7: response_format=json_object")

print(f"\n{SEP}")
print("全テスト完了")
print(SEP)
