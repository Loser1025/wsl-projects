from __future__ import annotations

import os
import re
import sys
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
GEMINI_API_BASE     = "https://generativelanguage.googleapis.com/v1beta/openai"
MISTRAL_API_BASE    = "https://api.mistral.ai/v1"

_DEFAULT_MODEL         = "openrouter/owl-alpha"
_DEFAULT_CWD: Optional[str] = None

# ── API リトライ設定 ─────────────────────────────────────────────
MAX_RETRIES  = 5
BASE_BACKOFF = 2.0
MAX_BACKOFF  = 60.0

# ── コンテキスト管理定数 ──────────────────────────────────────────
_CHARS_PER_TOKEN   = 4       # 日本語/英語平均: 1トークン ≈ 4文字
_COMPACTION_RATIO  = 0.75    # コンテキスト容量の 75% に達したら圧縮
_COMPACTION_DEFAULT = 3_000_000  # context_length 不明時のフォールバック

# ── Gemini モデルのコンテキスト長（既知テーブル）────────────────────────
_GEMINI_CONTEXT_LENGTHS: dict[str, int] = {
    "gemini-2.5-pro":        1_048_576,
    "gemini-2.5-flash":      1_048_576,
    "gemini-2.0-flash":      1_048_576,
    "gemini-2.0-flash-lite": 1_048_576,
    "gemini-1.5-pro":        2_097_152,
    "gemini-1.5-flash":      1_048_576,
    "gemini-1.5-flash-8b":   1_048_576,
}


def _gemini_context_length(model_id: str) -> int:
    """モデルIDからコンテキスト長を返す（既知テーブル検索、不明なら1M）。"""
    for key, val in _GEMINI_CONTEXT_LENGTHS.items():
        if key in model_id:
            return val
    return 1_048_576


# コンテキスト超過エラーを示すキーワード（プロバイダーによって表現が異なる）
_CTX_EXCEEDED_KEYWORDS = (
    "context_length", "context length", "context window",
    "token", "too long", "maximum context", "exceeds", "input too large",
    "prompt is too long", "content too large",
)


class KeyManager:
    """
    OpenRouterConfig / GoogleAIConfig 共通のキーローテーション管理。
    TokenBucket による RPM 制御 + 429 時の指数バックオフクールダウン。
    """
    _COOLDOWN_BASE = 60.0    # 429 後の基本クールダウン（秒）
    _COOLDOWN_MAX  = 600.0   # 最大クールダウン（10 分）

    def __init__(self, api_keys: list, rpm_limit: int):
        from .utils import TokenBucket
        self._keys           = api_keys
        self._rpm_limit      = rpm_limit
        self._buckets        = [TokenBucket(rpm_limit=rpm_limit, rpd_limit=0)
                                 for _ in api_keys]
        self._key_index      = 0
        self._cooldown_until = [0.0] * len(api_keys)   # time.monotonic() 基準
        self._429_count      = [0]   * len(api_keys)
        self._lock           = threading.Lock()

    def acquire(self) -> tuple:
        """
        使用するキーと待ち時間を返す。
        待ち時間 0.0 = 即使用可。> 0 = その秒数後にリトライを推奨。
        """
        with self._lock:
            now = time.monotonic()
            n = len(self._keys)
            for offset in range(n):
                idx = (self._key_index + offset) % n
                if now < self._cooldown_until[idx]:
                    continue  # 429 クールダウン中はスキップ
                ok, _ = self._buckets[idx].acquire()
                if ok:
                    self._key_index = (idx + 1) % n
                    return self._keys[idx], 0.0
            # 全キーがビジー / クールダウン中 → 最も早く使えるキーを返す
            def _ready_in(i: int) -> float:
                cd  = max(0.0, self._cooldown_until[i] - now)
                tok = self._buckets[i].wait_time()
                return max(cd, tok)
            best = min(range(n), key=_ready_in)
            return self._keys[best], _ready_in(best)

    def report_429(self, api_key: str) -> None:
        """429 を受けたキーに指数バックオフクールダウンを設定する。"""
        with self._lock:
            for i, k in enumerate(self._keys):
                if k == api_key:
                    self._429_count[i] += 1
                    # 60s → 120s → 240s → ... → 600s
                    cooldown = min(
                        self._COOLDOWN_BASE * (2 ** (self._429_count[i] - 1)),
                        self._COOLDOWN_MAX,
                    )
                    self._cooldown_until[i] = time.monotonic() + cooldown
                    self._buckets[i]._tokens = 0.0
                    return

    def report_success(self, api_key: str) -> None:
        """成功時に連続 429 カウントをリセットする。"""
        with self._lock:
            for i, k in enumerate(self._keys):
                if k == api_key:
                    self._429_count[i] = 0
                    return

    def status(self) -> list:
        """各キーの状態を返す（表示・デバッグ用）。"""
        with self._lock:
            now = time.monotonic()
            return [
                {
                    "tokens":    round(self._buckets[i].tokens_available, 2),
                    "cooldown":  round(max(0.0, self._cooldown_until[i] - now), 1),
                    "count_429": self._429_count[i],
                }
                for i in range(len(self._keys))
            ]

    def n_ready_keys(self) -> int:
        """現在すぐ使えるキー数（トークン >= 1 かつクールダウン外）を返す。"""
        now = time.monotonic()
        return sum(
            1 for i in range(len(self._keys))
            if now >= self._cooldown_until[i] and self._buckets[i].tokens_available >= 1.0
        )

    def wait_for_n_keys(self, n: int) -> float:
        """n 本のキーが使えるようになるまでの推定待ち時間（秒）を返す。"""
        n = min(n, len(self._keys))
        now = time.monotonic()
        wait_times = sorted(
            max(0.0, self._cooldown_until[i] - now, self._buckets[i].wait_time())
            for i in range(len(self._keys))
        )
        # n 番目に速いキーが準備完了するまでの時間
        return wait_times[n - 1] if wait_times else 0.0

    def total_tokens_available(self) -> float:
        """全キーのトークン残量合計を返す。"""
        return sum(b.tokens_available for b in self._buckets)


