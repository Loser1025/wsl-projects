"""ログインページのHTML構造を確認するデバッグスクリプト"""
import requests
import re

HIBIKI_BASE = 'https://hibiki.leaduplus.pro'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
}

session = requests.Session()
session.headers.update(HEADERS)

print('GETリクエスト送信中...')
res = session.get(f'{HIBIKI_BASE}/debt/login', timeout=30)
print(f'ステータス: {res.status_code}')
print(f'最終URL: {res.url}')
print(f'エンコーディング: {res.encoding}')
print()

# _token を探す
tokens = re.findall(r'name=["\']_token["\'].*?value=["\']([^"\']+)["\']', res.text, re.IGNORECASE)
print(f'_token (パターン1): {tokens}')
tokens2 = re.findall(r'value=["\']([^"\']+)["\'].*?name=["\']_token["\']', res.text, re.IGNORECASE)
print(f'_token (パターン2): {tokens2}')

# input要素を全部表示
inputs = re.findall(r'<input[^>]+>', res.text, re.IGNORECASE)
print(f'\ninput要素 ({len(inputs)}個):')
for inp in inputs:
    print(' ', inp[:200])

# HTMLの最初の2000文字
print('\n--- HTML先頭2000文字 ---')
print(res.text[:2000])
