"""
tools_image.py — 画像生成ツール群(Pollinations.ai写真 + Pillowテキストオーバーレイ)
@tools.register() で既存registryに登録。「sns-hybrid-image」スキルで確立した手法を
エージェント本体のツールとして提供する(写真取得→テキスト合成→保存の一連を関数化)。
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .tools import tools

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None  # type: ignore

_POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"
_IMAGE_DIR = Path(__file__).parent / "data" / "generated_images"

# WSL環境からWindows側の日本語フォントを利用する。無ければPillowの標準フォントにフォールバック。
_FONT_BOLD = "/mnt/c/Windows/Fonts/YuGothB.ttc"
_FONT_REG = "/mnt/c/Windows/Fonts/YuGothR.ttc"

_ACCENT = (255, 200, 87)
_NAVY = (10, 22, 40)
_NAVY2 = (26, 46, 74)


def _ensure_dir() -> None:
    _IMAGE_DIR.mkdir(parents=True, exist_ok=True)


@tools.register(
    name="generate_background_photo",
    description=(
        "Pollinations.ai(無料・APIキー不要)でプロンプトから背景写真を生成し、ファイルに保存する。"
        "SNS投稿画像の背景素材として使う。匿名利用は同時1リクエストまでの制限があるため、"
        "連続で複数枚生成する場合は前回呼び出しから15秒以上間隔を空けること。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "画像生成プロンプト(英語推奨。具体的な情景・光・構図を描写する)"},
            "filename": {"type": "string", "description": "保存ファイル名(例: photo_forest.jpg)"},
            "width": {"type": "integer", "description": "画像幅(デフォルト1080)"},
            "height": {"type": "integer", "description": "画像高さ(デフォルト1350)"},
            "seed": {"type": "integer", "description": "同じ構図を再現したい場合のシード値(省略可)"},
        },
        "required": ["prompt", "filename"],
    },
)
def generate_background_photo(
    prompt: str, filename: str, width: int = 1080, height: int = 1350, seed: int | None = None
) -> str:
    _ensure_dir()
    out_path = _IMAGE_DIR / filename

    params = {"width": str(width), "height": str(height), "nologo": "true"}
    if seed is not None:
        params["seed"] = str(seed)
    url = f"{_POLLINATIONS_BASE}/{urllib.parse.quote(prompt)}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mimic_sns"})
        with urllib.request.urlopen(req, timeout=40) as res:
            data = res.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return f"画像生成エラー(HTTP {e.code}): {body[:300]}"
    except urllib.error.URLError as e:
        return f"ネットワークエラー: {e.reason}"

    if data[:1] == b"{":
        # レート制限等でJSONエラーが返ってきたケース
        return f"画像生成エラー(JSON応答): {data.decode('utf-8', errors='replace')[:300]}"

    out_path.write_bytes(data)
    return str(out_path)


def _vertical_gradient(w: int, h: int, top: tuple, bottom: tuple):
    img = Image.new("RGB", (w, h), top)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img


def _draw_wrapped(draw, text: str, font, fill, x: float, y: float, max_width: float, line_spacing: float = 1.3) -> float:
    lines = []
    for raw_line in text.split("\n"):
        if not raw_line:
            lines.append("")
            continue
        cur = ""
        for ch in raw_line:
            test = cur + ch
            if draw.textlength(test, font=font) > max_width and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        lines.append(cur)
    line_h = font.size * line_spacing
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_h), line, font=font, fill=fill)
    return y + len(lines) * line_h


def _load_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default(size=size)


@tools.register(
    name="generate_text_card",
    description=(
        "テキストを合成したSNS投稿画像/LINEカード画像を生成する。photo_pathを指定すると"
        "写真+テキストオーバーレイのハイブリッド版(グラデーション暗幕付き)になり、省略すると"
        "ネイビー系グラデーション単色のシンプルカードになる(LINEの選択肢カード等に向く)。"
        "本文とフッターが重ならないよう、フッター指定時は自動で帯を確保する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "アクセントカラーの小見出し(例: 認知科学コーチング)"},
            "headline": {"type": "string", "description": "見出し。\\nで改行指定可(省略すると自動折り返し)"},
            "filename": {"type": "string", "description": "保存ファイル名(例: card_001.png)"},
            "body": {"type": "string", "description": "本文(省略可)"},
            "footer": {"type": "string", "description": "フッター(省略可。指定時のみ下部に帯を確保)"},
            "photo_path": {"type": "string", "description": "背景写真のパス(省略するとネイビー単色グラデーション)"},
            "width": {"type": "integer", "description": "画像幅(デフォルト1080。LINEカードは1024推奨)"},
            "height": {"type": "integer", "description": "画像高さ(デフォルト1350。LINEカードは1024推奨、Note見出しは670)"},
            "gradient": {"type": "string", "description": "写真使用時の暗幕方向: bottom(既定)/top/full"},
            "center_headline": {"type": "boolean", "description": "見出しを中央揃え・中央配置にする(LINEカード等の短いラベル向け。既定はfalse=左寄せ下部配置)"},
        },
        "required": ["label", "headline", "filename"],
    },
)
def generate_text_card(
    label: str,
    headline: str,
    filename: str,
    body: str | None = None,
    footer: str | None = None,
    photo_path: str | None = None,
    width: int = 1080,
    height: int = 1350,
    gradient: str = "bottom",
    center_headline: bool = False,
) -> str:
    if Image is None:
        return "Pillowがインストールされていません。仮想環境で `pip install Pillow` を実行してください。"

    _ensure_dir()
    out_path = _IMAGE_DIR / filename
    W, H = width, height

    if photo_path:
        try:
            base = Image.open(photo_path).convert("RGB")
        except (FileNotFoundError, OSError) as e:
            return f"背景写真を開けませんでした: {e}"
        src_w, src_h = base.size
        target_ratio = W / H
        src_ratio = src_w / src_h
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            offset = (src_w - new_w) // 2
            base = base.crop((offset, 0, offset + new_w, src_h))
        else:
            new_h = int(src_w / target_ratio)
            offset = (src_h - new_h) // 2
            base = base.crop((0, offset, src_w, offset + new_h))
        base = base.resize((W, H), Image.LANCZOS)

        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        for y in range(H):
            if gradient == "top":
                t = max(0, 1 - (y / (H * 0.55)))
            elif gradient == "full":
                t = 0.55
            else:
                t = max(0, (y - H * 0.28) / (H * 0.72))
            alpha = int(238 * min(1, t ** 1.25))
            odraw.line([(0, y), (W, y)], fill=(6, 6, 8, alpha))
        img = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    else:
        img = _vertical_gradient(W, H, _NAVY, _NAVY2)

    draw = ImageDraw.Draw(img)
    font_label = _load_font(_FONT_BOLD, max(24, int(W * 0.030)))
    font_headline = _load_font(_FONT_BOLD, max(40, int(W * 0.052)))
    font_body = _load_font(_FONT_REG, max(22, int(W * 0.028)))
    font_footer = _load_font(_FONT_REG, max(20, int(W * 0.024)))

    if center_headline:
        # LINEカード等:中央揃え・中央配置のシンプルレイアウト
        bar_w = int(W * 0.06)
        draw.rectangle([(W / 2 - bar_w / 2, H * 0.09), (W / 2 + bar_w / 2, H * 0.09 + 6)], fill=_ACCENT)
        lw = draw.textlength(label, font=font_label)
        draw.text(((W - lw) / 2, H * 0.13), label, font=font_label, fill=_ACCENT)

        headline_lines = headline.split("\n")
        line_h = font_headline.size * 1.28
        total_h = len(headline_lines) * line_h
        y = H / 2 - total_h / 2
        for line in headline_lines:
            lw = draw.textlength(line, font=font_headline)
            draw.text(((W - lw) / 2, y), line, font=font_headline, fill=(255, 255, 255))
            y += line_h

        if body:
            body_lines = body.split("\n")
            by = y + 30
            for line in body_lines:
                lw = draw.textlength(line, font=font_body)
                draw.text(((W - lw) / 2, by), line, font=font_body, fill=(222, 222, 222))
                by += font_body.size * 1.3
    else:
        # SNS投稿等:左寄せ・下部配置。フッター指定時は帯を先に確保して重なりを防ぐ
        pad_x = int(W * 0.093)
        if footer:
            footer_y = H - int(H * 0.056)
            scrim_top = footer_y - int(H * 0.03)
            sdraw = ImageDraw.Draw(img, "RGBA")
            sdraw.rectangle([(0, scrim_top), (W, H)], fill=(4, 4, 6, 170))
            text_bottom_limit = scrim_top - int(H * 0.03)
        else:
            text_bottom_limit = H - int(H * 0.052)

        headline_lines = headline.count("\n") + 1
        body_lines = (body.count("\n") + 2) if body else 0
        block_h = (font_label.size + 24) + headline_lines * font_headline.size * 1.24 + \
                  ((30 + body_lines * font_body.size * 1.3) if body else 0)

        y0 = min(H * 0.65, text_bottom_limit - block_h)

        draw.text((pad_x, y0), label, font=font_label, fill=_ACCENT)
        y = _draw_wrapped(draw, headline, font_headline, (255, 255, 255), pad_x, y0 + font_label.size + 24, W - pad_x * 2, 1.24)
        if body:
            _draw_wrapped(draw, body, font_body, (222, 222, 222), pad_x, y + 26, W - pad_x * 2 - 20)
        if footer:
            draw.text((pad_x, footer_y), footer, font=font_footer, fill=(220, 220, 220))

    img.save(out_path)
    return str(out_path)
