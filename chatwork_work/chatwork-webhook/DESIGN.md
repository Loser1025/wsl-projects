# Chatwork → Sheets リアルタイム化 設計書（ドラフト）

## 0. 背景・目的

現行の `chatwork-to-sheet/export_to_sheet.py` は GitHub Actions の cron（毎時。
実際には数時間単位で発火が遅延・スキップされることが判明済み）で
Chatwork APIをポーリングし、新着メッセージをGoogleスプレッドシートに書き出している。
リアクション取得のために非公式の内部API（`load_chat.php`等）に依存しており、
Chatwork側の仕様変更・Cookie失効・ログイン不安定化などのリスクを抱えている。

**方針転換**: リアクション取得を完全に諦める代わりに、公式APIの範囲だけで完結する
準リアルタイム方式に作り替える。ポーリング頻度を大幅に上げることで、
体感としてはリアルタイムに近い更新を実現する。

## 1. 決定事項（ユーザーと合意済み）

- ホスティング先: **Vercel Functions**
- リアクション列: **完全に廃止**（取得しない・書き込まない）
- Cookie・Playwright・内部API依存は全廃し、公式REST APIのみで完結させる

## 2. 方式の選定: Webhook（Plan A）は現時点で断念、Plan Bを採用

### 2.1 Plan A: Chatwork公式Webhook — 現時点でブロック中

調査の結果、以下の理由で**今すぐには着手できない**ことが判明した。

1. Webhookの登録はAPIではなく**Chatwork管理画面からの手動設定のみ**
   （登録用のREST APIは存在しない。実際に`/webhooks`等を叩いても404で確認済み）
2. 管理画面へのアクセス自体に**組織管理者の承認**が必要
   （t.hirotaアカウントで開くと「APIの利用申請」ページにリダイレクトされる）
3. 現在使っているAPIトークンは別アカウント（阿部翔平さん, s.abe@hibiki-law.or.jp）で
   発行されたものと判明。このアカウントなら承認済みの可能性があるが、
   ログイン情報が無いため未確認

→ 誰か（阿部さんかt.hirotaさんの組織管理者）の手動対応待ちになるため、
**いったん保留し、Plan Bで先に効果を出す**。承認が取れ次第、Plan Aへ移行してもよい
（Plan Bの実装はPlan Aに転用しやすい設計にしておく＝下記参照）。

### 2.2 Plan B（採用）: 外部cronサービス → Vercel Functionを高頻度ポーリング

Chatwork側への登録作業を一切必要とせず、同等の体感速度を実現する方式。

- 外部の無料cronサービス（cron-job.org等。GitHub Actions版で使ったのと同じ発想）から
  Vercel FunctionのURLを**1分間隔でHTTP GET**する
- Vercel自体のネイティブCron機能は使わない
  （Hobbyプランはネイティブcronが1日1回までという制限があるため。
  外部から普通の関数呼び出しとして叩く分にはこの制限を受けない）
- Function内部の処理は現行の`export_to_sheet.py`のロジックとほぼ同じ
  （`GET /rooms/{id}/messages`をポーリングしてmessage_id差分を追記）だが、
  リアクション取得部分（Cookie・Playwright・内部API）を丸ごと削除する

## 3. 現行方式との比較

| 項目 | 現行（GitHub Actions） | Plan B（Vercel + 外部cron） | Plan A（Webhook・将来） |
|---|---|---|---|
| トリガー | GitHub Actions cron（毎時、実際は数時間ズレる） | 外部cron → Vercel Functionを1分毎に叩く | ChatworkからのHTTP POST（即時） |
| 体感速度 | 数時間に1回 | 1分に1回（準リアルタイム） | 即時 |
| 事前の手動登録 | 不要 | 不要 | **必須**（管理画面、承認待ち） |
| 実行環境 | GitHub-hosted runner + Dockerコンテナ | Vercel Function（軽量） | Vercel Function（軽量） |
| リアクション | 内部API + Cookie（非公式・不安定） | ❌ 廃止 | ❌ 廃止 |
| メッセージ編集 | 非対応 | 非対応（ポーリングなので次回取得時に上書き検討要） | `message_updated`で対応可 |
| 認証情報 | CW_API_TOKEN, CW_EMAIL/PASSWORD, Cookie, Google SA | CW_API_TOKEN, Google SA のみ | CW_API_TOKEN, Google SA, Webhookトークン |
| コスト | GitHub Actions無料枠 | Vercel Hobby無料枠 + 外部cron無料枠 | 同左 |

