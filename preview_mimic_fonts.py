"""
MIMIC ASCII アートフォントプレビュー
pyfiglet で "MIMIC" を各種フォントで描画し、グラデーションカラーを付けて表示する。
"""
import sys

try:
    import pyfiglet
except ImportError:
    print("pyfiglet が必要です: pip install pyfiglet")
    sys.exit(1)

# ── カラー定義 ───────────────────────────────────────────────────────
R   = "\033[0m"
BLD = "\033[1m"
DIM = "\033[2m"

def rgb(r, g, b): return f"\033[38;2;{r};{g};{b}m"

GRADIENTS = {
    "green_aqua": [
        rgb(0,255,65), rgb(0,255,120), rgb(0,255,180),
        rgb(0,242,218), rgb(0,230,255), rgb(80,220,255),
        rgb(120,210,255), rgb(160,200,255), rgb(180,195,255),
    ],
    "fire": [
        rgb(255,30,0), rgb(255,80,0), rgb(255,130,0),
        rgb(255,180,0), rgb(255,220,0), rgb(255,245,80),
        rgb(255,255,140), rgb(255,255,200), rgb(255,255,230),
    ],
    "purple_pink": [
        rgb(100,0,220), rgb(140,0,255), rgb(180,40,255),
        rgb(210,80,255), rgb(240,140,255), rgb(255,170,255),
        rgb(255,200,255), rgb(255,220,255), rgb(255,235,255),
    ],
    "cyan_white": [
        rgb(0,180,255), rgb(0,210,255), rgb(40,230,255),
        rgb(100,245,255), rgb(160,252,255), rgb(200,255,255),
        rgb(230,255,255), rgb(250,255,255), rgb(255,255,255),
    ],
    "gold": [
        rgb(160,80,0), rgb(190,110,0), rgb(215,145,0),
        rgb(235,175,0), rgb(255,215,0), rgb(255,235,60),
        rgb(255,248,120), rgb(255,255,180), rgb(255,255,220),
    ],
    "ice": [
        rgb(0,120,200), rgb(0,150,230), rgb(0,180,255),
        rgb(60,210,255), rgb(120,230,255), rgb(180,240,255),
        rgb(210,248,255), rgb(235,252,255), rgb(255,255,255),
    ],
    "neon_green": [
        rgb(0,255,0), rgb(50,255,50), rgb(100,255,80),
        rgb(150,255,100), rgb(180,255,120), rgb(200,255,150),
        rgb(220,255,180), rgb(235,255,210), rgb(245,255,235),
    ],
    "magenta_orange": [
        rgb(255,0,120), rgb(255,20,80), rgb(255,60,40),
        rgb(255,100,0), rgb(255,150,0), rgb(255,200,0),
        rgb(255,230,40), rgb(255,250,100), rgb(255,255,160),
    ],
    "deep_blue": [
        rgb(0,0,200), rgb(0,40,230), rgb(0,80,255),
        rgb(40,120,255), rgb(80,160,255), rgb(120,195,255),
        rgb(160,220,255), rgb(200,240,255), rgb(230,252,255),
    ],
    "matrix": [
        rgb(0,80,0), rgb(0,120,0), rgb(0,160,0),
        rgb(0,200,0), rgb(0,230,0), rgb(0,255,0),
        rgb(80,255,80), rgb(160,255,160), rgb(210,255,210),
    ],
    "blood": [
        rgb(120,0,0), rgb(160,0,0), rgb(200,0,0),
        rgb(230,20,20), rgb(255,40,40), rgb(255,80,60),
        rgb(255,120,80), rgb(255,160,120), rgb(255,200,170),
    ],
    "sunset": [
        rgb(60,0,80), rgb(100,0,100), rgb(140,0,120),
        rgb(180,40,80), rgb(220,80,40), rgb(255,120,0),
        rgb(255,170,0), rgb(255,210,60), rgb(255,240,140),
    ],
}