@dataclass
class OpenRouterConfig:
    api_keys: list[str]
    model: str = field(default_factory=lambda: _DEFAULT_MODEL)
    system_prompt: str = ""
    site_url: str = "https://github.com/Loser1025/mimic"
    site_name: str = "Mimic OpenRouter"
    rpm_limit: int = 3
    context_length: int = 0  # モデルのコンテキストウィンドウ（トークン数）、0=不明
    max_tokens: int = 0       # 最大出力トークン数（0=指定なし）
    _key_manager: "KeyManager" = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self._key_manager = KeyManager(self.api_keys, self.rpm_limit)

    @property
    def api_key(self) -> str:
        return self.api_keys[0] if self.api_keys else ""

    def acquire_key(self) -> tuple:
        return self._key_manager.acquire()

    def report_429(self, api_key: str) -> None:
        self._key_manager.report_429(api_key)

    def report_success(self, api_key: str) -> None:
        self._key_manager.report_success(api_key)

    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def api_base(self) -> str:
        return OPENROUTER_API_BASE

    def build_auth_headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
        }

    @property
    def thinking_level(self) -> str:
        return "NONE"

    @thinking_level.setter
    def thinking_level(self, v: str):
        pass


# ── GoogleAIConfig ────────────────────────────────────────────────

@dataclass
class GoogleAIConfig:
    api_keys: list[str]
    model: str = "gemini-2.0-flash"
    system_prompt: str = ""
    rpm_limit: int = 15
    context_length: int = 0
    max_tokens: int = 0       # 最大出力トークン数（0=指定なし）
    _key_manager: "KeyManager" = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self._key_manager = KeyManager(self.api_keys, self.rpm_limit)

    @property
    def api_key(self) -> str:
        return self.api_keys[0] if self.api_keys else ""

    def acquire_key(self) -> tuple:
        return self._key_manager.acquire()

    def report_429(self, api_key: str) -> None:
        self._key_manager.report_429(api_key)

    def report_success(self, api_key: str) -> None:
        self._key_manager.report_success(api_key)

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def api_base(self) -> str:
        return GEMINI_API_BASE

    def build_auth_headers(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}"}

    @property
    def thinking_level(self) -> str:
        return "NONE"

    @thinking_level.setter
    def thinking_level(self, v: str):
        pass


