from flask import Flask, render_template, request, jsonify
import json, threading
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

CONFIG_PATH = Path(__file__).parent / 'config.json'

_status = {
    'running': False,
    'log': [],
}


def load_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {}


def save_config(data):
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


@app.route('/')
def index():
    config = load_config()
    today_iso = datetime.now().strftime('%Y-%m-%d')
    return render_template('index.html',
                           config=json.dumps(config, ensure_ascii=False),
                           today_iso=today_iso)


@app.route('/run', methods=['POST'])
def run():
    global _status
    if _status['running']:
        return jsonify({'error': '実行中です。完了後に再実行してください。'})

    data = request.json
    date = data.get('date', datetime.now().strftime('%Y/%m/%d'))
    login_id = data.get('login_id', '')
    login_pw = data.get('login_pw', '')

    if not login_id or not login_pw:
        return jsonify({'error': 'ログインIDとパスワードを入力してください。'})

    # 認証情報を保存
    cfg = load_config()
    cfg['login_id'] = login_id
    cfg['login_pw'] = login_pw
    save_config(cfg)

    _status = {'running': True, 'log': []}

    def _thread():
        from hibiki import login as hibiki_login, download_csv
        from core import process_and_write

        def log(msg):
            _status['log'].append(msg)

        try:
            log(f'hibikiにログイン中... ({login_id})')
            session = hibiki_login(login_id, login_pw)
            log('ログイン成功')

            log(f'CSV取得中 (対象日: {date})...')
            csv_text = download_csv(session, date, date)
            log('CSV取得完了')

            process_and_write(csv_text, log_fn=log)

        except Exception as e:
            log(f'[ERROR] {str(e)}')
        finally:
            _status['running'] = False

    threading.Thread(target=_thread, daemon=True).start()
    return jsonify({'ok': True})


@app.route('/status')
def status():
    return jsonify(_status)


if __name__ == '__main__':
    print('=' * 50)
    print('備考転記ツール')
    print('ブラウザで http://localhost:5100 を開いてください')
    print('=' * 50)
    app.run(port=5100, debug=False)
