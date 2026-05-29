#!/usr/bin/env python3
"""
ターミナルカラーサンプル集
──────────────────────────────────
1. 基本カラー（16色）
2. 拡張256色パレット（旧来＋クオリティ系）
3. 256色のグレースケール
4. 256色のレインボーグラデーション（RGB立方体スライス）
5. HSLベースの連続グラデーション
6. 全色を参照できるタテ棒チャート（簡易）
7. 256色 ID → 色表示（確認用）

実行: python3 color_samples.py
※ 対応ターミナル（24bit/8bit）で見栄えが変わります。
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
BLINK   = esc(5)
INV     = esc(7)

BLOCK   = "████████"
SPACE2  = "  "
SPACE4  = "    "

def rgb(r: int, g: int, b: int) -> tuple[int, int, int]:
    return (max(0, min(255, r)),
            max(0, min(255, g)),
            max(0, min(255, b)))

def luma(r: int, g: int, b: int) -> float:
    return 0.2126 * r + 0.7152 * g + 0.0722 * b          # ITU‑R BT.709

def fg_for_bg(r: int, g: int, b: int) -> tuple[int, int, int]:
    """背景に対するコントラストの高い文字色"""
    return (0, 0, 0) if luma(r, g, b) > 128 else (255, 255, 255)

def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
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

def hsl_to_rgb(h: float, s: float, l: float) -> tuple[int, int, int]:
    """H:0‑360  S,L:0‑1"""
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


# ═══════════════════════════════════════════
# 1. 基本 16 色
# ═══════════════════════════════════════════
def section_basic_16():
    names = [
        "黒",   "暗赤", "暗緑", "暗黄",
        "暗青", "暗紫", "暗水色","明灰",
        "暗灰", "赤",   "緑",   "黄",
        "青",   "紫",   "水色", "白",
    ]
    print(f"{BOLD}{UNDER}▶ 1. 基本 16 色（ANSI Colors）{RESET}")
    for i, name in enumerate(names):
        if i == 8:
            print()
        # 背景に基本色、適切な文字色
        code = 30 + i if i < 8 else 90 + (i - 8)
        sys.stdout.write(f"\033[{code};{40 + (i if i < 8 else i)}m {name:>4} {RESET}")
    print("\n")


# ═══════════════════════════════════════════
# 2. 256 色パレット（旧来カラー 16‑231）
# ═══════════════════════════════════════════
def section_256_palette():
    print(f"{BOLD}{UNDER}▶ 2. 256 色パレット（0‑255）{RESET}\n")

    # (a) 基本16 (0-15)
    print(f"  {BOLD}[0–15] 基本色{RESET}")
    col = 0
    for row in range(2):
        line = "    "
        for _ in range(8):
            r, g, b = ANSIRGB_256(col)
            fg = fg_for_bg(r, g, b)
            line += f"{BG8(col)}  {col:>3}  {RESET}"
            col += 1
        print(line)
    print()

    # (b) 216色 RGB立方体 (16-231)
    print(f"  {BOLD}[16–231] RGB 6×6×6 立方体（Z: 面ごとに6×6ブロック）{RESET}")
    for z in range(6):
        print(f"    R={z}")
        for y in range(6):
            line = "      "
            for x in range(6):
                idx = 16 + 36 * z + 6 * y + x
                r, g, b = ANSIRGB_256(idx)
                fg = fg_for_bg(r, g, b)
                line += f"{BG8(idx)}{RESET}"
            print(line)
        print()

    # (c) グレースケール (232-255)
    print(f"  {BOLD}[232–255] グレースケール{RESET}")
    line = "    "
    for idx in range(232, 256):
        r, g, b = ANSIRGB_256(idx)
        fg = fg_for_bg(r, g, b)
        if idx == 244:
            line += "\n    "
        line += f"{BG8(idx)}  {idx:>3}  {RESET}"
    print(line + "\n")


def ANSIRGB_256(idx: int) -> tuple[int, int, b]:
    """256 色コード (0‑255) → (R,G,B)（ANSI準拠の近似値）"""
    if idx < 16:
        # 基本色 – 標準値を返す（おおよその値）
        base = [
            (0, 0, 0),     (205, 0, 0),    (0, 205, 0),    (205, 205, 0),
            (0, 0, 238),   (205, 0, 205),  (0, 205, 205),  (229, 229, 229),
            (127, 127, 127),(255, 0, 0),   (0, 255, 0),    (255, 255, 0),
            (92, 92, 255), (255, 0, 255),  (0, 255, 255),  (255, 255, 255),
        ]
        return base[idx]
    if idx < 232:
        n = idx - 16
        return (
            [0, 95, 135, 175, 215, 255][n // 36],
            [0, 95, 135, 175, 215, 255][(n % 36) // 6],
            [0, 95, 135, 175, 215, 255][n % 6],
        )
    # 232-255 グレー
    v = 8 + (idx - 232) * 10
    return (v, v, v)


# ═══════════════════════════════════════════
# 3. グレースケールバー（0‑255 ステップ）
# ═══════════════════════════════════════════
def section_grayscale_full():
    print(f"{BOLD}{UNDER}▶ 3. グレースケール バー（0–255）{RESET}")
    steps = 32
    chunk = 256 // steps
    line = "  "
    for i in range(steps):
        v = min(255, i * chunk)
        r, g, b = v, v, v
        fg = fg_for_bg(r, g, b)
        line += f"{BG8(232 + min(23, i))}{'▀'}{RESET}"
    print(line + "\n")

    # 文字でのステップ表示
    for v in [0, 32, 64, 96, 128, 160, 192, 224, 255]:
        approx = 232 + max(0, min(23, round((v - 8) / 10)))
        r, g, b = v, v, v
        fg = fg_for_bg(r, g, b)
        print(f"  {BG(approx // 232 * 0 + v, v, v)}  R=G=B={v:>3}  "
              f"(256色ID≈{approx:>3})  {RESET}")


# ═══════════════════════════════════════════
# 4. レインボー HSV グラデーション（連続）
# ═══════════════════════════════════════════
def section_hsv_rainbow():
    print(f"\n{BOLD}{UNDER}▶ 4. HSV レインボー（H: 0→360°, S=V=1）{RESET}\n")
    cols = 72
    line = "  "
    for i in range(cols):
        h = i * 360 / cols
        r, g, b = hsv_to_rgb(h, 1.0, 1.0)
        line += f"{BG(r, g, b)} {RESET}"
    print(line)
    print(f"  {'0°':<10}{'60°':^10}{'120°':^10}{'180°':^10}{'240°':^10}{'300°':^10}{'360°':>10}\n")


# ═══════════════════════════════════════════
# 5. HSL ベース 連続グラデーション
# ═══════════════════════════════════════════
def section_hsl_variations():
    print(f"\n{BOLD}{UNDER}▶ 5. HSL バリエーション{RESET}\n")

    # (a) 彩度を変える（H=210 青系, L=0.5）
    print(f"  {BOLD}(a) 彩度変化  H=210°, L=0.50{RESET}")
    line = "    S=0.0→1.0: "
    for i in range(20):
        s = i / 19
        r, g, b = hsl_to_rgb(210, s, 0.5)
        line += f"{BG(r, g, b)}{'█'}{RESET}"
    print(line)

    # (b) 明度を変える（H=210, S=1.0）
    print(f"  {BOLD}(b) 明度変化  H=210°, S=1.0{RESET}")
    line = "    L=0.0→1.0: "
    for i in range(20):
        l = i / 19
        r, g, b = hsl_to_rgb(210, 1.0, l)
        line += f"{BG(r, g, b)}{'█'}{RESET}"
    print(line)

    # (c) 色相リング（固定 S/L で一周）
    print(f"\n  {BOLD}(c) 色相リング  S=0.9, L=0.5{RESET}")
    for row in range(4):
        line = "    "
        for col in range(36):
            h = (row * 36 + col) * (360 / 144)
            r, g, b = hsl_to_rgb(h, 0.9, 0.5)
            line += f"{BG(r, g, b)} {RESET}"
        print(line)

    # (d) 見やすいパレット候補5種
    print(f"\n  {BOLD}(d) よく使われるカラーパレット候補（Jet / Viridisっぽい）{RESET}")
    palettes = [
        ("Jetっぽい",    [0, 16, 32, 64, 96, 128, 160, 192, 224, 240]),
        ("Plasmaっぽい", [0, 20, 40, 65, 95, 125, 155, 185, 210, 235]),
        ("Pastel",       [(h, 0.4, 0.7) for h in range(0, 360, 36)]),
        ("Deep",         [(h, 0.85, 0.38) for h in range(0, 360, 36)]),
        ("Neon",         [(h, 1.0, 0.5) for h in range(0, 360, 36)]),
    ]
    for name, hs in palettes:
        line = f"    {name:>14}: "
        for item in hs:
            if isinstance(item, tuple):
                h, s, l = item
                r, g, b = hsl_to_rgb(h, s, l)
            else:
                r, g, b = hsv_to_rgb(item, 1.0, 1.0)
            line += f"{BG(r, g, b)}  {RESET}"
        print(line)
    print()


# ═══════════════════════════════════════════
# 6. 24‑bit 全色チャート（R / G / B 各軸）
# ═══════════════════════════════════════════
def section_rgb_axes():
    print(f"{BOLD}{UNDER}▶ 6. RGB 別チャート{RESET}\n")

    def ramp(step: int, max_step: int, ch: int) -> tuple:
        return tuple(100 + ch * (255 - 100) * step // max_step for _ in range(1))

    steps = 20
    print(f"  {BOLD}赤のグラデーション{RESET}  G,B=(128,128)  R: 100→255")
    line = "    "
    for i in range(steps):
        rv = 100 + (255 - 100) * i // (steps - 1)
        line += f"{BG(rv, 128, 128)} {RESET}"
    print(line)

    print(f"  {BOLD}緑のグラデーション{RESET}  R,B=(128,128):  G: 100→255")
    line = "    "
    for i in range(steps):
        gv = 100 + (255 - 100) * i // (steps - 1)
        line += f"{BG(128, gv, 128)}{RESET}"
    print(line)

    print(f"  {BOLD}青のグラデーション{RESET}  R,G=(128,128):  B: 100→255")
    line = "    "
    for i in range(steps):
        bv = 100 + (255 - 100) * i // (steps - 1)
        line += f"{BG(128, 128, bv)}{RESET}"
    print(line + "\n")

    # 面チャート（固定 R で G-B 面、固定 G で R-B 面、固定 B で R-G 面）
    r_fix, g_fix, b_fix = 255, 165, 0   # オレンジ系
    print(f"  {BOLD}G-B 面（R=255）{RESET}")
    for gi in range(5):
        line = "    "
        gv = 255 * gi // 4
        for bi in range(10):
            bv = 255 * bi // 9
            line += f"{BG(r_fix, gv, bv)}{BLOCK[0]}{RESET}"
        print(line)

    print(f"  {BOLD}R-B 面（G=165）{RESET}")
    for ri in range(5):
        line = "    "
        rv = 255 * ri // 4
        for bi in range(10):
            bv = 255 * bi // 9
            line += f"{BG(rv, g_fix, bv)}{BLOCK[0]}{RESET}"
        print(line)

    print(f"  {BOLD}R-G 面（B=0）{RESET}")
    for ri in range(5):
        line = "    "
        rv = 255 * ri // 4
        for gi in range(10):
            gv = 255 * gi // 9
            line += f"{BG(rv, gv, b_fix)}{BLOCK[0]}{RESET}"
        print(line + "\n")


# ═══════════════════════════════════════════
# 7. テクスチャ付き / テクスチャなし切替比較
# ═══════════════════════════════════════════
def section_text_samples():
    print(f"\n{BOLD}{UNDER}▶ 7. 各種表示スタイル{RESET}\n")
    samples = [
        ("太字 + 赤色背景",          BOLD + BG(220, 20, 60)),
        ("斜体の代わり 反転",        INV   + BG(25, 25, 112)),
        ("下線 + 緑",                UNDER + BG(0, 100, 0)),
        ("薄い + チェック柄のように",  DIM  + BG(128, 0, 128)),
        ("点滅は危険なので網掛け",    BG(255, 165, 0) + BOLD),
    ]
    for label, fmt in samples:
        r = int(fmt.split(';')[2].split('m')[0]) if ';38;' not in fmt else 0
        # 描画のために適当に色を入れる
        print(f"  {fmt}{' ':>30}{RESET} ← {label}")

    # ロードバーっぽい表示
    print(f"\n  {BOLD}ロードバー風:{RESET}")
    total = 40
    for progress in [0, 10, 25, 50, 75, 90, 100]:
        filled = int(total * progress / 100) + 1
        bar = ""
        for i in range(filled):
            # グラデーション: 赤 → 黄 → 緑
            ratio = i / total
            r_c = int(255 * (1 - ratio * 0.8))
            g_c = int(255 * ratio)
            b_c = 50
            bar += f"{BG(r_c, g_c, b_c)} {RESET}"
        bar += "░" * (total - filled)
        print(f"    {progress:>3}% |{bar}|")
    print()


# ═══════════════════════════════════════════
# 8. おすすめ「見やすいカラー」サンプル
# ═══════════════════════════════════════════
def section_recommended():
    print(f"{BOLD}{UNDER}▶ 8. おすすめ見やすいカラー（ダーク/ライト）{RESET}\n")
    dark_bgs  = [(23, 32, 42), (20, 30, 48), (30, 30, 30), (15, 20, 25), (35, 20, 30)]
    dark_fgs  = [(170, 215, 230), (120, 220, 180), (240, 200, 100), (200, 160, 250), (255, 140, 140)]
    light_bgs = [(240, 245, 250), (245, 240, 235), (250, 250, 245), (235, 245, 240), (240, 235, 245)]
    light_fgs = [(40, 55, 75), (70, 40, 30), (50, 60, 20), (70, 40, 70), (90, 50, 30)]

    print(f"  {BOLD}{BG(0,0,0)} 背景色 →{RESET} + 文字色 → {BOLD}サンプル{RESET}\n")
    print(f"  {'ダークモード':}")
    for i in range(len(dark_bgs)):
        bg_c = dark_bgs[i]
        fg_c = dark_fgs[i]
        r, g, b = fg_c
        print(f"    {BG(*bg_c)}{FG(*fg_c)}  abcdef0123456789  ← #{r:02X}{g:02X}{b:02X}  {RESET}")

    print(f"\n  {'ライトモード':}")
    for i in range(len(light_bgs)):
        bg_c = light_bgs[i]
        fg_c = light_fgs[i]
        r, g, b = fg_c
        print(f"    {BG(*bg_c)}{FG(*fg_c)}  abcdef0123456789  ← #{r:02X}{g:02X}{b:02X}  {RESET}")
    print()


# ═══════════════════════════════════════════
# 9. 256色 ID → 色表示（全部）
# ═══════════════════════════════════════════
def section_all_256_ids():
    print(f"{BOLD}{UNDER}▶ 9. 256色 ID → 色表示（全コード確認）{RESET}\n")
    for i in range(256):
        r, g, b = ANSIRGB_256(i)
        fg = fg_for_bg(r, g, b)
        end = "\n" if (i + 1) % 16 == 0 else ""
        sys.stdout.write(f"{BG8(i)} {i:>3} {RESET}{end}")
    print()


# ═══════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════
def main():
    print(f"\n{'═' * 80}")
    print(f"  🎨 ターミナルカラーサンプル集 — ESC シーケンスで全描画")
    print(f"  ターミナルが 24‑bit（True Color）をサポートしていると最も綺麗です")
    print(f"  例: export COLORTERM=truecolor")
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
