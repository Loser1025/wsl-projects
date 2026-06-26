"""
でいりスーパーALL シート デザイン適用（拠点別列配色）
3拠点（こんす / すたいる / かなで）を列単位で独立配色
書式のみ変更 ── 数式・値には一切触れない

シート構造（確認済み 2026-06-04）:
  行1   : 空白
  行2   : 表1ヘッダー  [こんす|A-J] [すたいる|L-O] [かなで|Q-T]
  行3-37: 表1データ
  行38  : 空白
  行39  : 表1合計
  行40  : 空白
  行41  : 表2ヘッダー  (提案日ベース、同列構成)
  行42-76: 表2データ
  行77  : 空白
  行78  : 表2合計

列グループ（0-indexed）:
  こんす  : A-J  = 0〜9
  (空)   : K    = 10
  すたいる: L-O  = 11〜14
  (空)   : P    = 15
  かなで  : Q-T  = 16〜19
"""

from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

SA_PATH = Path(__file__).parent / 'sa_credentials.json'
SPREADSHEET_ID = '1QBs3Z9y0i8eYLghtw87BEkvENuB-yr5E0wGbWw4Crr0'
SHEET_NAME     = 'でいりスーパーALL'
SHEET_ID       = 1963119170  # gid固定

# ── 行範囲（0-indexed） ──────────────────────────────────────────────────────
T1_HEADER  = 1          # 行2
T1_DATA_S  = 2          # 行3
T1_DATA_E  = 37         # 行37 (exclusive)
T1_GOKEI   = 38         # 行39

T2_HEADER  = 40         # 行41
T2_DATA_S  = 41         # 行42
T2_DATA_E  = 76         # 行76 (exclusive)
T2_GOKEI   = 77         # 行78

# ── 列グループ（0-indexed, end=exclusive） ────────────────────────────────────
GRP_KONSU  = (0,  10)   # A-J
GRP_SEP1   = (10, 11)   # K（セパレーター）
GRP_STYLE  = (11, 15)   # L-O
GRP_SEP2   = (15, 16)   # P（セパレーター）
GRP_KANADE = (16, 20)   # Q-T

TOTAL_COLS = 20


# ── カラーパレット ─────────────────────────────────────────────────────────────
def rgb(r, g, b):
    return {'red': r / 255, 'green': g / 255, 'blue': b / 255}


WHITE = rgb(255, 255, 255)

# こんす：インディゴ系
KONSU = {
    'header_bg':  rgb(26,  35, 126),   # Indigo 900
    'header_fg':  WHITE,
    'even_bg':    rgb(232, 234, 246),  # Indigo 50
    'odd_bg':     rgb(197, 202, 233),  # Indigo 100
    'data_fg':    rgb(26,  35, 126),
    'border':     rgb(57,  73, 171),   # Indigo 700
    'gokei_bg':   rgb(40,  53, 147),   # Indigo 800
}

# すたいる：エメラルドグリーン系
STYLE = {
    'header_bg':  rgb(27,  94,  32),   # Green 900
    'header_fg':  WHITE,
    'even_bg':    rgb(232, 245, 233),  # Green 50
    'odd_bg':     rgb(200, 230, 201),  # Green 100
    'data_fg':    rgb(27,  94,  32),
    'border':     rgb(56,  142,  60),  # Green 700
    'gokei_bg':   rgb(46,  125,  50),  # Green 800
}

# かなで（奏）：ディープオレンジ系
KANADE = {
    'header_bg':  rgb(230,  81,   0),  # Deep Orange 800
    'header_fg':  WHITE,
    'even_bg':    rgb(251, 233, 231),  # Deep Orange 50
    'odd_bg':     rgb(255, 204, 188),  # Deep Orange 100
    'data_fg':    rgb(191,  54,  12),  # Deep Orange 900
    'border':     rgb(244,  81,  30),  # Deep Orange 600
    'gokei_bg':   rgb(191,  54,  12),  # Deep Orange 900
}

# セパレーター列
SEP_BG = rgb(250, 250, 250)

# 合計行（全列共通）
GOKEI_BG     = rgb(33,  33,  33)   # Near Black
GOKEI_FG     = WHITE
GOKEI_BORDER = rgb(0,   0,   0)


# ── APIリクエスト生成ヘルパー ─────────────────────────────────────────────────
def grange(r0, r1, c0, c1):
    """GridRange（0-indexed, end exclusive）"""
    return {
        'sheetId': SHEET_ID,
        'startRowIndex': r0, 'endRowIndex': r1,
        'startColumnIndex': c0, 'endColumnIndex': c1,
    }