# ── MistralConfig ────────────────────────────────────────────────

@dataclass
class MistralConfig:
    api_keys: list[str]
    model: str = "mistral-small-latest"
    system_prompt: str = ""
    rpm_limit: int = 50
    context_length: int = 0
    max_tokens: int = 0
    _key_manager: "KeyManager" = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self._key_manager = KeyManager(self.api_keys, self.rpm_limit)

    @property
    def api_key(self) -> str:
        return self.api_keys[0] if self.api_keys else ""

    def acquire_key(self) -> tuple:
        return self._key_manager.acquire()

    def report_429(self, api_key: str) -> None:
        self._key_manager.report_429(api_key)

    def report_success(self, api_key: str) -> None:
        self._key_manager.report_success(api_key)

    @property
    def name(self) -> str:
        return "mistral"

    @property
    def api_base(self) -> str:
        return MISTRAL_API_BASE

    def build_auth_headers(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}"}

    @property
    def thinking_level(self) -> str:
        return "NONE"

    @thinking_level.setter
    def thinking_level(self, v: str):
        pass


# ── PortContext (orchestrator.py が使用) ────────────────────────

@dataclass(frozen=True)
class PortContext:
    cwd: Path
    py_file_count: int
    has_tests: bool
    has_config: bool
    top_files: tuple
    py_files: tuple
    cfg_files: tuple


def build_port_context(cwd: Path) -> PortContext:
    try:
        top_files = tuple(
            e.name + ("/" if e.is_dir() else "")
            for e in sorted(cwd.iterdir(), key=lambda x: (x.is_file(), x.name))[:10]
        )
    except Exception:
        top_files = ()
    try:
        py_files = tuple(f.name for f in cwd.glob("*.py"))[:5]
        cfg_files = tuple(
            f.name for f in list(cwd.glob("*.json")) + list(cwd.glob("*.env*"))
        )[:5]
        py_file_count = sum(1 for p in cwd.rglob("*.py") if p.is_file())
        has_tests = (cwd / "tests").is_dir() or any(
            f.name.startswith("test_") for f in cwd.glob("*.py")
        )
    except Exception:
        py_files = cfg_files = ()
        py_file_count = 0
        has_tests = False
    return PortContext(
        cwd=cwd,
        py_file_count=py_file_count,
        has_tests=has_tests,
        has_config=bool(cfg_files),
        top_files=top_files,
        py_files=py_files,
        cfg_files=cfg_files,
    )


def render_port_context(ctx: PortContext) -> str:
    lines = ["[実行コンテキスト]", f"作業フォルダ: {ctx.cwd}"]
    if ctx.py_file_count:
        lines.append(f"Pythonファイル数: {ctx.py_file_count}（再帰）")
    if ctx.top_files:
        lines.append(f"フォルダ内容: {', '.join(ctx.top_files)}")
    if ctx.py_files:
        lines.append(f"Pythonファイル: {', '.join(ctx.py_files)}")
    if ctx.cfg_files:
        lines.append(f"設定ファイル: {', '.join(ctx.cfg_files)}")
    if ctx.has_tests:
        lines.append("テスト: あり（tests/ または test_*.py）")
    return "\n".join(lines)


# ── 無料モデル取得・選択 ─────────────────────────────────────────

def fetch_free_models(api_key: str) -> list[dict]:
    """OpenRouter API から無料モデル一覧を取得して返す。"""
    import urllib.request
    import json

    url = f"{OPENROUTER_API_BASE}/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ⚠ モデル一覧の取得に失敗しました: {e}")
        return []

    models = data.get("data", [])
    free_models = [
        m for m in models
        if (
            str(m.get("pricing", {}).get("prompt", "1")) == "0"
            and str(m.get("pricing", {}).get("completion", "1")) == "0"
        ) or m.get("id", "").endswith(":free")
    ]
    free_models.sort(key=lambda m: m.get("name", m.get("id", "")))
    return free_models


