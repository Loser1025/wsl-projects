#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ターミナルカラーサンプル集（文字サンプル版）
==============================================
全セクションで 色ブロック に 文字 を重ね表示することで、
実際にその色の上にどう文字が読めるかがわかります。

セクション構成:
  1. 基本 16 色       - 「名前 Aaあ1」を背景色の上に表示
  2. 256 色パレット    - 各コードに「ID:nnn」を背景に重ねる
  3. グレースケールバー - 「R=G=B=nnn」をその色の上に
  4. HSV レインボー    - 各ブロックに連番・色相度数を表示
  5. HSL バリエーション - 彩度/明度変化 + 色相リング
  6. RGB 面チャート    - 座標値 R/G/B を表示
  7. 表示スタイル一覧  - 文字装飾 + サンプル文章
  8. おすすめテーマ    - ダーク/ライトの見やすい組み合わせ
  9. 256 色一覧        - 各色 ID をその色の上に表示
==============================================
実行: python3 color_samples.py
"""

import sys

# ---------- エスケープヘルパー ----------
def esc(*codes):
    return "\033[" + ";".join(str(c) for c in codes) + "m"

RESET  = esc(0)
BG     = lambda *c: esc(48, 2, *c)   # 24-bit BG
FG     = lambda *c: esc(38, 2, *c)   # 24-bit FG
BOLD   = esc(1)
DIM    = esc(2)
UNDER  = esc(4)
INV    = esc(7)

# ---------- 色変換ヘルパー ----------
def rgb(r, g, b):
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))

def luma(r, g, b):
    # ITU-R BT.709 luminance
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def fg_for_bg(r, g, b):
    """背景色に対して、明るい背景→黒字、暗い背景→白字"""
    return (0, 0, 0) if luma(r, g, b) > 128 else (255, 255, 255)

def hsv_to_rgb(h, s, v):
    h = h % 360
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if   h < 60:  r1, g1, b1 = c, x, 0
    elif h < 120: r1, g1, b1 = x, c, 0
    elif h < 180: r1, g1, b1 = 0, c, x
    elif h < 240: r1, g1, b1 = 0, x, c
    elif h < 300: r1, g1, b1 = x, 0, c
    else:         r1, g1, b1 = c, 0, x
    return rgb(int((r1 + m) * 255), int((g1 + m) * 255), int((b1 + m) * 255))

def hsl_to_rgb(h, s, l):
    """H: 0-360, S,L: 0-1"""
    h = h % 360
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if   h < 60:  r1, g1, b1 = c, x, 0
    elif h < 120: r1, g1, b1 = x, c, 0
    elif h < 180: r1, g1, b1 = 0, c, x
    elif h < 240: r1, g1, b1 = 0, x, c
    elif h < 300: r1, g1, b1 = x, 0, c
    else:         r1, g1, b1 = c, 0, x
    return rgb(int((r1 + m) * 255), int((g1 + m) * 255), int((b1 + m) * 255))

def ansi_rgb(idx):
    """256色コード -> おおよその (R,G,B)"""
    if idx < 16:
        base = [
            (0,0,0),(205,0,0),(0,205,0),(205,205,0),
            (0,0,238),(205,0,205),(0,205,205),(229,229,229),
            (127,127,127),(255,0,0),(0,255,0),(255,255,0),
            (92,92,255),(255,0,255),(0,255,255),(255,255,255),
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


# ============================================================
#  CORE UTILITY:  N文字の文字を背景色の上に描画する
# ============================================================
def color_block(text, r, g, b, width=None, fg_override=None):
    """
    width: ブロック全体の描幅（文字パディング）。None=パディングなし
    fg_override: 文字色の強制指定。None=自動コントラスト
    """
    fg = fg_override if fg_override else fg_for_bg(r, g, b)
    if width is not None:
        t = text.center(width)
    else:
        t = text
    return f"{BG(r,g,b)}{FG(*fg)}{t}{RESET}"

def color_block_8(col_id, text):
    """8-bit 256カラーパレット ID で背景色を指定する版"""
    return f"\033[48;5;{col_id}m{text}\033[0m"


# ============================================================
#  SECTION 1: 基本16色
# ============================================================
def section_basic_16():
    names = [
        "BLACK", "D_RED","D_GRN","D_YEL",
        "D_BLU","D_MGN","D_CYN","D_WHT",
        "BLACK+", "RED", "GRN", "YEL",
        "BLU", "MGN", "CYN", "WHT",
    ]
    print(f"{BOLD}{UNDER}Section 1. Basic 16 colors (text on each color background){RESET}\n")
    for i, name in enumerate(names):
        if i == 8:
            print()
        r, g, b = ansi_rgb(i)
        line = color_block(f" {name:>5} Aa 1 0 ", r, g, b)
        sys.stdout.write(line)
    print("\n")


# ============================================================
#  SECTION 2: 256 色パレット（ID をその色に重ねる）
# ============================================================
def section_256_palette():
    print(f"{BOLD}{UNDER}Section 2. 256-color palette (text = color ID){RESET}\n")

    # (a) 基本16
    print(f"  {BOLD}[0-15] Basic Colors{RESET}")
    for row in range(2):
        line = "    "
        for col in range(8):
            idx = row * 8 + col
            r, g, b = ansi_rgb(idx)
            line += color_block(f" {idx:>2} Aa ", r, g, b)
        print(line)
    print()

    # (b) 216色 RGB立方体 (16-231)
    print(f"  {BOLD}[16-231] RGB 6x6x6 cube (text = ID){RESET}")
    for z in range(6):
        print(f"    plane Z(R)={z}")
        for y in range(6):
            line = "      "
            for x in range(6):
                idx = 16 + 36 * z + 6 * y + x
                r, g, b = ansi_rgb(idx)
                line += color_block(f"{idx:>3}", r, g, b)
            print(line)
        print()

    # (c) グレースケール (232-255)
    print(f"  {BOLD}[232-255] Grayscale{RESET}")
    line = "    "
    for idx in range(232, 256):
        r, g, b = ansi_rgb(idx)
        if idx == 244:
            line += "\n    "
        line += color_block(f"{idx:>3}", r, g, b)
    print(line + "\n")


# ============================================================
#  SECTION 3: グレースケールバー
# ============================================================
def section_grayscale_full():
    print(f"{BOLD}{UNDER}Section 3. Grayscale bar (text = R=G=B=value){RESET}\n")
    for v in [0, 32, 64, 96, 128, 160, 192, 224, 255]:
        r, g, b = v, v, v
        print(f"  {color_block(' %sA%s ' % (chr(9608), chr(9617)), r, g, b, fg_override=(255,255,255) if v < 128 else (0,0,0))}"
              f"  R=G=B={v:>3}")
    print()


# ============================================================
#  SECTION 4: HSV レインボー（連番数字）
# ============================================================
def section_hsv_rainbow():
    print(f"\n{BOLD}{UNDER}Section 4. HSV Rainbow (text = index & hue degree){RESET}\n")
    cols = 36
    line0 = "  "
    line1 = "  "
    for i in range(cols):
        h = i * 360 / cols
        r, g, b = hsv_to_rgb(h, 1.0, 1.0)
        line0 += color_block(f"{i:>2}", r, g, b)
        line1 += color_block(f"{int(h/10):>2}", r, g, b)
    print(line0)
    print(line1)
    labels = ["0", "36", "72", "108", "144", "180", "216", "252", "288", "324", "360"]
    print("  " + "".join(f"{lab:>3}" for lab in labels))
    print()


# ============================================================
#  SECTION 5: HSL バリエーション
# ============================================================
def section_hsl_variations():
    print(f"\n{BOLD}{UNDER}Section 5. HSL Variations{RESET}\n")

    # (a) 彩度変化
    print(f"  {BOLD}(a) Saturation sweep  H=210, L=0.50  S: 0.0 -> 1.0{RESET}")
    line = "    "
    for i in range(20):
        s = i / 19
        r, g, b = hsl_to_rgb(210, s, 0.5)
        label = "{:.1f}".format(s)
        line += color_block(label, r, g, b)
    print(line + "\n")

    # (b) 明度変化
    print(f"  {BOLD}(b) Lightness sweep  H=210, S=1.0  L: 0.0 -> 1.0{RESET}")
    line = "    "
    for i in range(20):
        l = i / 19
        r, g, b = hsl_to_rgb(210, 1.0, l)
        label = "{:.1f}".format(l)
        line += color_block(label, r, g, b)
    print(line + "\n")

    # (c) 色相リング
    print(f"  {BOLD}(c) Hue ring  S=0.9, L=0.5  (text = degree){RESET}")
    for row in range(4):
        line = "    "
        for col in range(36):
            h = (row * 36 + col) * (360 / 144)
            r, g, b = hsl_to_rgb(h, 0.9, 0.5)
            label = "{:>3}".format(int(h))
            line += color_block(label, r, g, b)
        print(line)

    # (d) カラーパレット候補
    print(f"\n  {BOLD}(d) Popular palette candidates (text = hue degree){RESET}")
    palettes = [
        ("Jet-like",      [0, 16, 32, 64, 96, 128, 160, 192, 224, 240]),
        ("Plasma-like",   [0, 20, 40, 65, 95, 125, 155, 185, 210, 235]),
        ("Pastel",        [(h, 0.4, 0.7) for h in range(0, 360, 36)]),
        ("Deep",          [(h, 0.85, 0.38) for h in range(0, 360, 36)]),
        ("Neon",          [(h, 1.0, 0.5) for h in range(0, 360, 36)]),
    ]
    for name, hs in palettes:
        line = "    {:>14}: ".format(name)
        for item in hs:
            if isinstance(item, tuple):
                h, s, l = item
                r, g, b = hsl_to_rgb(h, s, l)
            else:
                r, g, b = hsv_to_rgb(item, 1.0, 1.0)
            line += color_block("{:>2}d".format(int(item[0] if isinstance(item, tuple) else item)), r, g, b)
        print(line)
    print()


# ============================================================
#  SECTION 6: RGB 別・面チャート
# ============================================================
def section_rgb_axes():
    print(f"{BOLD}{UNDER}Section 6. RGB axis & face charts (text = coordinate value){RESET}\n")

    # (a) 単軸グラデーション（文字に軸名+値）
    steps = 16
    trials = [
        ("Red sweep    R:100->255 (G=B=128)",  0, (128, 128), "R"),
        ("Green sweep  G:100->255 (R=B=128)",  1, (128, 128), "G"),
        ("Blue sweep   B:100->255 (R=G=128)",  2, (128, 128), "B"),
    ]
    for title, ch_idx, fixed, axis_name in trials:
        print(f"  {BOLD}{title}{RESET}")
        line = "    "
        for i in range(steps):
            v = 100 + (255 - 100) * i // (steps - 1)
            color_vals = list(fixed)
            color_vals.insert(ch_idx, v)
            r, g, b = color_vals
            label = "{}{}".format(axis_name, v)
            line += color_block(label, r, g, b)
        print(line + "\n")

    # (b) G-B 面 (R=255)  ex.  G0  G63 G127 ...
    print(f"  {BOLD}Face chart: G-B plane (R=255, text = G-value){RESET}")
    for gi in range(5):
        line = "    "
        gv = 255 * gi // 4
        for _ in range(5):
            line += color_block(" {}".format(gv), 255, gv, 0)
        print(line)

    print(f"\n  {BOLD}Face chart: R-B plane (G=165, text = B-value){RESET}")
    for gi in range(5):
        line = "    "
        rv = 255 * gi // 4
        for _ in range(5):
            line += color_block(" {}".format(rv), rv, 165, 0)
        print(line)

    print(f"\n  {BOLD}Face chart: R-G plane (B=0, text = R-value){RESET}")
    for gi in range(5):
        line = "    "
        rv = 255 * gi // 4
        bv = 255 * gi // 4
        for _ in range(5):
            line += color_block(" {}".format(rv), rv, bv, 0)
        print(line + "\n")


# ============================================================
#  SECTION 7: 文字装飾 + サンプル文章
# ============================================================
def section_text_samples():
    print(f"\n{BOLD}{UNDER}Section 7. Text style samples (with sample text){RESET}\n")

    sample = " The quick brown fox jumps over the lazy dog. 12345 "

    styles = [
        ("Bold",     BOLD, (220, 20, 60)),
        ("Inverted", INV,  (25, 25, 112)),
        ("Underline",UNDER, (0, 100, 0)),
        ("Dim",      DIM,  (128, 0, 128)),
        ("Normal",   "",   (255, 165, 0)),
    ]
    for name, attr, bg in styles:
        fg = fg_for_bg(*bg)
        print(f"  {attr}{BG(*bg)}{FG(*fg)}{sample}{RESET}  <- {name}")

    print()
    print(f"  {BOLD}Progress bar style (0% -> 100%):{RESET}")
    total = 20
    for progress in [0, 10, 25, 50, 75, 90, 100]:
        filled = int(total * progress / 100)
        bar = ""
        for i in range(filled):
            ratio = i / max(1, total)
            rc = int(255 * (1 - ratio * 0.8))
            gc = int(255 * ratio)
            bc = 50
            fg = fg_for_bg(rc, gc, bc)
            bar += f"{BG(rc,gc,bc)}{FG(*fg)}{chr(9617)}{RESET}"
        if filled < total:
            bar += "_" * (total - filled)
        label = " {}% ".format(progress)
        fg_label = fg_for_bg(40, 40, 40)
        print(f"    |{bar}|{RESET} {FG(*fg_label)}{label.strip().center(5)}{RESET}")
    print()


# ============================================================
#  SECTION 8: おすすめテーマ（背景+文字色）
# ============================================================
def section_recommended():
    print(f"{BOLD}{UNDER}Section 8. Recommended themes (dark / light){RESET}\n")

    dark_bgs  = [(23, 32, 42), (20, 30, 48), (30, 30, 30), (15, 20, 25), (35, 20, 30)]
    dark_fgs  = [(170, 215, 230), (120, 220, 180), (240, 200, 100), (200, 160, 250), (255, 140, 140)]
    light_bgs = [(240, 245, 250), (245, 240, 235), (250, 250, 245), (235, 245, 240), (240, 235, 245)]
    light_fgs = [(40, 55, 75), (70, 40, 30), (50, 60, 20), (70, 40, 70), (90, 50, 30)]

    sample = " Hello, World! 0123456789 "

    print(f"  {BOLD}Dark mode:{RESET}")
    for bg_c, fg_c in zip(dark_bgs, dark_fgs):
        hex_bg = "{:02X}{:02X}{:02X}".format(*bg_c)
        hex_fg = "{:02X}{:02X}{:02X}".format(*fg_c)
        print(f"    {BG(*bg_c)}{FG(*fg_c)}{sample}{RESET}  <- bg: #{hex_bg}  fg: #{hex_fg}")

    print(f"\n  {BOLD}Light mode:{RESET}")
    for bg_c, fg_c in zip(light_bgs, light_fgs):
        hex_bg = "{:02X}{:02X}{:02X}".format(*bg_c)
        hex_fg = "{:02X}{:02X}{:02X}".format(*fg_c)
        print(f"    {BG(*bg_c)}{FG(*fg_c)}{sample}{RESET}  <- bg: #{hex_bg}  fg: #{hex_fg}")
    print()


# ============================================================
#  SECTION 9: 256色一覧（全IDをその色に重ねて表示）
# ============================================================
def section_all_256_ids():
    print(f"{BOLD}{UNDER}Section 9. Full 256-color list (text = color ID){RESET}\n")
    for i in range(256):
        r, g, b = ansi_rgb(i)
        label = "{:>3}".format(i)
        end = "\n" if (i + 1) % 16 == 0 else ""
        sys.stdout.write(color_block(label, r, g, b) + end)
    print()


# ============================================================
#  MAIN
# ============================================================
def main():
    print()
    print("=" * 80)
    print("  Terminal Color Sample Collection (Text Overlay Edition)")
    print("  Each colored block has text rendered on it (ID / number / sample)")
    print("  Looks best on True Color (24-bit) terminals")
    print("=" * 80)
    print()

    section_basic_16()
    section_256_palette()
    section_grayscale_full()
    section_hsv_rainbow()
    section_hsl_variations()
    section_rgb_axes()
    section_text_samples()
    section_recommended()
    section_all_256_ids()

    print(f"{BOLD}{UNDER}End of samples{RESET}\n")


if __name__ == "__main__":
    main()
