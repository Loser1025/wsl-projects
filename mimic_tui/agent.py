from __future__ import annotations

import collections
import http.client
import json
import os
import queue
import random
import re
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Any
from uuid import uuid4

from .utils import safe_print, C, log, cache_tool_output, get_scratchpad, set_scratchpad
from .config import (
    OpenRouterConfig, GoogleAIConfig, MistralConfig, OPENROUTER_API_BASE,
    MAX_RETRIES, BASE_BACKOFF, MAX_BACKOFF,
    _CHARS_PER_TOKEN, _COMPACTION_RATIO, _COMPACTION_DEFAULT,
    _CTX_EXCEEDED_KEYWORDS,
)

MAX_TOOL_ROUNDS    = 60
_CACHEABLE_TOOLS   = ["read_file", "list_directory", "search_files", "get_repo_map"]


# ── Gemini Context Cache Manager ──────────────────────────────────

class GeminiContextCacheManager:
    """Geminiのシステムプロンプト+ツール定義をContext Cacheとして保持する。
    毎ターンの再送信をなくし、初回以降のTTFT（最初のトークンまでの時間）を削減する。
    作成失敗時は透過的にNoneを返し、呼び出し側はフォールバックする。"""

    _TTL_SEC        = 300   # 5分 (Gemini最小TTL = 60秒)
    _REFRESH_MARGIN = 30    # 期限30秒前に再作成
    _FAIL_BACKOFF   = 600   # 失敗後の再試行抑止期間（10分）

    def __init__(self):
        self._name:         Optional[str] = None   # "cachedContents/xxxx"
        self._expires:      float         = 0.0    # monotonic time
        self._content_hash: str           = ""
        self._cached_model: str           = ""
        self._fail_until:   float         = 0.0    # この時刻まで_create()を試みない

    def get(self, config: "GoogleAIConfig", system_prompt: str,
             tool_specs: list[dict]) -> Optional[str]:
        """有効なキャッシュ名を返す。期限切れ・内容変化時は再作成する。失敗時はNone。"""
        import hashlib
        h = hashlib.md5((system_prompt + repr(tool_specs)).encode()).hexdigest()[:12]
        now = time.monotonic()
        if (self._name
                and self._cached_model == config.model
                and self._content_hash == h
                and now < self._expires - self._REFRESH_MARGIN):
            return self._name
        # モデルが変わった場合はバックオフをリセット
        if self._cached_model and self._cached_model != config.model:
            self._fail_until = 0.0
        # 失敗バックオフ中はスキップ（ログなし）
        if now < self._fail_until:
            return None
        name = self._create(config, system_prompt, tool_specs)
        if name:
            self._name         = name
            self._expires      = now + self._TTL_SEC
            self._content_hash = h
            self._cached_model = config.model
            self._fail_until   = 0.0
            safe_print(C.gray(f"  [GeminiCache] キャッシュ作成: {name}"), flush=True)
        else:
            self._name         = None
            self._cached_model = config.model
            self._fail_until   = now + self._FAIL_BACKOFF
        return self._name

    def invalidate(self) -> None:
        self._name    = None
        self._expires = 0.0

    @staticmethod
    def _create(config: "GoogleAIConfig", system_prompt: str,
                  tool_specs: list[dict]) -> Optional[str]:
        """Gemini cachedContents APIを呼び出してキャッシュを作成し名前を返す。"""
        fn_decls = [
            {
                "name":        s["function"]["name"],
                "description": s["function"].get("description", ""),
                "parameters":  s["function"].get("parameters", {}),
            }
            for s in tool_specs if s.get("function", {}).get("name")
        ]
        body: dict = {
            "model": f"models/{config.model}",
            "ttl":   f"{GeminiContextCacheManager._TTL_SEC}s",
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        if fn_decls:
            body["tools"] = [{"functionDeclarations": fn_decls}]

        api_key = config.api_keys[0] if config.api_keys else ""
        url = (
            "https://generativelanguage.googleapis.com/v1beta/cachedContents"
            f"?key={api_key}"
        )
        try:
            data = json.dumps(body).encode()
            req  = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get("name")
        except urllib.error.HTTPError as e:
            # 404/400 = モデルがキャッシュ非対応（preview系など）。初回のみ表示。
            safe_print(C.gray(f"  [GeminiCache] このモデルはキャッシュ非対応（HTTP {e.code}）、以降スキップ"), flush=True)
            return None
        except Exception as e:
            safe_print(C.gray(f"  [GeminiCache] 作成失敗（フォールバック）: {e}"), flush=True)
            return None


def _is_context_exceeded(message: str) -> bool:
    """エラーメッセージがコンテキスト超過を示しているか判定する。"""
    lower = message.lower()
    return any(kw in lower for kw in _CTX_EXCEEDED_KEYWORDS)


# ── エラー定義 ────────────────────────────────────────────────────

class OpenRouterAPIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"HTTP {status}: {message}")


class RateLimitError(OpenRouterAPIError):
    pass


class ServerError(OpenRouterAPIError):
    pass



# ── AccountRotator 互換ラッパー ───────────────────────────────────

class AccountRotator:
    """OpenRouterConfig をラップし V4 の AccountRotator インタフェースを提供する。"""

    def __init__(self, config_or_list):
        if isinstance(config_or_list, (OpenRouterConfig, GoogleAIConfig, MistralConfig)):
            self._config = config_or_list
        else:
            # config オブジェクトのリストが渡された場合
            from .config import OpenRouterConfig as _C
            api_keys = [getattr(a, "api_key", str(a)) for a in config_or_list]
            self._config = _C(api_keys=api_keys)

    def pick(self) -> tuple[OpenRouterConfig, float]:
        return self._config, 0.0

    def _key_manager(self):
        """config の _key_manager を安全に返す。なければ None。"""
        return getattr(self._config, "_key_manager", None)

    def can_afford_reviewer(self) -> bool:
        """Reviewer を動かすトークンが 2 枚以上残っているか確認する。"""
        km = self._key_manager()
        if km is None:
            return True
        return km.total_tokens_available() >= 2.0

    def wait_to_start(self, step_count: int) -> float:
        """step_count 本のキーが使えるようになるまでの待ち時間（秒）を返す。"""
        km = self._key_manager()
        if km is None:
            return 0.0
        return km.wait_for_n_keys(max(1, step_count))

    @property
    def accounts(self) -> list[OpenRouterConfig]:
        return [self._config]


