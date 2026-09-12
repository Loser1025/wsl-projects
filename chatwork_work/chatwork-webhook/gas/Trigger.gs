/**
 * Chatwork -> Sheets (Vercel /api/run) を叩くためのGASトリガースクリプト。
 * スプレッドシートの「拡張機能 > Apps Script」に貼り付けて使う。
 *
 * 使い方:
 *   1. このファイルの中身をApps Scriptエディタに貼り付ける
 *   2. setPollSecret 内のプレースホルダーを実際のPOLL_SECRETの値に書き換えて一度だけ実行する
 *      （実行後、書き換えた値は元のプレースホルダーに戻すか関数ごと削除してよい。
 *       値はスクリプトのプロパティストアに保存されるので、コード上に残す必要はない）
 *   3. setupTriggers を一度だけ手動実行する（外部リクエストの許可を求められるので承認する）
 *   4. 以降は毎分 pollChatwork が、毎日0:05頃に dailyReset が自動実行される
 */

const VERCEL_URL = 'https://chatwork-webhook-kappa.vercel.app/api/run';

function getPollSecret_() {
  const secret = PropertiesService.getScriptProperties().getProperty('POLL_SECRET');
  if (!secret) {
    throw new Error('POLL_SECRET が未設定です。setPollSecret を先に実行してください。');
  }
  return secret;
}

/** 初回だけ手動実行する。プレースホルダーを実際の値に書き換えてから実行すること */
function setPollSecret() {
  PropertiesService.getScriptProperties().setProperty('POLL_SECRET', 'NKuCPk8LHUgP1FX1B9AaGVQGvIzXKFoB');
  console.log('POLL_SECRET を保存しました');
}

function pollChatwork() {
  const res = UrlFetchApp.fetch(`${VERCEL_URL}?key=${getPollSecret_()}&job=poll`, {
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    console.error(`poll failed: ${res.getResponseCode()} ${res.getContentText()}`);
  } else {
    console.log(res.getContentText());
  }
}

function dailyReset() {
  const res = UrlFetchApp.fetch(`${VERCEL_URL}?key=${getPollSecret_()}&job=reset`, {
    muteHttpExceptions: true,
  });
  if (res.getResponseCode() !== 200) {
    console.error(`reset failed: ${res.getResponseCode()} ${res.getContentText()}`);
  } else {
    console.log(res.getContentText());
  }
}

/** 初回だけ手動実行する。既存トリガーを消してから毎分/毎日のトリガーを張り直す */
function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach((t) => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger('pollChatwork').timeBased().everyMinutes(1).create();

  ScriptApp.newTrigger('dailyReset')
    .timeBased()
    .atHour(0)
    .nearMinute(5)
    .everyDays(1)
    .create();

  console.log('トリガーを設定しました: pollChatwork(毎分), dailyReset(毎日0:05頃)');
}
