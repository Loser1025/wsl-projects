#!/usr/bin/env python3
"""
ターミナルカラーサンプル集（文字サンプル版）
─────────────────────────────────────────────
全セクションで ████████ ではなく "サンプル" という文字を背景色の上に表示することで、
実際にその色の上にどう文字が読めるかがわかります。

セクション構成:
  1. 基本 16 色       — 各色の上に "Aaあ" を表示
  2. 256 色パレット    — 各コードの上に "ID:nnn" を表示
  3. グレースケールバー — 色の上に "R=G=B=nnn" を表示
  4. HSV レインボー    — 各ブロックの上に連番数字を表示
  5. HSL バリエーション — 彩度変化・明度変化・各色相リング
  6. RGB 面チャート    — RGB 各面に座標値を表示
  7. 表示スタイル一覧  — 文字装飾 + 見本文章
  8. おすすめテーマ    — ダーク/ライト別の見やすい組み合わせ
  9. 256 色一覧        — 各色 ID をその色の上に表示
─────────────────────────────────────────────
実行: python3 color_samples.py
"""

import sys, math

# ─────────────── 小ヘルパー ───────────────
def esc(*codes: int) -> str:
    return f"\033[{';'.join(str(c) for c in codes)}m"

RESET   = esc(0)
BG      = lambda *c: esc(48, 2, *c)          # 24‑bit BG
FG      = lambda *c: esc(38, 2, *c)          # 24‑bit FG
BG8     = lambda n: esc(48, 5, n)            # 8‑bit BG
FG8     = lambda n: esc(38, 5, n)            # 8‑bit FG
BOLD    = esc(1)
DIM     = esc(2)
UNDER   = esc(4)
INV     = esc(7)

BLOCK   = "████████"

def rgb(r: int, g: int, b: int) -> tuple[int, int, int]:
    return (max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)))