def _test_model(
    api_key: str,
    model_id: str,
    base_url: str = OPENROUTER_API_BASE,
) -> tuple[bool, float]:
    """モデルに最小リクエストを送り (成功フラグ, 応答時間秒) を返す。"""
    import urllib.request
    import json
    import time

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if "error" in data:
            return False, 0.0
        return True, time.time() - t0
    except Exception:
        return False, 0.0


def fetch_gemini_models(api_key: str) -> list[dict]:
    """Google AI Studio から利用可能モデル一覧を取得して返す。"""
    import urllib.request
    import json

    url = f"{GEMINI_API_BASE}/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ⚠ Geminiモデル一覧の取得に失敗しました: {e}")
        return []

    models = data.get("data", [])
    result = []
    for m in models:
        mid = m.get("id", "")
        if not mid:
            continue
        ml = mid.lower()
        if "gemini" not in ml and "gemma" not in ml:
            continue
        ctx = _gemini_context_length(mid)
        result.append({"id": mid, "context_length": ctx, "name": mid})
    result.sort(key=lambda m: m.get("id", ""))
    return result


def fetch_mistral_models(api_key: str) -> list[dict]:
    """Mistral AI から利用可能モデル一覧を取得して返す。"""
    import urllib.request
    import json

    url = f"{MISTRAL_API_BASE}/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  ⚠ Mistralモデル一覧の取得に失敗しました: {e}")
        return []

    models = data.get("data", [])
    result = []
    for m in models:
        mid = m.get("id", "")
        if not mid:
            continue
        ctx = m.get("max_context_length", 0) or 0
        result.append({"id": mid, "context_length": ctx, "name": m.get("name", mid)})
    result.sort(key=lambda m: m.get("id", ""))
    return result