def _msg_char_count(m: dict) -> int:
    count = len(str(m.get("content", "") or ""))
    for tc in m.get("tool_calls", []):
        count += len(str(tc.get("function", {}).get("arguments", "")))
    return count


def _trim_messages_smart(messages: list[dict]) -> list[dict]:
    protected = messages[:2]
    body = messages[2:]
    if not body:
        return messages
    target_remove = max(2, len(body) // 4)

    # assistant+tool_calls とそれに続く全 role=="tool" を原子ブロックとして識別する。
    # 並列ツール呼び出し（1 assistant に複数 tool result）でも部分削除が起きないようにする。
    blocks: list[tuple[int, int]] = []  # (start_idx, count) — assistant 含む
    i = 0
    while i < len(body):
        m = body[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            j = i + 1
            while j < len(body) and body[j].get("role") == "tool":
                j += 1
            blocks.append((i, j - i))
            i = j
        else:
            i += 1

    # 古いブロックから順に丸ごと削除して target_remove に達するまで続ける
    indices_to_remove: set[int] = set()
    removed = 0
    for start, count in blocks:
        if removed >= target_remove:
            break
        for k in range(start, start + count):
            indices_to_remove.add(k)
        removed += count

    # ブロック削除だけでは足りない場合は非ブロックメッセージを個別に削除
    if removed < target_remove:
        for i in range(len(body)):
            if removed >= target_remove:
                break
            if i not in indices_to_remove:
                indices_to_remove.add(i)
                removed += 1

    return protected + [m for i, m in enumerate(body) if i not in indices_to_remove]


_DIGEST_MAX_LINES = 25
_DIGEST_MAX_CHARS = 1600


def _build_compaction_digest(removed_msgs: list[dict],
                              max_lines: int = _DIGEST_MAX_LINES) -> str:
    """削除対象メッセージから作業履歴をLLMなしで機械抽出する。

    抽出対象: ユーザー指示（先頭80文字）、ツール呼び出し（名前+主要引数）とその成否。
    tool_calls は構造化データなので正確に取れる。成否は直後の tool メッセージの
    先頭文字列で判定する（粗いが「何を試して失敗したか」が残るだけで再試行の重複を防げる）。"""
    lines: list[str] = []
    pending_calls: dict[str, int] = {}  # tool_call_id -> lines index
    for m in removed_msgs:
        role = m.get("role")
        if role == "user":
            content = str(m.get("content", "") or "")
            if content and not content.startswith("["):
                lines.append(f"指示: {' '.join(content.split())[:80]}")
        elif role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "?")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                target = str(args.get("path") or args.get("command")
                             or args.get("task") or args.get("pattern") or "")
                target = " ".join(target.split())[:60]
                lines.append(f"{name}({target})")
                if tc.get("id"):
                    pending_calls[tc["id"]] = len(lines) - 1
        elif role == "tool":
            idx = pending_calls.pop(m.get("tool_call_id", ""), None)
            if idx is not None:
                content = str(m.get("content", "") or "")
                ok = not content.startswith(("ツール実行エラー", "エラー", "[ループ防止]"))
                lines[idx] += " →OK" if ok else " →失敗"
    if not lines:
        return ""
    if len(lines) > max_lines:
        lines = [f"…（先頭{len(lines) - max_lines}行省略）"] + lines[-max_lines:]
    text = "\n".join(f"- {ln}" for ln in lines)
    return text[:_DIGEST_MAX_CHARS]


# ── 永続ダイジェスト（フェーズ4・シャドーモード） ───────────────────
# _compact_if_needed が生成する使い捨てダイジェストを .mimic/digests/ に
# セッション単位でマージ保存する（anchored iterative summarization）。
# 既存の圧縮動作（モデルへ送るnote_text）は一切変更しない。あくまで比較用の
# 記録を並行して残すだけの「シャドーモード」導入であり、切替は行わない。
# 環境変数 MIMIC_PERSISTENT_DIGEST=0 で無効化できる。

_PERSISTENT_DIGEST_MAX_CHARS = 8000  # 肥大化防止: 超過分は古いエントリから削る
_PERSISTENT_DIGEST_KEEP = 50         # ディスク上に保持するセッションダイジェスト数


def _persistent_digest_enabled() -> bool:
    return (os.environ.get("MIMIC_PERSISTENT_DIGEST") or "1").strip() != "0"


def _digests_dir() -> Path:
    p = Path(__file__).parent / ".mimic" / "digests"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _persist_digest_shadow(session_key: str, digest: str) -> None:
    """既存の使い捨て圧縮とは独立に、セッション単位でダイジェストをマージ保存する。

    失敗しても圧縮処理本体には一切影響させない（try/exceptで完全に隔離）。"""
    if not digest or not _persistent_digest_enabled():
        return
    try:
        path = _digests_dir() / f"{session_key}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {"entries": []}
        data.setdefault("entries", []).append(digest)
        merged = "\n".join(data["entries"])
        if len(merged) > _PERSISTENT_DIGEST_MAX_CHARS:
            # 肥大化防止: 古いエントリから機械的に削る
            while data["entries"] and len("\n".join(data["entries"])) > _PERSISTENT_DIGEST_MAX_CHARS:
                data["entries"].pop(0)
        data["updated_at"] = time.time()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _prune_old_digests()
    except Exception:
        pass


def _prune_old_digests() -> None:
    """保持上限を超えた古いダイジェストファイルを削除する（utils.prune_old_sessions相当）。"""
    try:
        files = sorted(_digests_dir().glob("*.json"), key=lambda f: f.stat().st_mtime)
        for f in files[:-_PERSISTENT_DIGEST_KEEP]:
            f.unlink(missing_ok=True)
    except Exception:
        pass


def _repair_message_sequence(messages: list[dict]) -> list[dict]:
    """孤立した tool_calls / tool ロールメッセージを除去する（OpenAI ネイティブ形式）。"""
    repaired = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            # 後続の tool メッセージを収集
            j = i + 1
            tool_msgs = []
            while j < len(messages) and messages[j].get("role") == "tool":
                tool_msgs.append(messages[j])
                j += 1
            expected_ids = {tc["id"] for tc in m["tool_calls"] if tc.get("id")}
            found_ids = {tm.get("tool_call_id") for tm in tool_msgs}
            if expected_ids and not expected_ids.issubset(found_ids):
                # 対応する tool 応答が揃っていない → ブロックごとスキップ
                log.warning({"event": "orphan_tool_calls_removed", "index": i})
                i = j
                continue
            repaired.append(m)
            repaired.extend(tool_msgs)
            i = j
        elif m.get("role") == "tool":
            # 直前が tool_calls を持つ assistant でなければ孤立
            prev = repaired[-1] if repaired else None
            if prev and prev.get("role") == "assistant" and prev.get("tool_calls"):
                repaired.append(m)
            else:
                log.warning({"event": "orphan_tool_result_removed", "index": i})
            i += 1
        else:
            repaired.append(m)
            i += 1
    return repaired


# ── API 呼び出し ──────────────────────────────────────────────────

def _acquire_key_with_wait(config: OpenRouterConfig) -> str:
    """RPM トークンが取れるまで待機し、使用する API キーを返す。"""
    while True:
        api_key, wait = config.acquire_key()
        if wait == 0.0:
            return api_key
        jitter = random.uniform(0.05, 0.3)
        actual_wait = wait + jitter
        safe_print(C.yellow(f"  ⏳ RPM待機中 {actual_wait:.1f}秒 (残トークン不足)"), flush=True)
        time.sleep(actual_wait)


def _build_openrouter_payload(
    config: OpenRouterConfig,
    messages: list[dict],
    tool_specs: list[dict],
    system_prompt: Optional[str],
    json_mode: bool,
    prompt_cache_key: Optional[str] = None,
    cached_content_name: Optional[str] = None,
) -> tuple[dict, str]:
    """ペイロードと使用する API キーを返す。変換不要・全てネイティブ OpenAI 形式。
    cached_content_name が指定された場合はシステムプロンプトとツール定義をキャッシュ参照に置き換える。"""
    send_messages = []
    if system_prompt and not cached_content_name:
        send_messages.append({"role": "system", "content": system_prompt})
    for m in messages:
        clean = {k: v for k, v in m.items() if not k.startswith("_")}
        send_messages.append(clean)

    payload: dict[str, Any] = {
        "model": config.model,
        "messages": send_messages,
    }

    if config.max_tokens > 0:
        payload["max_tokens"] = config.max_tokens

    if cached_content_name:
        # システムプロンプト・ツール定義はキャッシュに含まれているため送信不要
        payload["cachedContent"] = cached_content_name
    elif tool_specs:
        payload["tools"] = tool_specs  # 既に OpenAI 形式
        payload["tool_choice"] = "auto"

    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    if prompt_cache_key and isinstance(config, MistralConfig):
        payload["prompt_cache_key"] = prompt_cache_key

    api_key = _acquire_key_with_wait(config)
    return payload, api_key


def _call_openrouter_api(
    config: OpenRouterConfig,
    messages: list[dict],
    tool_specs: list[dict],
    system_prompt: Optional[str] = None,
    json_mode: bool = False,
    prompt_cache_key: Optional[str] = None,
    cached_content_name: Optional[str] = None,
) -> dict:
    payload, api_key = _build_openrouter_payload(
        config, messages, tool_specs, system_prompt, json_mode,
        prompt_cache_key, cached_content_name,
    )
    url = f"{config.api_base}/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **config.build_auth_headers(api_key)},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        config.report_success(api_key)
        return result
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body_text).get("error", {}).get("message", body_text)
        except Exception:
            msg = body_text
        if e.code == 429:
            config.report_429(api_key)
            raise RateLimitError(e.code, msg)
        if e.code >= 500:
            raise ServerError(e.code, msg)
        raise OpenRouterAPIError(e.code, msg)
    except urllib.error.URLError as e:
        raise OpenRouterAPIError(0, f"ネットワークエラー: {e.reason}")