def repeat_cell(r0, r1, c0, c1, bg, fg, bold=False, font_size=10):
    return {
        'repeatCell': {
            'range': grange(r0, r1, c0, c1),
            'cell': {
                'userEnteredFormat': {
                    'backgroundColor': bg,
                    'textFormat': {
                        'foregroundColor': fg,
                        'bold': bold,
                        'fontSize': font_size,
                        'fontFamily': 'Arial',
                    },
                    'verticalAlignment': 'MIDDLE',
                    'horizontalAlignment': 'CENTER',
                }
            },
            'fields': (
                'userEnteredFormat('
                'backgroundColor,textFormat,'
                'verticalAlignment,horizontalAlignment'
                ')'
            ),
        }
    }


def update_borders(r0, r1, c0, c1, color,
                   outer='SOLID_MEDIUM', inner='SOLID'):
    def bdr(style):
        return {'style': style, 'colorStyle': {'rgbColor': color}}

    return {
        'updateBorders': {
            'range': grange(r0, r1, c0, c1),
            'top':    bdr(outer),
            'bottom': bdr(outer),
            'left':   bdr(outer),
            'right':  bdr(outer),
            'innerHorizontal': bdr(inner),
            'innerVertical':   bdr(inner),
        }
    }


# ── フォーマットリクエスト構築 ────────────────────────────────────────────────
def build_group_requests(header_row, data_s, data_e, grp, theme):
    """1グループ（1列範囲）の書式リクエストを生成"""
    c0, c1 = grp
    reqs = []

    # ヘッダー行
    reqs.append(repeat_cell(
        header_row, header_row + 1, c0, c1,
        theme['header_bg'], theme['header_fg'],
        bold=True, font_size=11,
    ))

    # データ行（ゼブラストライプ）
    for row_i in range(data_s, data_e):
        bg = theme['even_bg'] if (row_i % 2 == 0) else theme['odd_bg']
        reqs.append(repeat_cell(
            row_i, row_i + 1, c0, c1,
            bg, theme['data_fg'],
        ))

    # 外枠ボーダー（グループ全体を太枠で囲む）
    reqs.append(update_borders(
        header_row, data_e, c0, c1,
        theme['border'],
        outer='SOLID_MEDIUM',
        inner='SOLID',
    ))

    return reqs


def build_gokei_requests(row_i, c0, c1, theme):
    """合計行の書式リクエスト"""
    reqs = []
    reqs.append(repeat_cell(
        row_i, row_i + 1, c0, c1,
        theme['gokei_bg'], WHITE,
        bold=True, font_size=11,
    ))
    reqs.append(update_borders(
        row_i, row_i + 1, c0, c1,
        theme['border'],
        outer='SOLID_MEDIUM',
    ))
    return reqs


def build_sep_requests(header_row, data_e, c0, c1):
    """セパレーター列の書式リクエスト"""
    return [repeat_cell(
        header_row, data_e, c0, c1,
        SEP_BG, SEP_BG,
    )]


def build_gokei_row_all(row_i):
    """合計行を全列にわたってダークで統一"""
    reqs = [
        repeat_cell(
            row_i, row_i + 1, 0, TOTAL_COLS,
            GOKEI_BG, GOKEI_FG,
            bold=True, font_size=11,
        ),
        update_borders(
            row_i, row_i + 1, 0, TOTAL_COLS,
            GOKEI_BORDER,
            outer='SOLID_MEDIUM',
        ),
    ]
    return reqs


def build_all_requests():
    reqs = []

    for header_row, data_s, data_e, gokei_row in [
        (T1_HEADER, T1_DATA_S, T1_DATA_E, T1_GOKEI),
        (T2_HEADER, T2_DATA_S, T2_DATA_E, T2_GOKEI),
    ]:
        # こんす
        reqs += build_group_requests(header_row, data_s, data_e, GRP_KONSU, KONSU)
        # セパレーター
        reqs += build_sep_requests(header_row, data_e, *GRP_SEP1)
        # すたいる
        reqs += build_group_requests(header_row, data_s, data_e, GRP_STYLE, STYLE)
        # セパレーター
        reqs += build_sep_requests(header_row, data_e, *GRP_SEP2)
        # かなで
        reqs += build_group_requests(header_row, data_s, data_e, GRP_KANADE, KANADE)
        # 合計行（全列）
        reqs += build_gokei_row_all(gokei_row)

    return reqs


# ── メイン ────────────────────────────────────────────────────────────────────
def main():
    print('Sheets API 接続中...')
    creds = service_account.Credentials.from_service_account_file(
        str(SA_PATH),
        scopes=['https://www.googleapis.com/auth/spreadsheets'],
    )
    service = build('sheets', 'v4', credentials=creds)

    requests = build_all_requests()
    print(f'リクエスト数: {len(requests)}')

    CHUNK = 500
    total = len(requests)
    for i in range(0, total, CHUNK):
        chunk = requests[i:i + CHUNK]
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={'requests': chunk},
        ).execute()
        print(f'  適用完了: {min(i + CHUNK, total)}/{total}')

    print('\nデザイン適用完了！')
    print('  こんす  → インディゴ（青）')
    print('  すたいる → エメラルドグリーン（緑）')
    print('  かなで  → ディープオレンジ（橙）')


if __name__ == '__main__':
    main()
