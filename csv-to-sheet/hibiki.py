"""
hibiki へのログインとCSVダウンロードを担当
requests.Session でCookieを自動管理
"""
import re
import requests

HIBIKI_BASE = 'https://hibiki.leaduplus.pro'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
}


def _csrf(html: str) -> str:
    m = re.search(r'name="_token"[^>]*value="([^"]+)"', html)
    if not m:
        raise ValueError('CSRFトークンの取得に失敗しました')
    return m.group(1)


def login(login_id: str, login_pw: str) -> requests.Session:
    """ログインしてセッションを返す"""
    session = requests.Session()
    session.headers.update(HEADERS)

    page = session.get(f'{HIBIKI_BASE}/debt/login', timeout=30)
    page.raise_for_status()
    token = _csrf(page.text)

    login_res = session.post(
        f'{HIBIKI_BASE}/debt/login',
        data={'_token': token, 'name': login_id, 'password': login_pw},
        allow_redirects=True,
        timeout=30,
    )

    # ログイン失敗チェック（ログインフォームが再表示されたら失敗）
    if 'name="_token"' in login_res.text and '/debt/login' in login_res.url:
        raise ValueError('ログイン失敗: IDまたはパスワードが違います')

    return session


def download_csv(session: requests.Session, date_from: str, date_to: str) -> str:
    """CSVを取得してテキストで返す"""
    search_res = session.get(f'{HIBIKI_BASE}/debt/consulter/list/search', timeout=30)
    search_res.raise_for_status()
    token = _csrf(search_res.text)

    csv_res = session.post(
        f'{HIBIKI_BASE}/debt/consulter/list/outputContactHistoryCsv',
        data={
            '_token': token,
            'first_call_date_from': date_from,
            'first_call_date_to': date_to,
            'except_test_inquiry': '1',
            'limit': '500',
            'total_count': '0',
        },
        timeout=60,
    )
    csv_res.raise_for_status()

    # エンコーディング判定
    csv_res.encoding = csv_res.apparent_encoding or 'utf-8'
    return csv_res.text
