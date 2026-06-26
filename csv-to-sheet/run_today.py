"""ダブルクリック1回で今日の備考を転記する"""
import json
import sys
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / 'config.json'


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {}


def main():
    cfg = load_config()
    login_id = cfg.get('login_id', '')
    login_pw = cfg.get('login_pw', '')

    if not login_id or not login_pw:
        messagebox.showerror('設定エラー', 'config.jsonにログインIDとパスワードが保存されていません。\n先にブラウザ版(run.bat)で一度実行してください。')
        return

    today = datetime.now().strftime('%Y/%m/%d')
    logs = []

    def log(msg):
        logs.append(msg)
        print(msg)

    try:
        from hibiki import login as hibiki_login, download_csv
        from core import process_and_write

        log(f'hibikiにログイン中... ({login_id})')
        session = hibiki_login(login_id, login_pw)
        log('ログイン成功')

        log(f'CSV取得中 (対象日: {today})...')
        csv_text = download_csv(session, today, today)
        log('CSV取得完了')

        count = process_and_write(csv_text, log_fn=log)

        messagebox.showinfo('完了', f'{count}件の備考を書き込みました\n対象日: {today}')

    except Exception as e:
        log(f'[ERROR] {e}')
        messagebox.showerror('エラー', str(e))


if __name__ == '__main__':
    # tkinterウィンドウを非表示にする
    root = tk.Tk()
    root.withdraw()
    main()