def _stream_openrouter_api(
    config: OpenRouterConfig,
    messages: list[dict],
    tool_specs: list[dict],
    system_prompt: Optional[str] = None,
    json_mode: bool = False,
    on_model=None,
    prompt_cache_key: Optional[str] = None,
    cached_content_name: Optional[str] = None,
):
    """
    ストリーミング呼び出し。
    yields (text_chunk: str, tool_calls: list[dict], finish_reason: str)
    on_model(actual_model_id) は最初のチャンクで実際のモデルが判明した時点で1度だけ呼ばれる。
    """
    payload, api_key = _build_openrouter_payload(
        config, messages, tool_specs, system_prompt, json_mode,
        prompt_cache_key, cached_content_name,
    )
    payload["stream"] = True

    url = f"{config.api_base}/chat/completions"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **config.build_auth_headers(api_key)},
        method="POST",
    )

    # tool_calls はインデックスで蓄積する
    accumulated_tools: dict[int, dict] = {}
    # reasoning フォールバック用: content が一度も来なかった場合に使用
    accumulated_reasoning = ""
    had_content = False
    _model_reported = False  # on_model コールバックを1度だけ呼ぶためのフラグ

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n\r")
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if not data_str or data_str == "[DONE]":
                    # 蓄積したツール呼び出しを最終チャンクで flush
                    if accumulated_tools:
                        chunk_tools = []
                        for idx in sorted(accumulated_tools):
                            t = accumulated_tools[idx]
                            try:
                                args = json.loads(t.get("arguments", "{}") or "{}")
                            except Exception:
                                args = {}
                            chunk_tools.append({
                            "name": t.get("name", ""), "args": args, "id": t.get("id", ""),
                            "thought_signature": t.get("thought_signature", ""),
                        })
                        yield "", chunk_tools, "tool_calls"
                    if data_str == "[DONE]":
                        # content が一度も来なかった場合、reasoning をフォールバックとして流す
                        if not had_content and accumulated_reasoning:
                            yield accumulated_reasoning, [], ""
                        config.report_success(api_key)
                        return  # ストリーム終了 — 後続データを処理せず即脱出
                    continue
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # 実際に応答しているモデルを1度だけ通知
                if not _model_reported and on_model:
                    _actual = chunk.get("model", "")
                    if _actual:
                        on_model(_actual)
                        _model_reported = True

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason") or ""

                text_chunk = delta.get("content") or ""
                if text_chunk:
                    had_content = True
                elif not had_content:
                    accumulated_reasoning += delta.get("reasoning") or ""

                # tool_calls デルタの蓄積
                for tc_delta in (delta.get("tool_calls") or []):
                    idx = tc_delta.get("index", 0)
                    if idx not in accumulated_tools:
                        accumulated_tools[idx] = {"id": "", "name": "", "arguments": "", "thought_signature": ""}
                    if tc_delta.get("id"):
                        accumulated_tools[idx]["id"] = tc_delta["id"]
                    fn = tc_delta.get("function") or {}
                    if fn.get("name"):
                        accumulated_tools[idx]["name"] = fn["name"]
                    if fn.get("arguments"):
                        accumulated_tools[idx]["arguments"] += fn["arguments"]
                    _sig = (tc_delta.get("extra_content") or {}).get("google", {}).get("thought_signature", "")
                    if _sig:
                        accumulated_tools[idx]["thought_signature"] = _sig
                if finish_reason:
                    chunk_tools = []
                    for i in sorted(accumulated_tools):
                        t = accumulated_tools[i]
                        try:
                            args = json.loads(t.get("arguments", "{}") or "{}")
                        except Exception:
                            args = {}
                        chunk_tools.append({
                            "name": t.get("name", ""), "args": args, "id": t.get("id", ""),
                            "thought_signature": t.get("thought_signature", ""),
                        })
                    accumulated_tools.clear()
                    yield text_chunk, chunk_tools, finish_reason
                else:
                    yield text_chunk, [], ""

    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body_text).get("error", {}).get("message", body_text)
        except Exception:
            msg = body_text
        if e.code == 429:
            config.report_429(api_key)
            raise RateLimitError(e.code, msg)
        if e.code >= 500:
            raise ServerError(e.code, msg)
        raise OpenRouterAPIError(e.code, msg)
    except urllib.error.URLError as e:
        raise OpenRouterAPIError(0, f"ネットワークエラー: {e.reason}")



