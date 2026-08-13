# Google Slides 編集ツール セットアップガイド

AIエージェントがGoogleスライドのデザインを編集するためのツール（`wsl-projects/slides_design_tool.py`）を使用するための準備手順です。

## 1. Google Cloud プロジェクトの準備

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセスします。
2. プロジェクトを選択するか、新規作成します。
3. **APIとサービス > ライブラリ** から以下を有効にします。
    - Google Slides API
    - Google Drive API
4. **APIとサービス > 認証情報** から、以下のいずれかを作成します。

### A. サービスアカウント（推奨：サーバー・自動処理用）
- 「認証情報を作成」 > 「サービスアカウント」を選択。
- 適当な名前を付け、「完了」をクリック。
- 作成されたアカウントの「キー」タブから「鍵を追加」 > 「新しい鍵を作成」 > 「JSON」を選択してダウンロードします。
- ダウンロードしたファイルを `/home/loser/wsl-projects/slides_design_tool/credentials.json` として保存します。
- **重要**: 編集したいGoogleスライドの右上の「共有」ボタンから、サービスアカウントのメールアドレス（`xxx@xxx.iam.gserviceaccount.com`）を「編集者」として追加してください。

### B. OAuth 2.0 クライアント ID（個人アカウント用・対話型）
- 「認証情報を作成」 > 「OAuth クライアント ID」を選択。
- アプリケーションの種類を「デスクトップ アプリ」にします。
- JSONをダウンロードし、`/home/loser/wsl-projects/slides_design_tool/credentials.json` として保存します。
- 初回実行時にブラウザで認証を求められます。

## 2. ライブラリのインストール

このディレクトリには準備済みのvenvがあります。以下のコマンドで有効化するか、venvのpythonを直接使います。

```bash
cd /home/loser/wsl-projects/slides_design_tool
source venv/bin/activate
# または
./venv/bin/python your_script.py
```

（未セットアップの場合の再構築コマンド）
```bash
python3 -m venv venv
./venv/bin/pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
```

## 3. ツールの使用方法

`GoogleSlidesTool` クラスを使用して、Pythonスクリプトから簡単に操作できます。

```python
from slides_design_tool import GoogleSlidesTool

# 初期化（credentials.jsonがこのディレクトリにある場合）
tool = GoogleSlidesTool(credentials_path='credentials.json')

# 特定のスライドのテキストを置換
SLIDE_ID = 'あなたのスライドID'
tool.replace_text(SLIDE_ID, '旧テキスト', '新テキスト')

# スライド情報の取得
presentation = tool.get_presentation(SLIDE_ID)
print(f"Title: {presentation.get('title')}")
```

## 4. AIエージェントへの指示

AIエージェントに編集を依頼する際は、以下のように伝えてください。
「`wsl-projects/slides_design_tool.py` を使って、スライド `[ID]` の `[テキスト]` を `[新しいテキスト]` に変更して。」