# ── フォント定義 (font_name, gradient, 説明, カテゴリ) ──────────────
FONTS = [
    # ── クラシック定番 ─────────────────────────────────────────
    ("doom",           "green_aqua",    "クラシック定番 DOOM"),
    ("big",            "cyan_white",    "Big — バランス良好"),
    ("slant",          "purple_pink",   "Slant — スタイリッシュ斜体"),
    ("standard",       "gold",          "Standard — figlet 標準"),
    ("lean",           "cyan_white",    "Lean — シャープ細身"),
    ("block",          "gold",          "Block — アンダースコア使用"),
    ("speed",          "purple_pink",   "Speed — 疾走感"),
    ("starwars",       "green_aqua",    "Star Wars スクロール"),
    ("graffiti",       "fire",          "Graffiti — 落書き風"),
    ("epic",           "fire",          "Epic"),

    # ── 3D・立体 ───────────────────────────────────────────────
    ("isometric1",     "gold",          "Isometric 1 — 3D 等角投影"),
    ("isometric2",     "purple_pink",   "Isometric 2"),
    ("isometric3",     "cyan_white",    "Isometric 3"),
    ("isometric4",     "ice",           "Isometric 4"),
    ("3-d",            "green_aqua",    "3-D — シンプル立体"),
    ("3d-ascii",       "gold",          "3D ASCII"),
    ("henry_3d",       "fire",          "Henry 3D"),
    ("larry3d",        "purple_pink",   "Larry 3D"),

    # ── 重厚・太字 ─────────────────────────────────────────────
    ("colossal",       "fire",          "Colossal — 巨大"),
    ("banner3-D",      "gold",          "Banner 3-D"),
    ("banner3",        "green_aqua",    "Banner 3"),
    ("banner4",        "cyan_white",    "Banner 4"),
    ("chunky",         "magenta_orange","Chunky — 丸太字"),
    ("broadway",       "fire",          "Broadway — 舞台看板風"),
    ("big_money-ne",   "gold",          "Big Money NE"),
    ("big_money-nw",   "purple_pink",   "Big Money NW"),
    ("big_money-se",   "fire",          "Big Money SE"),
    ("big_money-sw",   "cyan_white",    "Big Money SW"),

    # ── シャドウ・グロー ───────────────────────────────────────
    ("ansi_shadow",    "neon_green",    "ANSI Shadow — シャドウ付き"),
    ("ansi_regular",   "ice",           "ANSI Regular — モダン"),
    ("shadow",         "purple_pink",   "Shadow — ミニシャドウ"),
    ("cosmic",         "sunset",        "Cosmic — 宇宙風"),
    ("nancyj",         "cyan_white",    "NancyJ"),
    ("nancyj-fancy",   "purple_pink",   "NancyJ Fancy"),
    ("ghost",          "ice",           "Ghost — 浮かび上がる"),
    ("gradient",       "green_aqua",    "Gradient"),

    # ── 炎・血・ダーク ─────────────────────────────────────────
    ("bloody",         "blood",         "Bloody — 恐怖系"),
    ("fire_font-k",    "fire",          "Fire Font K — 炎"),
    ("fire_font-s",    "magenta_orange","Fire Font S — 炎(細)"),
    ("poison",         "matrix",        "Poison"),
    ("def_leppard",    "blood",         "Def Leppard"),
    ("devilish",       "fire",          "Devilish"),
    ("barbwire",       "blood",         "Barbwire — 有刺鉄線"),

    # ── レトロ・テック ─────────────────────────────────────────
    ("dos_rebel",      "matrix",        "DOS Rebel — レトロDOS"),
    ("dotmatrix",      "green_aqua",    "Dot Matrix — ドットプリンタ"),
    ("electronic",     "ice",           "Electronic — LED風"),
    ("computer",       "neon_green",    "Computer"),
    ("lcd",            "matrix",        "LCD — 液晶ディスプレイ"),
    ("trek",           "ice",           "Trek — Star Trek"),
    ("rammstein",      "fire",          "Rammstein — バンド風"),
    ("sub-zero",       "ice",           "Sub-Zero"),

    # ── ファンシー・装飾 ───────────────────────────────────────
    ("roman",          "gold",          "Roman — ローマン体"),
    ("univers",        "cyan_white",    "Univers — モダン"),
    ("varsity",        "magenta_orange","Varsity — 大学スポーツ"),
    ("acrobatic",      "purple_pink",   "Acrobatic"),
    ("delta_corps_priest_1", "deep_blue","Delta Corps Priest — SF"),
    ("coil_cop",       "green_aqua",    "Coil Cop"),
    ("whimsy",         "purple_pink",   "Whimsy — ひょうきん"),
    ("broadway_kb",    "gold",          "Broadway KB"),
    ("alligator",      "fire",          "Alligator"),
    ("alligator2",     "green_aqua",    "Alligator 2"),
    ("tubular",        "cyan_white",    "Tubular — パイプ"),
    ("stencil1",       "blood",         "Stencil 1"),
    ("stencil2",       "magenta_orange","Stencil 2"),
    ("sweet",          "purple_pink",   "Sweet"),

    # ── コンパクト ─────────────────────────────────────────────
    ("puffy",          "cyan_white",    "Puffy — ふっくら"),
    ("ogre",           "green_aqua",    "Ogre — オーガ"),
    ("rectangles",     "ice",           "Rectangles"),
    ("bulbhead",       "gold",          "Bulbhead"),
    ("bubble",         "cyan_white",    "Bubble — バブル"),
    ("graceful",       "purple_pink",   "Graceful — 優雅"),
    ("small_slant",    "green_aqua",    "Small Slant"),
    ("small_poison",   "blood",         "Small Poison"),
    ("cursive",        "magenta_orange","Cursive — 草書風"),
]

SEP = "─"

def gradient_text(text: str, colors: list[str]) -> str:
    lines = text.rstrip("\n").split("\n")
    n = len(colors)
    result = []
    for i, line in enumerate(lines):
        if not line.strip():
            result.append(line)
            continue
        c = colors[min(i, n - 1)]
        result.append(f"{BLD}{c}{line}{R}")
    return "\n".join(result)

def sep_line(label: str, color: str, width: int = 72) -> str:
    pad = max(0, width - len(label) - 4)
    left = pad // 2
    right = pad - left
    return f"{color}{SEP * left}  {label}  {SEP * right}{R}"

def main():
    available = set(pyfiglet.FigletFont.getFonts())
    skipped   = []

    print()
    prev_category = None

    for i, (font_name, grad_name, desc) in enumerate(FONTS):
        if font_name not in available:
            skipped.append(font_name)
            continue
        try:
            art = pyfiglet.figlet_format("MIMIC", font=font_name)
        except Exception as e:
            skipped.append(f"{font_name}({e})")
            continue

        colors = GRADIENTS[grad_name]
        label  = f"{font_name}  [{desc}]"
        label_color = f"{BLD}{colors[0]}"

        print(sep_line(label, label_color))
        print()
        print(gradient_text(art, colors))

    # フッター
    dim_teal = rgb(0, 80, 80)
    print(f"{dim_teal}{SEP * 72}{R}")
    print(f"{dim_teal}  計 {len(FONTS) - len(skipped)} フォント表示  /  スキップ: {len(skipped)}{R}")
    if skipped:
        print(f"{dim_teal}  ({', '.join(skipped)}){R}")
    print()


if __name__ == "__main__":
    main()