def _build_tool_call_entry(tc: dict) -> dict:
    call_id = tc.get("id") or f"call_{tc['name']}_{uuid4().hex[:8]}"
    fn: dict = {
        "name": tc["name"],
        "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False),
    }
    entry: dict = {"id": call_id, "type": "function", "function": fn}
    sig = tc.get("thought_signature", "")
    if sig:
        entry["extra_content"] = {"google": {"thought_signature": sig}}
    return entry


# ── diff 表示ユーティリティ ───────────────────────────────────────

def _print_write_diff(fn_name: str, fn_args: dict) -> None:
    path = fn_args.get("path", "?")
    safe_print(C.gray(f"  [{fn_name}] → {path}"))


# ── OpenRouterAgent ───────────────────────────────────────────────

class OpenRouterAgent:
    """ReAct ループエージェント（OpenRouter版）。"""

    def __init__(self, config_or_rotator, tool_registry):
        # AccountRotator でも OpenRouterConfig でも受け付ける
        if isinstance(config_or_rotator, AccountRotator):
            self._config = config_or_rotator._config
        elif isinstance(config_or_rotator, (OpenRouterConfig, GoogleAIConfig, MistralConfig)):
            self._config = config_or_rotator
        else:
            raise TypeError(f"Unsupported config type: {type(config_or_rotator)}")

        self.rotator = AccountRotator(self._config)
        self.tools = tool_registry
        self.conversation: list[dict] = []
        self.system_prompt: Optional[str] = self._config.system_prompt or None
        self.cwd: str = str(Path.cwd().resolve())
        self._task_goal: Optional[str] = None
        self._tool_cache: collections.OrderedDict[str, str] = collections.OrderedDict()
        self._tool_cache_lock = threading.Lock()
        self._tool_cache_max = 128  # LRU 上限
        self.json_mode: bool = False
        self._overhead_cache: tuple[float, int] = (0.0, 0)  # (timestamp, value)
        self._session_cache_key: str = uuid4().hex[:16]
        self._gemini_cache = GeminiContextCacheManager()
        self._recent_writes: list[str] = []  # ハーネス自動記録: セッション内の書き込みファイル
        self._update_compaction_threshold()

    def set_system_prompt(self, prompt: str):
        self.system_prompt = prompt
        self._gemini_cache.invalidate()

    _RECENT_WRITES_SHOWN = 8

    def _build_machine_notes(self) -> str:
        """ハーネスが確実に知っている事実（自己申告に依存しない）を整形する。

        scratchpad はモデルの自己更新頼みで信頼できないため、タスクゴール・
        書き込み済みファイル・直近の委任結果はハーネス側で毎ターン自動併記する。"""
        lines = []
        if self._task_goal:
            lines.append(f"現在のタスク: {self._task_goal[:120]}")
        if self._recent_writes:
            shown = self._recent_writes[-self._RECENT_WRITES_SHOWN:]
            lines.append(f"このセッションで書き込んだファイル: {', '.join(shown)}")
        try:
            from .team import get_delegation_history_brief
            brief = get_delegation_history_brief()
            if brief:
                lines.append("直近の委任: " + " / ".join(brief))
        except Exception:
            pass
        if not lines:
            return ""
        return (
            "--- [ハーネス自動記録（機械生成・正確）] ---\n"
            + "\n".join(f"- {ln}" for ln in lines)
            + "\n--- [自動記録 ここまで] ---\n"
        )

    def _build_skills_section(self) -> str:
        """利用可能Skill（.claude/skills/*/SKILL.md）の name+description 一覧。
        本文は未ロード（progressive disclosure — design doc §3）。"""
        try:
            from .skills import registry as _skill_registry, default_skill_dirs
            if not _skill_registry.list_summaries():
                _skill_registry.scan(default_skill_dirs())
            return _skill_registry.context_header_section()
        except Exception:
            return ""

    def _build_context_header(self) -> str:
        sep = "─" * 40
        return (
            f"[作業フォルダ] {self.cwd}\n"
            f"{sep}\n"
            f"{self._build_machine_notes()}"
            f"{self._build_skills_section()}"
            f"--- [エージェントの自己記憶（Scratchpad）] ---\n"
            f"{get_scratchpad()}\n"
            f"--- [Scratchpad ここまで] ---"
        )

    def _update_compaction_threshold(self):
        """config.context_length から会話圧縮しきい値（文字数）を再計算する。"""
        ctx = self._config.context_length
        if ctx > 0:
            self.compaction_threshold_chars = int(ctx * _CHARS_PER_TOKEN * _COMPACTION_RATIO)
        else:
            self.compaction_threshold_chars = _COMPACTION_DEFAULT

    def _compaction_keep_recent(self) -> int:
        """compaction 後に残す直近メッセージ数をコンテキスト長に応じて計算する。
        小さいコンテキストのモデルでは少なく（最低4）、大きければ最大20。
        平均メッセージサイズ 2000文字 × 2 バッファを想定。"""
        return max(4, min(20, self.compaction_threshold_chars // 4000))

    _OVERHEAD_CACHE_TTL = 1.0  # scratchpad は 1 秒以内の変化を無視

    def _effective_threshold(self) -> int:
        """system_prompt と context_header のオーバーヘッドを差し引いた
        実際に会話履歴に使える文字数上限を返す。
        scratchpad 読み取り（I/O）を 1 秒 TTL でキャッシュしてコスト削減。"""
        now = time.monotonic()
        if now - self._overhead_cache[0] > self._OVERHEAD_CACHE_TTL:
            overhead = len(self.system_prompt or "") + len(self._build_context_header())
            self._overhead_cache = (now, overhead)
        return max(1000, self.compaction_threshold_chars - self._overhead_cache[1])

    def _trim_to_fit(self, messages: list[dict]) -> list[dict]:
        """送信前にペイロードがコンテキスト窓の 90% を超えていたら
        _trim_messages_smart を繰り返してサイズを削減する。"""
        ctx = self._config.context_length
        if ctx <= 0:
            return messages
        max_chars = int(ctx * _CHARS_PER_TOKEN * 0.90)
        sys_chars = len(self.system_prompt or "")
        available = max(2000, max_chars - sys_chars)
        total = sum(_msg_char_count(m) for m in messages)
        trim_count = 0
        while total > available and len(messages) > 4 and trim_count < 8:
            messages = _trim_messages_smart(messages)
            total = sum(_msg_char_count(m) for m in messages)
            trim_count += 1
        if trim_count:
            safe_print(C.yellow(
                f"  ✂ 送信前トリム: {trim_count}回実行 → {total:,}文字 (上限 {available:,}文字)"
            ), flush=True)
        return messages

    def set_cwd(self, path: str):
        self.cwd = path
        safe_print(f"  作業フォルダを変更: {path}")

    def start_task(self, goal: str):
        self._task_goal = goal
        prev = (get_scratchpad() or "").strip()
        if prev:
            # 前タスクの作業記憶を空テンプレで上書きせず引き継ぐ
            # （同一セッション内で連続タスクを実行すると前回の内容を
            #  忘れてしまう問題への対処）
            set_scratchpad(
                f"【ゴール】{goal}\n"
                f"【前タスクまでの記憶】\n{prev[:2000]}\n"
                f"【次のステップ】→ タスク分析中"
            )
        else:
            set_scratchpad(
                f"【ゴール】{goal}\n"
                f"【完了済み】（なし）\n"
                f"【次のステップ】→ タスク分析中\n"
                f"【発見・注意】（なし）"
            )

    def end_task(self):
        self._task_goal = None

    def _task_context(self) -> str:
        if not self._task_goal:
            return ""
        return f"[現在のタスク] {self._task_goal}"

    def clear_history(self):
        self.conversation = []

    def print_status(self):
        n = len(self._config.api_keys)
        safe_print(f"  モデル  : {self._config.model}")
        ctx = self._config.context_length
        ctx_str = f"{ctx:,} tokens" if ctx > 0 else "不明"
        safe_print(f"  CTX窓  : {ctx_str}  (圧縮しきい値: {self._effective_threshold():,} 文字 / 保持上限: {self._compaction_keep_recent()} メッセージ)")
        safe_print(f"  APIキー : {n} 個")
        safe_print(f"  RPM上限 : {self._config.rpm_limit} / キー")
        for i, st in enumerate(self._config._key_manager.status()):
            cd_str  = f"  クールダウン残 {st['cooldown']:.0f}s" if st["cooldown"] > 0 else ""
            cnt_str = f"  429×{st['count_429']}" if st["count_429"] > 0 else ""
            safe_print(f"    key_{i+1}: 残トークン {st['tokens']}/{self._config.rpm_limit}{cd_str}{cnt_str}")
        safe_print(f"  会話履歴: {len(self.conversation)} メッセージ")
        safe_print(f"  作業Dir : {self.cwd}")

    def _compact_if_needed(self):
        effective = self._effective_threshold()
        total_chars = sum(_msg_char_count(m) for m in self.conversation)
        if total_chars <= effective:
            return
        keep_recent = self._compaction_keep_recent()
        first_pair = self.conversation[:2]
        recent_part = self.conversation[-keep_recent:] if keep_recent < len(self.conversation) else []
        removed_msgs = self.conversation[len(first_pair):len(self.conversation) - len(recent_part)]
        removed = len(removed_msgs)
        # 削除する会話から「何をしたか」をLLMなしで機械抽出して残す。
        # 弱いモデルはscratchpadの自己更新が当てにならないため、削除＝完全な記憶喪失に
        # ならないようハーネス側で最低限の作業履歴を保証する。
        digest = _build_compaction_digest(removed_msgs)
        note_text = f"[{removed}件の古い会話を削除しました（コンテキスト節約）]"
        if digest:
            note_text += f"\n[削除された会話の機械ダイジェスト（ハーネス自動抽出）]\n{digest}"
            # フェーズ4（シャドーモード）: モデルへ送る内容は変更せず、比較用に
            # セッション単位でマージ永続化するだけ。失敗しても圧縮処理に影響しない。
            _persist_digest_shadow(self._session_cache_key, digest)
        note = {"role": "user", "content": note_text}
        ack = {"role": "assistant", "content": "了解しました。"}
        self.conversation = first_pair + [note, ack] + recent_part

    def _handle_api_exception(
        self,
        e: Exception,
        attempt: int,
        trim_count: int,
        working_messages: list,
    ) -> tuple[int, int, list]:
        """
        API 例外を処理し (new_attempt, new_trim_count, working_messages) を返す。
        コンテキスト超過は即トリムしてリトライ。バックオフの sleep もここで実行。
        401/403 のみリトライ不可として再送出する。
        """
        # RateLimitError を最初にチェック（OpenRouterAPIError のサブクラスのため先に処理）
        if isinstance(e, RateLimitError):
            msg = e.message
            backoff = min(BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 1), MAX_BACKOFF)
            log.warning({"event": "rate_limited", "status": 429,
                         "attempt": attempt, "backoff_sec": round(backoff, 1),
                         "message": msg[:200]})
            safe_print(C.yellow(
                f"  ⚠ 429 レート制限 → {backoff:.0f}秒待機してリトライ ({msg[:80]})"
            ), flush=True)
            time.sleep(backoff)
            return attempt + 1, trim_count, working_messages

        if isinstance(e, (ServerError, OpenRouterAPIError)):
            msg = e.message
            # コンテキスト超過チェック
            is_ctx = _is_context_exceeded(msg) and e.status in (400, 429)
            if is_ctx and len(working_messages) > 4 and trim_count < 5:
                log.warning({"event": "context_exceeded", "status": e.status,
                             "trim_count": trim_count + 1, "message": msg[:200]})
                safe_print(C.yellow(
                    f"  ✂ {e.status} コンテキスト超過 → メッセージを削減してリトライ"
                ), flush=True)
                return attempt + 1, trim_count + 1, _trim_messages_smart(working_messages)
            # 認証・権限エラーはリトライ不可
            if e.status in (401, 403):
                log.error({"event": "api_auth_error", "status": e.status, "message": msg[:200]})
                safe_print(C.red(f"  ✗ APIエラー({e.status}): {msg}"), flush=True)
                raise e
            backoff = min(BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 2), MAX_BACKOFF)
            label = "サーバーエラー" if isinstance(e, ServerError) else f"APIエラー({e.status})"
            log.warning({"event": "api_error", "status": e.status,
                         "is_server_error": isinstance(e, ServerError),
                         "attempt": attempt, "backoff_sec": round(backoff, 1),
                         "message": msg[:200]})
            safe_print(C.yellow(
                f"  ⚠ {label}: {msg[:100]} → {backoff:.0f}秒待機してリトライ"
            ), flush=True)
            msgs, new_trim = working_messages, trim_count
            if len(msgs) > 4 and trim_count < 5:
                msgs = _trim_messages_smart(msgs)
                new_trim += 1
            time.sleep(backoff)
            return attempt + 1, new_trim, msgs

        # 接続エラー系
        backoff = min(BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 2), MAX_BACKOFF)
        log.warning({"event": "connection_error", "error_type": type(e).__name__,
                     "attempt": attempt, "backoff_sec": round(backoff, 1)})
        safe_print(C.yellow(
            f"  ⚠ 接続エラー → {backoff:.0f}秒待機 ({type(e).__name__})"
        ), flush=True)
        time.sleep(backoff)
        return attempt + 1, trim_count, working_messages

    def _api_call_with_retry(
        self,
        messages: list[dict],
        override_tool_specs: Optional[list] = None,
    ) -> dict:
        _short = isinstance(self._config, MistralConfig)
        tool_specs = override_tool_specs if override_tool_specs is not None else self.tools.get_specs(short=_short)
        attempt = 0
        trim_count = 0
        working_messages = _repair_message_sequence(list(messages))

        while attempt < MAX_RETRIES:
            working_messages = self._trim_to_fit(working_messages)
            try:
                safe_print(C.gray(f"  → {self._config.name} ({self._config.model})"), flush=True)
                result = _call_openrouter_api(
                    self._config, working_messages, tool_specs,
                    system_prompt=self.system_prompt,
                    json_mode=self.json_mode,
                    prompt_cache_key=self._session_cache_key,
                )
                actual = result.get("model", "")
                if actual and actual != self._config.model:
                    safe_print(C.gray(f"  → 実際のモデル: {actual}"), flush=True)
                return result
            except (RateLimitError, ServerError, OpenRouterAPIError,
                    http.client.RemoteDisconnected, ConnectionResetError,
                    ConnectionError, TimeoutError) as e:
                attempt, trim_count, working_messages = self._handle_api_exception(
                    e, attempt, trim_count, working_messages
                )

        raise RuntimeError(f"API最大リトライ数({MAX_RETRIES})を超えました")

    def _stream_react_call(
        self,
        messages: list,
        text_callback=None,
    ) -> tuple[str, list]:
        """ストリーミング ReAct 呼び出し。(full_text, tool_calls) を返す。

        HTTP ストリームをバックグラウンドスレッドで読み、メインスレッドは
        queue.get(timeout=0.05) でポーリングするため Ctrl+C が確実に機能する。
        Gemini使用時はContext Cacheを用いてシステムプロンプト+ツール定義の再送信を省く。
        """
        _short = isinstance(self._config, MistralConfig)
        tool_specs = self.tools.get_specs(short=_short)
        attempt = 0
        trim_count = 0
        working_messages = _repair_message_sequence(list(messages))

        # Gemini Context Cache: システムプロンプト+ツール定義を初回のみ送信してキャッシュ
        _cached_content: Optional[str] = None
        if isinstance(self._config, GoogleAIConfig):
            _cached_content = self._gemini_cache.get(
                self._config, self.system_prompt or "", tool_specs
            )

        while attempt < MAX_RETRIES:
            working_messages = self._trim_to_fit(working_messages)
            try:
                safe_print(C.gray(f"  → {self._config.name} ({self._config.model})"), flush=True)
                full_text = ""
                tool_calls_list: list[dict] = []
                header_printed = False
                cancel_event = threading.Event()
                chunk_queue: queue.Queue = queue.Queue()

                def _on_actual_model(actual: str):
                    if actual != self._config.model:
                        safe_print(
                            C.gray(f"  → 実際のモデル: {actual}"), flush=True
                        )

                def _stream_worker():
                    try:
                        for item in _stream_openrouter_api(
                            self._config, working_messages, tool_specs,
                            self.system_prompt, json_mode=self.json_mode,
                            on_model=_on_actual_model,
                            cached_content_name=_cached_content,
                        ):
                            chunk_queue.put(item)
                            if cancel_event.is_set():
                                break
                    except Exception as exc:
                        chunk_queue.put(exc)
                    finally:
                        chunk_queue.put(None)

                _thread = threading.Thread(target=_stream_worker, daemon=True)
                _thread.start()

                try:
                    while True:
                        try:
                            item = chunk_queue.get(timeout=0.05)
                        except queue.Empty:
                            continue

                        if item is None:
                            break
                        if isinstance(item, Exception):
                            raise item

                        text_chunk, chunk_tools, finish_reason = item

                        if text_chunk:
                            if text_callback is not None:
                                text_callback(text_chunk)
                            else:
                                if not header_printed:
                                    safe_print(f"\n  {C.purple('💭')} ", end="", flush=True)
                                    header_printed = True
                                safe_print(C.purple(text_chunk), end="", flush=True)
                            full_text += text_chunk

                        for ct in chunk_tools:
                            if ct.get("name"):
                                tool_calls_list.append({
                                    "name": ct["name"],
                                    "args": dict(ct.get("args", {})),
                                    "id": ct.get("id", ""),
                                    "thought_signature": ct.get("thought_signature", ""),
                                })

                except KeyboardInterrupt:
                    cancel_event.set()
                    safe_print(C.yellow("\n\n  [割り込み] Ctrl+C"), flush=True)
                    return "__interrupted__", []

                if header_printed:
                    safe_print()
                return full_text, tool_calls_list

            except (RateLimitError, ServerError, OpenRouterAPIError,
                    http.client.RemoteDisconnected, ConnectionResetError,
                    ConnectionError, TimeoutError) as e:
                attempt, trim_count, working_messages = self._handle_api_exception(
                    e, attempt, trim_count, working_messages
                )

        raise RuntimeError(f"ストリーミングAPI最大リトライ数({MAX_RETRIES})を超えました")

    def _extract_text(self, response: dict) -> Optional[str]:
        try:
            msg = response["choices"][0]["message"]
            return msg.get("content") or msg.get("reasoning") or None
        except (KeyError, IndexError):
            return None

    def _extract_tool_calls(self, response: dict) -> list[dict]:
        try:
            tcs = response["choices"][0]["message"].get("tool_calls") or []
            result = []
            for tc in tcs:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}") or "{}")
                except Exception:
                    args = {}
                result.append({
                    "name": fn.get("name", ""),
                    "args": args,
                    "id": tc.get("id", ""),
                    "thought_signature": (tc.get("extra_content") or {}).get("google", {}).get("thought_signature", ""),
                })
            return result
        except (KeyError, IndexError):
            return []

    def _finish_reason(self, response: dict) -> str:
        try:
            reason = response["choices"][0].get("finish_reason") or "UNKNOWN"
            mapping = {"stop": "STOP", "tool_calls": "STOP", "length": "MAX_TOKENS"}
            return mapping.get(reason, reason.upper())
        except (KeyError, IndexError):
            return "UNKNOWN"

    def _make_cache_key(self, fn_name: str, fn_args: dict) -> str:
        return f"{fn_name}:{json.dumps(fn_args, sort_keys=True, ensure_ascii=False)}"

    def _invalidate_cache_for_path(self, path: str):
        # ハーネス自動記録: 書き込み済みファイルを記録（コンテキストヘッダーに毎ターン併記）
        if path:
            if path in self._recent_writes:
                self._recent_writes.remove(path)
            self._recent_writes.append(path)
            del self._recent_writes[:-30]
        parent_dir = str(Path(path).parent)
        dir_key = self._make_cache_key("list_directory", {"path": parent_dir})
        with self._tool_cache_lock:
            for key in list(self._tool_cache):
                if key.startswith("read_file:") and json.dumps(path) in key:
                    self._tool_cache.pop(key, None)
                elif key == dir_key:
                    self._tool_cache.pop(key, None)

    def _run_single_tool(self, tc: dict) -> tuple[str, str]:
        fn_name = tc.get("name", "")
        fn_args = tc.get("args", {})
        call_id = tc.get("id", f"call_{fn_name}")

        cache_key = self._make_cache_key(fn_name, fn_args)
        if fn_name in _CACHEABLE_TOOLS:
            with self._tool_cache_lock:
                if cache_key in self._tool_cache:
                    return self._tool_cache[cache_key], call_id

        tool = self.tools._tools.get(fn_name)
        if not tool:
            result = f"[エラー] ツール '{fn_name}' が見つかりません"
        else:
            try:
                result = tool["fn"](**fn_args)
                if result is None:
                    result = "(完了)"
                result = str(result)
            except Exception as e:
                result = f"[エラー] {fn_name}: {e}\n{traceback.format_exc()}"

        # 書き込み系ツールのキャッシュ無効化
        if fn_name in ("write_file", "edit_file", "patch_file", "delete_file"):
            path = fn_args.get("path", "")
            if path:
                self._invalidate_cache_for_path(path)

        if fn_name in _CACHEABLE_TOOLS:
            with self._tool_cache_lock:
                self._tool_cache[cache_key] = result
                self._tool_cache.move_to_end(cache_key)
                while len(self._tool_cache) > self._tool_cache_max:
                    self._tool_cache.popitem(last=False)  # LRU 退避

        return result, call_id

    def run_stream(self, user_message: str, callback=None) -> str:
        """Interactive モードと同じ表示エンジン（ストリーミング + PipelineTypewriter）で
        ReAct ループを実行する。callback は後方互換のために受け取るが使用しない。"""
        from .utils import PipelineTypewriter
        from .tools import clear_read_files_registry, UserRejectedWriteError
        from uuid import uuid4

        clear_read_files_registry()
        self._compact_if_needed()

        ctx_parts = [p for p in [self._build_context_header(), self._task_context()] if p]
        injected = ("\n\n".join(ctx_parts) + "\n\n" + user_message) if ctx_parts else user_message

        messages: list[dict] = list(self.conversation)
        old_conv_len = len(self.conversation)
        messages.append({"role": "user", "content": injected})

        write_tools = {"write_file", "edit_file", "patch_file", "delete_file"}
        had_tool_call = False
        empty_retry_count = 0
        _MAX_EMPTY_RETRIES = 2

        for _ in range(MAX_TOOL_ROUNDS):
            _tw = PipelineTypewriter()
            _tw.start()
            text, tool_calls = self._stream_react_call(messages, text_callback=_tw.feed)
            _tw.finalize()

            if text == "__interrupted__":
                return "処理を中断しました。"

            if not tool_calls:
                if not text and had_tool_call and empty_retry_count < _MAX_EMPTY_RETRIES:
                    empty_retry_count += 1
                    safe_print(C.yellow(
                        f"  ⚠ 空レスポンス検知 → 報告を促します ({empty_retry_count}/{_MAX_EMPTY_RETRIES})"
                    ), flush=True)
                    messages.append({"role": "assistant", "content": None, "_skip_save": True})
                    messages.append({"role": "user",
                        "content": "ツール実行結果を踏まえて、作業内容と結果を日本語で報告してください。",
                        "_skip_save": True,
                    })
                    continue
                final = text or "(応答なし)"
                self.conversation.append({"role": "user", "content": user_message})
                _save = [m for m in messages[old_conv_len + 1:] if not m.get("_skip_save")]
                self.conversation.extend(_save)
                self.conversation.append({"role": "assistant", "content": final})
                return final

            messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [_build_tool_call_entry(tc) for tc in tool_calls],
            })

            # 書き込みツールが含まれるかで並列/逐次を切り替える
            _has_write = any(tc.get("name") in write_tools for tc in tool_calls)
            had_tool_call = True

            def _exec_stream_tool(tc):
                fn_name = tc.get("name", "")
                fn_args = tc.get("args", {})
                call_id = tc.get("id") or f"call_{fn_name}_{uuid4().hex[:8]}"
                safe_print(
                    f"  {C.bold_green('⚙')} {C.green(fn_name)}"
                    + C.cyan(f"({', '.join(f'{k}={repr(v)[:40]}' for k, v in fn_args.items())})"),
                    flush=True,
                )
                try:
                    result = self.tools.execute(fn_name, fn_args)
                    result_str = cache_tool_output(fn_name, str(result))
                    if fn_name in _CACHEABLE_TOOLS:
                        cache_key = self._make_cache_key(fn_name, fn_args)
                        with self._tool_cache_lock:
                            self._tool_cache[cache_key] = result_str
                except Exception as e:
                    result_str = f"ツール実行エラー: {fn_name}: {e}"
                    safe_print(C.red(f"\n  ✗ [{fn_name}] エラー: {e}"), flush=True)
                return call_id, result_str

            if len(tool_calls) > 1 and not _has_write:
                # 読み取り専用ツールを並列実行
                with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as _ex:
                    _futures = {_ex.submit(_exec_stream_tool, tc): tc for tc in tool_calls}
                    _results_map = {}
                    for _f in as_completed(_futures):
                        _cid, _res = _f.result()
                        _results_map[_cid] = _res
                for tc in tool_calls:
                    call_id = tc.get("id") or f"call_{tc['name']}_{uuid4().hex[:8]}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": _results_map.get(call_id, "(結果なし)"),
                    })
            else:
                # 書き込みツールあり or 単一ツール → 逐次実行
                for tc in tool_calls:
                    fn_name = tc.get("name", "")
                    fn_args = tc.get("args", {})
                    call_id = tc.get("id") or f"call_{fn_name}_{uuid4().hex[:8]}"

                    safe_print(
                        f"  {C.bold_green('⚙')} {C.green(fn_name)}"
                        + C.cyan(f"({', '.join(f'{k}={repr(v)[:40]}' for k, v in fn_args.items())})"),
                        flush=True,
                    )

                    if fn_name in ("write_file", "edit_file", "patch_file"):
                        _print_write_diff(fn_name, fn_args)

                    try:
                        result = self.tools.execute(fn_name, fn_args)
                        result_str = cache_tool_output(fn_name, str(result))
                        if fn_name in _CACHEABLE_TOOLS:
                            cache_key = self._make_cache_key(fn_name, fn_args)
                            with self._tool_cache_lock:
                                self._tool_cache[cache_key] = result_str
                                self._tool_cache.move_to_end(cache_key)
                                while len(self._tool_cache) > self._tool_cache_max:
                                    self._tool_cache.popitem(last=False)
                        elif fn_name in write_tools:
                            self._invalidate_cache_for_path(fn_args.get("path", ""))
                    except UserRejectedWriteError:
                        raise
                    except Exception as e:
                        result_str = f"ツール実行エラー: {fn_name}: {e}"
                        safe_print(C.red(f"\n  ✗ [{fn_name}] エラー: {e}"), flush=True)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result_str,
                    })

        fallback = f"(ReActループ上限 {MAX_TOOL_ROUNDS} ターンに達しました)"
        self.conversation.append({"role": "user", "content": user_message})
        _save = [m for m in messages[old_conv_len + 1:] if not m.get("_skip_save")]
        self.conversation.extend(_save)
        self.conversation.append({"role": "assistant", "content": fallback})
        return fallback

    def run(self, user_message: str) -> str:
        """ReAct ループを実行して最終回答を返す。"""
        from .tools import clear_read_files_registry
        clear_read_files_registry()
        self._compact_if_needed()

        ctx_parts = [p for p in [self._build_context_header(), self._task_context()] if p]
        injected = user_message
        if ctx_parts:
            injected = "\n".join(ctx_parts) + "\n\n" + user_message

        self.conversation.append({"role": "user", "content": injected})

        for round_num in range(MAX_TOOL_ROUNDS):
            response = self._api_call_with_retry(self.conversation)
            text = self._extract_text(response)
            tool_calls = self._extract_tool_calls(response)
            finish = self._finish_reason(response)

            if text:
                safe_print(f"\n  {C.purple('💭')} {C.purple(text)}")

            if not tool_calls:
                final = text or "(応答なし)"
                self.conversation.append({"role": "assistant", "content": final})
                return final

            # アシスタントメッセージを OpenAI ネイティブ形式で記録
            self.conversation.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [_build_tool_call_entry(tc) for tc in tool_calls],
            })

            # 並列ツール実行
            results = []
            if len(tool_calls) == 1:
                result, call_id = self._run_single_tool(tool_calls[0])
                safe_print(C.gray(f"  🔧 {tool_calls[0]['name']} → {str(result)[:80]}"))
                results.append({"call_id": call_id, "result": result})
            else:
                with ThreadPoolExecutor(max_workers=min(len(tool_calls), 4)) as ex:
                    futures = {ex.submit(self._run_single_tool, tc): tc for tc in tool_calls}
                    for future in as_completed(futures):
                        tc = futures[future]
                        result, call_id = future.result()
                        safe_print(C.gray(f"  🔧 {tc['name']} → {str(result)[:80]}"))
                        results.append({"call_id": call_id, "result": result})

            # ツール結果を OpenAI ネイティブ形式（role: tool）で追加
            for r in results:
                self.conversation.append({
                    "role": "tool",
                    "tool_call_id": r["call_id"],
                    "content": r["result"],
                })

        return "(最大ツール呼び出し回数に達しました)"
