# 顧客カレンダー機能セットアップガイド

このプロジェクトに「顧客カレンダー」機能を追加するための手順です。

## 1. 環境変数の設定
Vercelのダッシュボード、または `.env.local` に以下のFirebase設定を追加してください。

- `FIREBASE_PROJECT_ID`
- `FIREBASE_CLIENT_EMAIL`
- `FIREBASE_PRIVATE_KEY`

## 2. 認証の設定
`api/create-booking.js` は現在認証なしの簡易実装になっています。
本番環境では、Firebase Admin SDKを用いた認証ミドルウェアを導入してください。

## 3. デプロイ方法
変更をコミットし、メインブランチにプッシュすることで自動的にVercelへデプロイされます。

```bash
git add .
git commit -m "feat: 顧客カレンダー機能の雛形を追加"
git push
```
