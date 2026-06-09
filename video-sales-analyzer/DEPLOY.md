# デプロイガイド

## 前提条件

- GitHubアカウント
- Gemini APIキー（複数推奨）
- 動画ファイル（テスト用）

---

## オプション1: Render（推奨）

### 手順

1. **GitHubにプッシュ**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/yourusername/video-sales-analyzer.git
   git push -u origin main
   ```

2. **Renderでデプロイ**
   - https://render.com にログイン
   - "New" → "Web Service" を選択
   - GitHubリポジトリを接続
   - 設定:
     - **Name**: `video-sales-analyzer`
     - **Runtime**: Python
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 300 app:app`
   - 環境変数に `GEMINI_API_KEYS` を設定
   - "Create Web Service" をクリック

3. **アクセス**
   - `https://video-sales-analyzer.onrender.com` でアクセス

---

## オプション2: Google Cloud Run

### 手順

1. **Google Cloud SDKをインストール**
   ```bash
   # https://cloud.google.com/sdk/docs/install
   ```

2. **プロジェクト作成 & デプロイ**
   ```bash
   # プロジェクトIDを設定
   export PROJECT_ID=your-project-id
   gcloud config set project $PROJECT_ID

   # コンテナをビルド & デプロイ
   gcloud run deploy video-sales-analyzer \
     --source . \
     --platform managed \
     --region asia-northeast1 \
     --allow-unauthenticated \
     --set-env-vars="GEMINI_API_KEYS=your_key_1,your_key_2" \
     --memory 2Gi \
     --timeout 300
   ```

3. **アクセス**
   - 発行されたURLでアクセス

---

## オプション3: Vercel

### 手順

1. **Vercel CLIをインストール**
   ```bash
   npm i -g vercel
   ```

2. **デプロイ**
   ```bash
   cd /home/loser/wsl-projects/video-sales-analyzer
   vercel
   ```

3. **環境変数設定**
   ```bash
   vercel env add GEMINI_API_KEYS
   ```

4. **再デプロイ**
   ```bash
   vercel --prod
   ```

---

## オプション4: 自宅サーバー / VPS

### 手順

1. **サーバーにSSH接続**
   ```bash
   ssh user@your-server
   ```

2. **依存パッケージインストール**
   ```bash
   sudo apt update
   sudo apt install python3 python3-pip python3-venv ffmpeg nginx
   ```

3. **アプリケーションデプロイ**
   ```bash
   git clone https://github.com/yourusername/video-sales-analyzer.git
   cd video-sales-analyzer
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **環境変数設定**
   ```bash
   echo "GEMINI_API_KEYS=your_key_1,your_key_2" > .env
   ```

5. **systemdサービス作成**
   ```bash
   sudo nano /etc/systemd/system/video-analyzer.service
   ```
   ```ini
   [Unit]
   Description=Video Sales Analyzer
   After=network.target

   [Service]
   User=www-data
   WorkingDirectory=/home/user/video-sales-analyzer
   Environment="PATH=/home/user/video-sales-analyzer/.venv/bin"
   EnvironmentFile=/home/user/video-sales-analyzer/.env
   ExecStart=/home/user/video-sales-analyzer/.venv/bin/gunicorn --bind 127.0.0.1:8080 --workers 2 --timeout 300 app:app

   [Install]
   WantedBy=multi-user.target
   ```

6. **nginx設定**
   ```bash
   sudo nano /etc/nginx/sites-available/video-analyzer
   ```
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://127.0.0.1:8080;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           client_max_body_size 500M;
       }
   }
   ```

7. **起動**
   ```bash
   sudo systemctl enable video-analyzer
   sudo systemctl start video-analyzer
   sudo ln -s /etc/nginx/sites-available/video-analyzer /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   ```

---

## 注意事項

- **APIキー**: 絶対にコードにハードコードしないこと
- **ファイルサイズ**: 500MB制限（nginx等の設定で調整可能）
- **タイムアウト**: 動画分析には時間がかかるため、タイムアウトを長めに設定
- **メモリ**: 動画処理には2GB以上のメモリを推奨