def select_model_interactively_multi(
    or_config: Optional["OpenRouterConfig"],
    gemini_config: Optional["GoogleAIConfig"],
    mistral_config: Optional["MistralConfig"] = None,
) -> "OpenRouterConfig | GoogleAIConfig | MistralConfig":
    """
    OpenRouter / Gemini / Mistral のモデルを並列取得・疎通テストし、
    番号選択で使用モデルとプロバイダーを確定する。
    選択された config（model / context_length 更新済み）を返す。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # ── ANSI カラー ──────────────────────────────────────────────
    _RG  = "\033[38;2;0;255;65m"    # Razer Neon Green  #00FF41
    _RGD = "\033[38;2;0;160;45m"    # Deep Green        #00A02D
    _WHT = "\033[38;2;255;255;255m" # Pure White        #FFFFFF
    _GRY = "\033[38;2;0;200;100m"   # Medium Green      #00C864
    _CYN = "\033[38;2;0;240;200m"   # Bright Cyan-Green #00F0C8
    _YLW = "\033[38;2;255;230;0m"   # Neon Yellow       #FFE600
    _MEM = "\033[38;2;0;200;220m"   # Cyan              #00C8DC
    _ORG = "\033[38;2;0;255;65m"    # = Razer Green
    _BLD = "\033[1m"
    _RST = "\033[0m"

    def g(s):  return f"{_RG}{s}{_RST}"
    def gd(s): return f"{_RGD}{s}{_RST}"
    def w(s):  return f"{_WHT}{s}{_RST}"
    def cy(s): return f"{_CYN}{s}{_RST}"
    def y(s):  return f"{_YLW}{s}{_RST}"
    def mm(s): return f"{_MEM}{s}{_RST}"
    def gr(s): return f"{_GRY}{s}{_RST}"
    def gm(s): return f"{_ORG}{s}{_RST}"
    def bg(s): return f"{_BLD}{_RG}{s}{_RST}"
    def bw(s): return f"{_BLD}{_WHT}{s}{_RST}"
    def bm(s): return f"{_BLD}{_ORG}{s}{_RST}"

    # ── ヘッダー ─────────────────────────────────────────────────
    BW = 76
    print()
    print(gd("  ╔" + "═" * BW + "╗"))
    title = "  MULTI-PROVIDER MODEL SELECTOR  ·  LIVE API HEALTH CHECK  "
    print(f"{gd('  ║')}{_BLD}{_RG}{title}{_RST}{' ' * max(0, BW - len(title))}{gd('║')}")
    print(gd("  ╚" + "═" * BW + "╝"))
    print()

    # ── フェーズ1: モデル一覧を並列取得 ─────────────────────────
    print(f"  {gr('⟳')}  モデル一覧を取得中...", end="", flush=True)
    or_models: list[dict] = []
    gemini_models: list[dict] = []
    mistral_models: list[dict] = []

    with ThreadPoolExecutor(max_workers=3) as ex:
        or_fut      = ex.submit(fetch_free_models,    or_config.api_keys[0])      if or_config      else None
        gemini_fut  = ex.submit(fetch_gemini_models,  gemini_config.api_keys[0])  if gemini_config  else None
        mistral_fut = ex.submit(fetch_mistral_models, mistral_config.api_keys[0]) if mistral_config else None
        if or_fut:
            or_models = or_fut.result()
        if gemini_fut:
            gemini_models = gemini_fut.result()
        if mistral_fut:
            mistral_models = mistral_fut.result()

    parts = []
    if or_config:
        parts.append(f"{g('OpenRouter')}: {w(str(len(or_models)))} 件の無料モデル")
    if gemini_config:
        parts.append(f"{gm('Gemini')}: {w(str(len(gemini_models)))} 件のモデル")
    if mistral_config:
        parts.append(f"{cy('Mistral')}: {w(str(len(mistral_models)))} 件のモデル")
    print(f"\r  {g('✓')}  {'  /  '.join(parts)}{' ' * 20}")
    print()

    all_entries = (
        [("or",      m) for m in or_models] +
        [("gemini",  m) for m in gemini_models] +
        [("mistral", m) for m in mistral_models]
    )
    total = len(all_entries)
    _fallback = or_config or gemini_config or mistral_config  # type: ignore[assignment]

    if total == 0:
        print(f"  {y('⚠')}  モデル一覧の取得に失敗しました。現在の設定を使用します。\n")
        return _fallback

    # ── フェーズ2: 疎通確認（並列、エンターで途中終了可）──────────
    import select as _select
    from concurrent.futures import wait as _fut_wait, FIRST_COMPLETED

    print(f"  {gr('疎通確認中...')}  {y('← エンターキーで現時点の結果を表示')}\n")
    results: dict[str, tuple[bool, float]] = {}
    tested_n = [0]
    lock = threading.Lock()
    BAR = 34
    stop_testing = threading.Event()

    def _test_entry(entry: tuple) -> None:
        if stop_testing.is_set():
            return
        provider, mdl = entry
        mid = mdl["id"]
        if provider == "or" and or_config:
            ok, elapsed = _test_model(or_config.api_keys[0], mid, OPENROUTER_API_BASE)
        elif provider == "gemini" and gemini_config:
            ok, elapsed = _test_model(gemini_config.api_keys[0], mid, GEMINI_API_BASE)
        elif provider == "mistral" and mistral_config:
            ok, elapsed = _test_model(mistral_config.api_keys[0], mid, MISTRAL_API_BASE)
        else:
            ok, elapsed = False, 0.0
        if stop_testing.is_set():
            return
        key = f"{provider}:{mid}"
        with lock:
            results[key] = (ok, elapsed)
            tested_n[0] += 1
            n = tested_n[0]
            filled = int(BAR * n / total)
            bar = f"{_RG}{'█' * filled}{_GRY}{'░' * (BAR - filled)}{_RST}"
            tw = len(str(total))
            print(
                f"\r  [{bar}]  {w(str(n).rjust(tw))}/{total}"
                f"  {gr(str(int(100 * n / total)).rjust(3) + '%')}",
                end="", flush=True,
            )

    ex = ThreadPoolExecutor(max_workers=10)
    pending = {ex.submit(_test_entry, e) for e in all_entries}
    try:
        while pending and not stop_testing.is_set():
            done, pending = _fut_wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for f in done:
                try:
                    f.result()
                except Exception:
                    pass
            # エンター押下を非ブロッキングで検知（select timeout=0）
            if _select.select([sys.stdin], [], [], 0)[0]:
                sys.stdin.readline()
                stop_testing.set()
    finally:
        stop_testing.set()
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)
    print(f"\r{' ' * 80}\r", end="", flush=True)

    working = sorted(
        [
            (prov, mdl, results[f"{prov}:{mdl['id']}"][1])
            for prov, mdl in all_entries
            if results.get(f"{prov}:{mdl['id']}", (False,))[0]
        ],
        key=lambda x: x[2],
    )

    if not working:
        print(f"  {y('⚠')}  疎通できたモデルがありませんでした。現在の設定を使用します。\n")
        return _fallback

    # ── フェーズ3: 結果テーブル ──────────────────────────────────
    CN, CPROV, CID, CLAT, CCTX = 4, 4, 42, 7, 9

    def ctx_fmt(ctx: int) -> str:
        if not ctx:          return "─"
        if ctx >= 1_000_000: return f"{ctx // 1_000_000}M"
        if ctx >= 1_000:     return f"{ctx // 1_000}K"
        return str(ctx)

    def lat_col(e: float, rank: int) -> str:
        s = f"{e:.1f}s".center(CLAT)
        if rank == 0:  return f"{_BLD}{_RG}{s}{_RST}"
        if e < 3.0:    return f"{_CYN}{s}{_RST}"
        if e < 8.0:    return f"{_YLW}{s}{_RST}"
        return f"{_GRY}{s}{_RST}"

    def prov_badge(provider: str) -> str:
        if provider == "or":
            return f"{_RG}{'OR'.center(CPROV)}{_RST}"
        if provider == "mistral":
            return f"{_CYN}{'MI'.center(CPROV)}{_RST}"
        return f"{_ORG}{'GM'.center(CPROV)}{_RST}"

    EQ = "═"
    def hline(lc: str, rc: str, jc: str) -> str:
        return gd(
            lc + EQ*(CN+2) + jc + EQ*(CPROV+2) + jc
               + EQ*(CID+2) + jc + EQ*(CLAT+2) + jc + EQ*(CCTX+2) + rc
        )

    V = gd("║")
    or_cur      = or_config.model      if or_config      else ""
    gemini_cur  = gemini_config.model  if gemini_config  else ""
    mistral_cur = mistral_config.model if mistral_config else ""

    print(f"  {bw(str(len(working)))} 件が稼働中  {gr('/')}  {gr(str(total) + ' 件取得')}\n")
    print(hline("╔", "╗", "╦"))
    print(
        f"{V} {bw('No.'.center(CN))} {V} {bw('Pv'.center(CPROV))} {V}"
        f" {bw('Model ID'.ljust(CID))} {V} {bw('Latency'.center(CLAT))} {V}"
        f" {bw('Context'.center(CCTX))} {V}"
    )
    print(hline("╠", "╣", "╬"))

    for i, (provider, mdl, elapsed) in enumerate(working, 1):
        mid    = mdl.get("id", "")
        ctx    = mdl.get("context_length", 0)
        is_cur = (provider == "or"      and mid == or_cur)      or \
                 (provider == "gemini"  and mid == gemini_cur)  or \
                 (provider == "mistral" and mid == mistral_cur)
        is_top = i == 1

        no_p  = str(i).center(CN)
        id_p  = mid[:CID].ljust(CID)
        lat_d = lat_col(elapsed, i - 1)
        ctx_d = mm(ctx_fmt(ctx).rjust(CCTX))
        pv_d  = prov_badge(provider)

        if is_top and is_cur:
            no_d, id_d, tag = bg(no_p), bg(id_p), f"  {bg('★ FASTEST · CURRENT')}"
        elif is_top:
            no_d, id_d, tag = bg(no_p), bg(id_p), f"  {bg('★ FASTEST')}"
        elif is_cur:
            nc = cy if provider == "mistral" else (gm if provider == "gemini" else cy)
            no_d, id_d, tag = nc(no_p), nc(id_p), f"  {nc('← CURRENT')}"
        else:
            no_d, id_d, tag = gr(no_p), w(id_p), ""

        print(f"{V} {no_d} {V} {pv_d} {V} {id_d} {V} {lat_d} {V} {ctx_d} {V}{tag}")

    print(hline("╚", "╝", "╩"))

    active_providers = sum([bool(or_config), bool(gemini_config), bool(mistral_config)])
    if active_providers > 1:
        legend_parts = []
        if or_config:      legend_parts.append(f"{g('OR')} = OpenRouter")
        if gemini_config:  legend_parts.append(f"{gm('GM')} = Google AI Studio")
        if mistral_config: legend_parts.append(f"{cy('MI')} = Mistral AI")
        print(f"\n  凡例: {'  '.join(legend_parts)}\n")

    cancel_parts = []
    if or_config:
        cancel_parts.append(f"{g('OR')} {y(or_config.model)}")
    if gemini_config:
        cancel_parts.append(f"{gm('GM')} {y(gemini_config.model)}")
    if mistral_config:
        cancel_parts.append(f"{cy('MI')} {y(mistral_config.model)}")
    print(f"  {gd('[ 0 ]')}  {gr('キャンセル')}  {gr('·')}  {gr('現在:')}  {'  /  '.join(cancel_parts)}\n")

    _ansi_re = re.compile(r'\033\[[^m]*m')
    while True:
        try:
            raw = input(_ansi_re.sub(r'\001\g<0>\002', f"  {g('▸')}  番号を入力  {gd('›')}  ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return _fallback
        if raw in ("", "0"):
            return _fallback
        try:
            n = int(raw)
        except ValueError:
            print(f"  {y('⚠')}  数字を入力してください（0〜{len(working)}）。")
            continue
        if 1 <= n <= len(working):
            provider, sel_mdl, _ = working[n - 1]
            sel_id  = sel_mdl["id"]
            sel_ctx = sel_mdl.get("context_length", 0)
            if provider == "or" and or_config:
                or_config.model          = sel_id
                or_config.context_length = sel_ctx
                print(f"\n  {bg('✓')}  {w('選択:')}  {g('[OR]')} {g(sel_id)}\n")
                return or_config
            elif provider == "gemini" and gemini_config:
                gemini_config.model          = sel_id
                gemini_config.context_length = sel_ctx
                print(f"\n  {bm('✓')}  {w('選択:')}  {gm('[GM]')} {gm(sel_id)}\n")
                return gemini_config
            elif provider == "mistral" and mistral_config:
                mistral_config.model          = sel_id
                mistral_config.context_length = sel_ctx
                print(f"\n  {cy('✓')}  {w('選択:')}  {cy('[MI]')} {cy(sel_id)}\n")
                return mistral_config
        print(f"  {y('⚠')}  1〜{len(working)} の番号を入力してください。")


# ── .env パーサー ────────────────────────────────────────────────

def _parse_env_file(env_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or \
           (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        result[key] = val
    return result


def _generate_env_template(env_path: Path):
    template = (
        "# =====================================================\n"
        "# Mimic3 設定ファイル\n"
        "# =====================================================\n\n"
        "# ── Actor: OpenRouter (https://openrouter.ai/keys)\n"
        "# OPENROUTER_KEY_1=YOUR_OPENROUTER_KEY_1\n"
        "# OPENROUTER_KEY_2=YOUR_OPENROUTER_KEY_2\n"
        "# OPENROUTER_KEY_3=YOUR_OPENROUTER_KEY_3\n"
        "# OPENROUTER_MODEL=openrouter/owl-alpha\n\n"
        "# ── Actor: Google AI Studio (https://aistudio.google.com/apikey)\n"
        "# GEMINI_KEY_1=YOUR_GEMINI_KEY_1\n"
        "# GEMINI_KEY_2=YOUR_GEMINI_KEY_2\n"
        "# GEMINI_KEY_3=YOUR_GEMINI_KEY_3\n"
        "# GEMINI_MODEL=gemini-2.0-flash\n"
        "# RPM_LIMIT_GEMINI=15\n\n"
        "# ── 共通設定 ──\n"
        "# どちらか一方（または両方）のキーを設定してください\n"
        "RPM_LIMIT=20\n\n"
        "# システムプロンプト\n"
        "SYSTEM_PROMPT=あなたは有能なAIアシスタントです。日本語で丁寧に回答してください。\n"
    )
    env_path.write_text(template, encoding="utf-8")


def load_config(
    base_dir: Optional[str] = None,
) -> tuple[Optional["OpenRouterConfig"], Optional["GoogleAIConfig"], str]:
    """(or_config, gemini_config, system_prompt) を返す。未設定のプロバイダーは None。"""
    search_dir = Path(base_dir) if base_dir else Path(__file__).parent
    env_path = search_dir / ".env"

    if env_path.exists():
        env = _parse_env_file(env_path)

        global _DEFAULT_MODEL, _DEFAULT_CWD
        _DEFAULT_CWD = os.environ.get("MIMIC_CWD") or env.get("DEFAULT_CWD", None)

        system_prompt = env.get("SYSTEM_PROMPT", "")
        rpm_limit     = int(env.get("RPM_LIMIT", "3"))
        max_tokens    = int(env.get("MAX_TOKENS", "0"))

        # ── OpenRouter ─────────────────────────────────────────
        or_keys: list[str] = []
        for i in range(1, 10):
            k = env.get(f"OPENROUTER_KEY_{i}", "")
            if k and not k.startswith("YOUR_"):
                or_keys.append(k)
        if not or_keys:
            k = env.get("OPENROUTER_KEY", "")
            if k and not k.startswith("YOUR_"):
                or_keys.append(k)

        or_config: Optional[OpenRouterConfig] = None
        if or_keys:
            or_model = env.get("OPENROUTER_MODEL", _DEFAULT_MODEL)
            _DEFAULT_MODEL = or_model
            or_config = OpenRouterConfig(
                api_keys=or_keys, model=or_model,
                system_prompt=system_prompt, rpm_limit=rpm_limit,
                max_tokens=max_tokens,
            )

        # ── Google AI Studio ───────────────────────────────────
        gemini_keys: list[str] = []
        for i in range(1, 10):
            k = env.get(f"GEMINI_KEY_{i}", "")
            if k and not k.startswith("YOUR_"):
                gemini_keys.append(k)
        if not gemini_keys:
            k = env.get("GEMINI_KEY", "")
            if k and not k.startswith("YOUR_"):
                gemini_keys.append(k)

        gemini_config: Optional[GoogleAIConfig] = None
        if gemini_keys:
            gemini_model = env.get("GEMINI_MODEL", "gemini-2.0-flash")
            gemini_rpm   = int(env.get("RPM_LIMIT_GEMINI", str(rpm_limit)))
            gemini_config = GoogleAIConfig(
                api_keys=gemini_keys, model=gemini_model,
                system_prompt=system_prompt, rpm_limit=gemini_rpm,
                max_tokens=max_tokens,
            )

        # ── Mistral AI ─────────────────────────────────────────
        mistral_keys: list[str] = []
        for i in range(1, 10):
            k = env.get(f"MISTRAL_KEY_{i}", "")
            if k and not k.startswith("YOUR_"):
                mistral_keys.append(k)
        if not mistral_keys:
            k = env.get("MISTRAL_KEY", "")
            if k and not k.startswith("YOUR_"):
                mistral_keys.append(k)

        mistral_config: Optional[MistralConfig] = None
        if mistral_keys:
            mistral_model = env.get("MISTRAL_MODEL", "mistral-small-latest")
            mistral_rpm   = int(env.get("RPM_LIMIT_MISTRAL", "50"))
            mistral_config = MistralConfig(
                api_keys=mistral_keys, model=mistral_model,
                system_prompt=system_prompt, rpm_limit=mistral_rpm,
                max_tokens=max_tokens,
            )

        if not or_config and not gemini_config and not mistral_config:
            print("[エラー] .env に有効な OPENROUTER_KEY / GEMINI_KEY / MISTRAL_KEY が見つかりません。")
            sys.exit(1)

        return or_config, gemini_config, mistral_config, system_prompt

    _generate_env_template(env_path)
    print("=" * 55)
    print("  設定ファイルを生成しました。")
    print(f"  場所: {env_path}")
    print("  APIキーを設定してから再実行してください。")
    print("=" * 55)
    sys.exit(0)
