# 商談動画アナライザー

オンライン商談の録画動画から、AI（Gemma 4 / Gemini API）が表情と声のトーンを100点満点でスコア化するWebアプリケーション。

## 機能

- **動画入力**: ファイルアップロード / Google Drive URL
- **AI分析**: Gemma 4 31Bモデルによる表情・声トーン分析
- **スコアリング**: 100点満点の詳細スコア + グレード判定（S/A/B/C/D）
- **改善提案**: AIによる具体的な改善ポイント
- **APIキーフォールバック**: 複数アカウント対応でクォータ制限に対応

## スクリーンショット

（準備中）

## セットアップ

### 1. リポジトリのクローン

```bash
cd /home/loser/wsl-projects/video-sales-analyzer
```

### 2. 依存パッケージのインストール

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. APIキーの設定

環境変数でAPIキーを設定:

```bash
export GEMINI_API_KEYS="your_api_key_1,your_api_key_2"
```

または `.env` ファイルを作成:

```bash
cp .env.example .env
# .envファイルを編集してAPIキーを設定
```

### 4. サーバー起動

```bash
python app.py
```

ブラウザで http://localhost:8080 にアクセス

## スコア基準のカスタマイズ

`config/score_criteria.py` を編集することで、評価基準や重み付けを自由に変更できます。

```python
# 表情の重みを60%、声トーンを40%に変更
EXPRESSION_CRITERIA = {
    "weight": 0.6,
    ...
}
VOICE_TONE_CRITERIA = {
    "weight": 0.4,
    ...
}
```

## プロジェクト構造

```
video-sales-analyzer/
├── app.py                 # メインアプリケーション
├── requirements.txt       # Python依存パッケージ
├── .env.example           # 環境変数テンプレート
├── config/
│   ├── settings.py        # アプリ設定
│   └── score_criteria.py  # スコアリング基準（カスタマイズ可能）
├── templates/
│   └── index.html         # Web UIテンプレート
├── static/
│   ├── css/
│   │   └── style.css      # スタイルシート
│   └── js/
│       └── app.js         # フロントエンドJavaScript
└── uploads/               # 一時アップロードフォルダ
```

## API エンドポイント

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/` | GET | メインページ |
| `/api/analyze/upload` | POST | 動画ファイルを分析 |
| `/api/analyze/drive` | POST | Google Drive動画を分析 |
| `/api/status` | GET | API状態確認 |

## 対応動画形式

- MP4
- AVI
- MOV
- MKV
- WebM

最大ファイルサイズ: 500MB

## 注意事項

- APIキーは絶対に公開リポジトリにコミットしないでください
- 大容量動画の分析には時間がかかる場合があります
- Google Driveの動画は「リンクを知っている全員」に共有設定が必要です