def luma(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b          # ITU‑R BT.709

def fg_for_bg(r: int, g: int, b: int) -> tuple[int, int, int]:
    """背景に対するコントラストの高い文字色を返す"""
    return (0, 0, 0) if luma(r, g, b) > 128 else (255, 255, 255)

def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    h = h % 360
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if   h < 60:   r1, g1, b1 = c, x, 0
    elif h < 120:  r1, g1, b1 = x, c, 0
    elif h < 180:  r1, g1, b1 = 0, c, x
    elif h < 240:  r1, g1, b1 = 0, x, c
    elif h < 300:  r1, g1, b1 = x, 0, c
    else:          r1, g1, b1 = c, 0, x
    return rgb(int((r1 + m) * 255), int((g1 + m) * 255), int((b1 + m) * 255))

def hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    h = h % 360
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if   h < 60:   r1, g1, b1 = c, x, 0
    elif h < 120:  r1, g1, b1 = x, c, 0
    elif h < 180:  r1, g1, b1 = 0, c, x
    elif h < 240:  r1, g1, b1 = 0, x, c
    elif h < 300:  r1, g1, b1 = x, 0, c
    else:          r1, g1, b1 = c, 0, x
    return rgb(int((r1 + m) * 255), int((g1 + m) * 255), int((b1 + m) * 255))


def ANSIRGB_256(idx: int) -> tuple[int, int, int]:
    """256 色コード (0‑255) → おおよその (R,G,B)（ANSI準拠の概算値）"""
    if idx < 16:
        base = [
            (0,0,0),       (205,0,0),     (0,205,0),     (205,205,0),
            (0,0,238),     (205,0,205),   (0,205,205),   (229,229,229),
            (127,127,127), (255,0,0),     (0,255,0),     (255,255,0),
            (92,92,255),   (255,0,255),   (0,255,255),   (255,255,255),
        ]
        return base[idx]
    if idx < 232:
        n = idx - 16
        return (
            [0, 95, 135, 175, 215, 255][n // 36],
            [0, 95, 135, 175, 215, 255][(n % 36) // 6],
            [0, 95, 135, 175, 215, 255][n % 6],
        )
    v = 8 + (idx - 232) * 10
    return (v, v, v)


# ═══════════════════════════════════════════
# 1. 基本 16 色（文字つき）
# ═══════════════════════════════════════════
def section_basic_16():
    names = [
        "黒", "暗赤", "暗緑", "暗黄",
        "暗青", "暗紫", "暗水色", "明灰",
        "暗灰", "赤", "緑", "黄",
        "青", "紫", "水色", "白",
    ]
    print(f"{BOLD}{UNDER}▶ 1. 基本 16 色（文字 "Aaあ" を背景に重ね表示）{RESET}\n")
    # 各色に文字を描画: 背景=その色、文字色=コントラスト調整
    for i, name in enumerate(names):
        if i == 8:
            print()
        # ANSI 16色の RGB 値
        r, g, b = ANSIRGB_256(i)
        fg = fg_for_bg(r, g, b)
        label = f" {name:>4} Aaあ "
        sys.stdout.write(f"{BG(r,g,b)}{FG(*fg)}{label}{RESET}")
    print("\n")


# ═══════════════════════════════════════════
# 2. 256 色パレット（文字つき）
# ═══════════════════════════════════════════
def section_256_palette():
    print(f"{BOLD}{UNDER}▶ 2. 256 色パレット（ID をその背景色に重ね表示）{RESET}\n")

    # (a) 基本 16 (0–15)
    print(f"  {BOLD}[0–15] 基本色{RESET}")
    for row in range(2):
        line = "    "
        for _ in range(8):
            idx = row * 8 + _
            r, g, b = ANSIRGB_256(idx)
            fg = fg_for_bg(r, g, b)
            line += f"{BG(r,g,b)}{FG(*fg)} ID:{idx:>3} {RESET}"
        print(line)
    print()

    # (b) 216色 RGB立方体 (16–231)
    print(f"  {BOLD}[16–231] RGB 6×6×6 立方体（Z面ごとに6×6ブロック、文字="ID"）{RESET}")
    for z in range(6):
        print(f"    R={z}")
        for y in range(6):
            line = "      "
            for x in range(6):
                idx = 16 + 36 * z + 6 * y + x
                r, g, b = ANSIRGB_256(idx)
                fg = fg_for_bg(r, g, b)
                line += f"{BG(r,g,b)}{FG(*fg)}{idx:>3}{RESET}"
            print(line)
        print()

    # (c) グレースケール (232–255)
    print(f"  {BOLD}[232–255] グレースケール{RESET}")
    line = "    "
    for idx in range(232, 256):
        r, g, b = ANSIRGB_256(idx)
        fg = fg_for_bg(r, g, b)
        if idx == 244:
            line += "\n    "
        line += f"{BG(r,g,b)}{FG(*fg)}{idx:>3}{RESET}"
    print(line + "\n")


# ═══════════════════════════════════════════
# 3. グレースケールバー（文字つき）
# ═══════════════════════════════════════════
def section_grayscale_full():
    print(f"{BOLD}{UNDER}▶ 3. グレースケール バー（文字="R=G=B=nnn"）{RESET}\n")
    for v in [0, 32, 64, 96, 128, 160, 192, 224, 255]:
        r, g, b = v, v, v
        label = f" {v:>3} "
        fg = fg_for_bg(r, g, b)
        print(f"  {BG(r,g,b)}{FG(*fg)}R=G=B={label.strip()}{RESET}")
    print()


# ═══════════════════════════════════════════
# 4. HSV レインボー（連番数字を重ね表示）
# ═══════════════════════════════════════════
def section_hsv_rainbow():
    print(f"{BOLD}{UNDER}▶ 4. HSV レインボー（H: 0→360°、各ブロックに連番数字）{RESET}\n")
    cols = 36
    line0 = "  "
    line1 = "  "
    for i in range(cols):
        h = i * 360 / cols
        r, g, b = hsv_to_rgb(h, 1.0, 1.0)
        fg = fg_for_bg(r, g, b)
        num = f"{i:>2}"
        line0 += f"{BG(r,g,b)}{FG(*fg)} {num}{RESET}"
        # 2行目は色相度数
        deg = f"{int(h//10):>2}"
        line1 += f"{BG(r,g,b)}{FG(*fg)}{deg:>2}°{RESET}"
    print(line0)
    print(line1)
    print(f"  {'0°':<10}{'60°':^10}{'120°':^10}{'180°':^10}{'240°':^10}{'300°':^10}{'360°':>10}\n")


# ═══════════════════════════════════════════
# 5. HSL バリエーション
# ═══════════════════════════════════════════
def section_hsl_variations():
    print(f"\n{BOLD}{UNDER}▶ 5. HSL バリエーション{RESET}\n")

    # (a) 彩度変化
    print(f"  {BOLD}(a) 彩度変化  H=210°, L=0.50  S: 0.0→1.0{RESET}")
    line = "    "
    for i in range(20):
        s = i / 19
        r, g, b = hsl_to_rgb(210, s, 0.5)
        fg = fg_for_bg(r, g, b)
        # S の値（少数第1位）
        label = f"{s:.1f}"
        line += f"{BG(r,g,b)}{FG(*fg)}{label:>3}{RESET}"
    print(line + "\n")

    # (b) 明度変化
    print(f"  {BOLD}(b) 明度変化  H=210°, S=1.0  L: 0.0→1.0{RESET}")
    line = "    "
    for i in range(20):
        l = i / 19
        r, g, b = hsl_to_rgb(210, 1.0, l)
        fg = fg_for_bg(r, g, b)
        label = f"{l:.1f}"
        line += f"{BG(r,g,b)}{FG(*fg)}{label:>3}{RESET}"
    print(line + "\n")

    # (c) 色相リング
    print(f"  {BOLD}(c) 色相リング  S=0.9, L=0.5（各ブロックに色相度数）{RESET}")
    for row in range(4):
        line = "    "
        for col in range(36):
            h = (row * 36 + col) * (360 / 144)
            r, g, b = hsl_to_rgb(h, 0.9, 0.5)
            fg = fg_for_bg(r, g, b)
            label = f"{int(h):>3}"
            line += f"{BG(r,g,b)}{FG(*fg)}{label}{RESET}"
        print(line)

    # (d) 見やすいパレット候補
    print(f"\n  {BOLD}(d) よく使われるカラーパレット候補（文字="H:nnn"）{RESET}")
    palettes = [
        ("Jetっぽい",     [0, 16, 32, 64, 96, 128, 160, 192, 224, 240]),
        ("Plasmaっぽい",  [0, 20, 40, 65, 95, 125, 155, 185, 210, 235]),
        ("Pastel",        [(h, 0.4, 0.7) for h in range(0, 360, 36)]),
        ("Deep",          [(h, 0.85, 0.38) for h in range(0, 360, 36)]),
        ("Neon",          [(h, 1.0, 0.5) for h in range(0, 360, 36)]),
    ]
    for name, hs in palettes:
        line = f"    {name:>14}: "
        for item in hs:
            if isinstance(item, tuple):
                h, s, l = item
                r, g, b = hsl_to_rgb(h, s, l)
            else:
                r, g, b = hsv_to_rgb(item, 1.0, 1.0)
            fg = fg_for_bg(r, g, b)
            line += f"{BG(r,g,b)}{FG(*fg)} {int(item[0] if isinstance(item, tuple) else item):>2}°{RESET}"
        print(line)
    print()


# ═══════════════════════════════════════════
# 6. RGB 面チャート（座標値表示）
# ═══════════════════════════════════════════
def section_rgb_axes():
    print(f"{BOLD}{UNDER}▶ 6. RGB 面チャート（文字=座標値 R,G,B）{RESET}\n")

    # (a) R / G / B の単軸グラデーション
    steps = 16
    for name, channel_idx, fixed in [
        ("赤のグラデーション  R: 100→255 (G=B=128)", 0, (128, 128)),
        ("緑のグラデーション  G: 100→255 (R=B=128)", 1, (128, 128)),
        ("青のグラデーション  B: 100→255 (R=G=128)", 2, (128, 128)),
    ]:
        print(f"  {BOLD}{name}{RESET}")
        line = "    "
        for i in range(steps):
            v = 100 + (255 - 100) * i // (steps - 1)
            rgb_vals = list(fixed)
            rgb_vals.insert(channel_idx, v)
            r, g, b = rgb_vals
            fg = fg_for_bg(r, g, b)
            if channel_idx == 0:
                label = f"R{v}"
            elif channel_idx == 1:
                label = f"G{v}"
            else:
                label = f"B{v}"
            line += f"{BG(r,g,b)}{FG(*fg)}{label:>5}{RESET}"
        print(line + "\n")

    # (b) 面チャート（固定 R=255 で G-B 面）
    print(f"  {BOLD}G-B 面（R=255、文字="G:g,B:b"）{RESET}")
    for gi in range(5):
        gv = 255 * gi // 4
        line = "    "
        for bi in range(5):
            bv = 255 * bi // 4
            r, g, b = 255, gv, bv
            fg = fg_for_bg(r, g, b)
            label = f"G{gv:>3}"
            line += f"{BG(r,g,b)}{FG(*fg)}{label}{RESET}"
        print(line)

    print(f"\n  {BOLD}R-B 面（G=165、文字="R:r,B:b"）{RESET}")
    for ri in range(5):
        rv = 255 * ri // 4
        line = "    "
        for bi in range(5):
            bv = 255 * bi // 4
            r, g, b = rv, 165, bv
            fg = fg_for_bg(r, g, b)
            label = f"B{bv:>3}"
            line += f"{BG(r,g,b)}{FG(*fg)}{label}{RESET}"
        print(line)

    print(f"\n  {BOLD}R-G 面（B=0、文字="R:r,G:g"）{RESET}")
    for ri in range(5):
        rv = 255 * ri // 4
        line = "    "
        for gi in range(5):
            gv = 255 * gi // 4
            r, g, b = rv, gv, 0
            fg = fg_for_bg(r, g, b)
            label = f"R{rv:>3}"
            line += f"{BG(r,g,b)}{FG(*fg)}{label}{RESET}"
        print(line + "\n")


# ═══════════════════════════════════════════
# 7. 表示スタイル一覧（文字装飾の見本）
# ═══════════════════════════════════════════
def section_text_samples():
    print(f"\n{BOLD}{UNDER}▶ 7. 文字装飾スタイル一覧 + 見本文章{RESET}\n")

    # (a) 装飾の見本
    styles = [
        ("太字",                BOLD,    (220, 20, 60)),
        ("反転",                INV,     (25, 25, 112)),
        ("下線",                UNDER,   (0, 100, 0)),
        ("薄い",                DIM,     (128, 0, 128)),
        ("通常",                "",      (255, 165, 0)),
    ]
    sample_text = " The quick brown fox jumps over the lazy dog. 12345 "
    for name, fmt_code, bg_c in styles:
        fg = fg_for_bg(*bg_c)
        fmt_str = fmt_code if fmt_code else ""
        print(f"  {fmt_str}{BG(*bg_c)}{FG(*fg)}{sample_text}{RESET}  ← {name}")

    print()

    # (b) ロードバー風（文字つき）
    print(f"  {BOLD}ロードバー風 0%→100%（背景=グラデーション、文字="Loading…n%"）:{RESET}")
    total = 24
    for progress in [0, 10, 25, 50, 75, 90, 100]:
        filled = int(total * progress / 100)
        bar = ""
        for i in range(filled):
            ratio = i / max(1, total)
            r_c = int(255 * (1 - ratio * 0.8))
            g_c = int(255 * ratio)
            b_c = 50
            fg = fg_for_bg(r_c, g_c, b_c)
            col = f"{BG(r_c, g_c, b_c)}{FG(*fg)}"
            if i == filled - 1:
                # 最後のブロックに進行率を表示
                label = f"{progress:>3}%"
            else:
                label = "░"
            bar += f"{col}{label}{RESET}"
        if filled < total:
            bar += "░" * (total - filled)
        print(f"    |{bar}|")
    print()


# ═══════════════════════════════════════════
# 8. おすすめテーマ
# ═══════════════════════════════════════════
def section_recommended():
    print(f"{BOLD}{UNDER}▶ 8. おすすめ見やすいテーマ（文字="見本文章" を重ね表示）{RESET}\n")

    dark_bgs  = [(23, 32, 42), (20, 30, 48), (30, 30, 30), (15, 20, 25), (35, 20, 30)]
    dark_fgs  = [(170, 215, 230), (120, 220, 180), (240, 200, 100), (200, 160, 250), (255, 140, 140)]
    light_bgs = [(240, 245, 250), (245, 240, 235), (250, 250, 245), (235, 245, 240), (240, 235, 245)]
    light_fgs = [(40, 55, 75), (70, 40, 30), (50, 60, 20), (70, 40, 70), (90, 50, 30)]

    sample = "  Hello, World! こんにちは 0123456789  "

    print(f"  {BOLD}ダークモード:{RESET}")
    for bg_c, fg_c in zip(dark_bgs, dark_fgs):
        print(f"    {BG(*bg_c)}{FG(*fg_c)}{sample}{RESET}  ← 背景#{bg_c[0]:02X}{bg_c[1]:02X}{bg_c[2]:02X} 文字#{fg_c[0]:02X}{fg_c[1]:02X}{fg_c[2]:02X}")

    print(f"\n  {BOLD}ライトモード:{RESET}")
    for bg_c, fg_c in zip(light_bgs, light_fgs):
        print(f"    {BG(*bg_c)}{FG(*fg_c)}{sample}{RESET}  ← 背景#{bg_c[0]:02X}{bg_c[1]:02X}{bg_c[2]:02X} 文字#{fg_c[0]:02X}{fg_c[1]:02X}{fg_c[2]:02X}")
    print()


# ═══════════════════════════════════════════
# 9. 256 色一覧（各色 ID をその色に重ね表示）
# ═══════════════════════════════════════════
def section_all_256_ids():
    print(f"{BOLD}{UNDER}▶ 9. 256 色一覧（文字=ID をその色に重ねて表示）{RESET}\n")
    for i in range(256):
        r, g, b = ANSIRGB_256(i)
        fg = fg_for_bg(r, g, b)
        # 3桁IDを表示 → 幅揃えのためスペースパディング
        label = f"{i:>3}"
        end = "\n" if (i + 1) % 16 == 0 else ""
        sys.stdout.write(f"{BG(r,g,b)}{FG(*fg)}{label}{RESET}{end}")
    print()


# ═══════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════
def main():
    print(f"\n{'═' * 80}")
    print(f"  🎨 ターミナルカラーサンプル集 ver.2 — 文字サンプル版")
    print(f"  各ブロックに文字（ID / 数値 / "Aaあ" / 文章）を背景色の上に描画")
    print(f"  True Color 対応ターミナルで最も綺麗に表示されます")
    print(f"{'═' * 80}\n")

    section_basic_16()
    section_256_palette()
    section_grayscale_full()
    section_hsv_rainbow()
    section_hsl_variations()
    section_rgb_axes()
    section_text_samples()
    section_recommended()
    section_all_256_ids()

    print(f"{BOLD}{UNDER}おわり{RESET}\n")


if __name__ == "__main__":
    main()