## 4. Plan B: Vercel Function の設計

### 4.1 エンドポイント構成

```
/api/poll             GET   外部cronから1分毎に呼ばれる。新着メッセージを取り込む
/api/daily-reset      GET   外部cronから1日1回（JST 0:00頃）呼ばれる。前日分をクリア
```

（`/api/daily-reset`もVercelネイティブcronではなく外部cronから叩く統一方式にする。
Hobbyプランのネイティブcron制限を気にしなくて済むため）

### 4.2 `/api/poll` の処理フロー

現行`export_to_sheet.py`の`main()`からリアクション関連を全て除いたもの。

1. シートのA:B列を読み、`message_id_to_row` / `today_existing_ids` を構築（現行と同じ）
2. 日付が変わっていたら前日分を削除（現行の`daily reset`ロジックをそのまま流用）
3. `GET /rooms/{room_id}/messages?force=1` で最新100件取得
4. 本日分だけフィルタ
5. 未追記のものだけ抽出し、本文から`面談対応(先生)`/`対応者(CS)`を正規表現抽出
6. 本文中のURLをtextFormatRunsでリンク化（現行ロジック流用）
7. `next_row`を自前計算して`values.update`で明示範囲に書き込み（`values.append`は使わない）
8. 簡易な認証: 外部cronからのリクエストにシークレットクエリパラメータ
   （例: `?key=xxxx`）を付与し、一致しなければ401（誰でも叩けるURLにしないため）

### 4.3 `/api/daily-reset` の処理フロー

現行の「日付が変わった最初の実行で前日分を削除」を独立関数として切り出し、
`/api/poll`側の判定に加えて、こちらでも保険的に日次で叩く
（`/api/poll`が万一長時間動かなくても日次リセットだけは走るように）。

**I列（処理完了チェック）だけ特別扱いする**:
1. まず全体（A2:Z, 現在のグリッド行数まで）を`values.clear()`で単純リセット
   （チェックボックスの入力規則自体は消えない。従来通り）
2. 続けてI列だけ、`values.update()`で明示的に`FALSE`を敷き詰める
   （クリアしただけの「空セル」ではなく、確実に`FALSE`という値を入れる）
   - 対象範囲はシートの現在の実際の行数（`gridProperties.rowCount`）を都度取得して使う
     （数千行を想定。100000のような固定値で無駄なリクエストを送らない）

### 4.4 実装言語

既存ロジック（正規表現・Sheets書き込み）はPython実装済み。Vercelは
Python Serverless Functions（`api/*.py`）をサポートしているため、
書き直しコストを抑えるためPythonのまま移植する。

## 5. 環境変数（Vercel）

| 変数名 | 用途 |
|---|---|
| `CW_API_TOKEN` | メッセージ取得・メンバー名解決 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Sheets書き込み用サービスアカウント |
| `SPREADSHEET_ID` / `SHEET_NAME` | 書き込み先 |
| `POLL_SECRET` | 外部cronからのリクエストを認証するシークレット |

## 6. 移行手順（案）

1. Vercelプロジェクトを作成し、`/api/poll` `/api/daily-reset` を実装・デプロイ
2. cron-job.org等に登録し、`/api/poll`を1分毎、`/api/daily-reset`を1日1回叩くよう設定
3. しばらく現行GitHub Actions方式と並走させ、両方が同じデータを書けているか目視比較
4. 問題なければGitHub Actionsのscheduledトリガーを停止（ワークフロー自体は
   `workflow_dispatch`のみ残す。Playwright/内部APIリアクション取得コードも削除）
5. （将来）阿部さんアカウントでの管理画面アクセスが確認でき次第、Plan A（Webhook）へ
   段階的に移行する。`/api/webhook`エンドポイントを追加し、`/api/poll`の頻度を落とす
   or 廃止する

## 7. リスク・未解決事項

- ポーリング間隔（何分にするか）は外部cronサービスの無料枠上限と要相談
  （cron-job.orgは1分間隔まで無料で対応可能な想定だが要確認）
- `force=1`は常に最新100件を返す仕様のため、ポーリング間隔中に101件以上
  新規メッセージが来ると取りこぼす可能性がある（現行方式でも同じ制約が既にある）
- Vercel Functionの実行時間・呼び出し回数がHobbyプランの無料枠上限に収まるか確認要
  （1分間隔・軽量処理なら十分収まる想定）
