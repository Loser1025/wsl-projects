# Calendar Integration

Google Calendar APIおよびFirebase Admin SDKを使用した統合が完了しました。

## 実装内容
- `api/get-availability.js`: Google CalendarのFreeBusy APIを使用して空き状況を取得。
- `api/create-booking.js`: Firebase Admin SDKを使用してFirestoreに予約を保存。
- `src/components/Calendar/CustomerCalendar.jsx`: 予約UIコンポーネント。

## 必要な環境変数の設定
Vercelの環境変数、またはローカルの`.env`ファイルに以下を設定してください。

- `GOOGLE_SERVICE_ACCOUNT_KEY`: Google CloudサービスアカウントのJSONキー文字列
- `FIREBASE_SERVICE_ACCOUNT_KEY`: Firebase AdminサービスアカウントのJSONキー文字列

## 依存関係
`googleapis` と `firebase-admin` をインストール済みです。
`npm install` を実行してください。

## フロントエンド統合手順
作成された `src/components/Calendar/CustomerCalendar.jsx` をアプリケーションに組み込むには、Reactエントリーポイント（例: `src/index.js`）にて以下のようにマウントしてください。

```javascript
import React from 'react';
import ReactDOM from 'react-dom/client';
import CustomerCalendar from './components/Calendar/CustomerCalendar';

const root = ReactDOM.createRoot(document.getElementById('calendar-root'));
root.render(<CustomerCalendar />);
```

`index.html` 内の任意の場所に、以下のコンテナを配置してください。

```html
<div id="calendar-root"></div>
```
