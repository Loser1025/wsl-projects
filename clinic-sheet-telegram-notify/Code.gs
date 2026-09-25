/**
 * スプレッドシートの各タブに新しい回答行が追加されたら
 * Telegramグループ（フォーラム内の対応トピック）に通知するスクリプト。
 *
 * 予約系タブ（国内・韓国・台湾）→「予約通知」トピック
 * 問診票系タブ（問診票・問診票（韓国）・問診票（台湾））→「問診表回答」トピック
 *
 * このスプレッドシートへの書き込みはGoogle Sheets API（サービスアカウント）経由で
 * 行われるため、通常のonEdit/onFormSubmitトリガーは発火しません。
 * そのため、インストール型の「変更時（onChange）」トリガーを使い、
 * 各シートの最終行番号を記録・比較する方式で新規行を検知します。
 *
 * ==== セットアップ手順 ====
 * 1. 対象スプレッドシートを開く → 拡張機能 → Apps Script
 * 2. このファイルの内容を貼り付けて保存
 * 3. 関数選択で `initializeLastRows` を選び、1回だけ実行（既存データを「既知」として記録する）
 *    → 初回の権限承認ダイアログが出るので許可する
 * 4. 関数選択で `setupTrigger` を選び、1回だけ実行（通知トリガーを設定する）
 * 5. 関数選択で `testTelegram` を選び、1回実行してTelegramにテスト通知が届くか確認する
 *
 * ID/トークンが間違っている場合は下記の TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID を書き換えてください。
 */

// ==== 設定 ====
const TELEGRAM_BOT_TOKEN = '8784934929:AAHIi5wcyE76TqaTwba1HADe9_8AhV9XjBU';
const TELEGRAM_CHAT_ID = '-1003920328257'; // グループ「SNS連携」（スーパーグループ）

const RESERVATION_THREAD_ID = 259; // フォーラム内トピック「予約通知」
const QUESTIONNAIRE_THREAD_ID = 336; // フォーラム内トピック「問診表回答」

// シート名 → 送信先トピックIDのマッピング
const SHEET_THREAD_MAP = {
  '国内': RESERVATION_THREAD_ID,
  '韓国': RESERVATION_THREAD_ID,
  '台湾': RESERVATION_THREAD_ID,
  '問診票': QUESTIONNAIRE_THREAD_ID,
  '問診票（韓国）': QUESTIONNAIRE_THREAD_ID,
  '問診票（台湾）': QUESTIONNAIRE_THREAD_ID,
};
const SHEET_NAMES = Object.keys(SHEET_THREAD_MAP);

/**
 * インストール型トリガー（onChange）から呼ばれるエントリーポイント。
 */
function onChangeHandler(e) {
  checkForNewRows();
}

/**
 * 各シートの最終行を確認し、前回記録した行数より増えていれば
 * 増えた行ぶんだけTelegram通知を送る。
 */
function checkForNewRows() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const props = PropertiesService.getScriptProperties();

  SHEET_NAMES.forEach(function (sheetName) {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;

    const propKey = 'lastRow_' + sheetName;
    const lastKnownRow = Number(props.getProperty(propKey) || 1); // 1 = ヘッダー行のみ
    const currentLastRow = sheet.getLastRow();

    if (currentLastRow <= lastKnownRow) return;

    const numCols = Math.max(sheet.getLastColumn(), 1);
    const headerRow = sheet.getRange(1, 1, 1, numCols).getValues()[0];

    for (let row = lastKnownRow + 1; row <= currentLastRow; row++) {
      const values = sheet.getRange(row, 1, 1, numCols).getValues()[0];
      const isEmpty = values.every(function (v) { return v === '' || v === null; });
      if (isEmpty) continue;
      sendTelegramNotification(sheetName, headerRow, values);
    }

    props.setProperty(propKey, String(currentLastRow));
  });
}

/**
 * Telegramへ1件分の回答内容を通知する。
 */
function sendTelegramNotification(sheetName, headers, values) {
  let message = '📋 新しい回答が届きました（' + sheetName + '）\n\n';
  for (let i = 0; i < headers.length; i++) {
    const label = headers[i];
    if (!label) continue;
    const value = formatCellValue(values[i]);
    message += '・' + label + '： ' + value + '\n';
  }

  const url = 'https://api.telegram.org/bot' + TELEGRAM_BOT_TOKEN + '/sendMessage';
  const payload = {
    chat_id: TELEGRAM_CHAT_ID,
    message_thread_id: TELEGRAM_THREAD_ID,
    text: message,
  };
  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };

  const response = UrlFetchApp.fetch(url, options);
  const result = JSON.parse(response.getContentText());
  if (!result.ok) {
    console.error('Telegram送信失敗: ' + response.getContentText());
  }
}

/**
 * シートのセル値を通知用に読みやすい文字列へ整形する。
 * 日付・時間セルはGASでは実体がDate型（時刻のみのセルは1899-12-30が基準日になる）で
 * 返ってくるため、そのままtoString()すると "Sat Dec 30 1899 15:30:00 GMT+0900..." のように
 * 読みにくくなってしまう。ここでyyyy-MM-dd / HH:mm 形式に整形する。
 */
function formatCellValue(value) {
  if (value === '' || value === null || value === undefined) return '-';

  if (Object.prototype.toString.call(value) === '[object Date]') {
    const tz = Session.getScriptTimeZone();
    const isTimeOnly = value.getFullYear() === 1899 && value.getMonth() === 11 && value.getDate() === 30;
    if (isTimeOnly) {
      return Utilities.formatDate(value, tz, 'HH:mm');
    }
    const isMidnight = value.getHours() === 0 && value.getMinutes() === 0 && value.getSeconds() === 0;
    if (isMidnight) {
      return Utilities.formatDate(value, tz, 'yyyy-MM-dd');
    }
    return Utilities.formatDate(value, tz, 'yyyy-MM-dd HH:mm');
  }

  return value;
}

/**
 * 初回セットアップ用：現在の各シートの最終行を「既知」として記録する。
 * これを実行せずにトリガーを設定すると、既存の全行分の通知が一度に送られてしまうので注意。
 */
function initializeLastRows() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const props = PropertiesService.getScriptProperties();
  SHEET_NAMES.forEach(function (sheetName) {
    const sheet = ss.getSheetByName(sheetName);
    if (sheet) {
      props.setProperty('lastRow_' + sheetName, String(sheet.getLastRow()));
    }
  });
  console.log('初期化完了。現在の最終行を記録しました。');
}

/**
 * 初回セットアップ用：onChangeトリガーを1つ作成する。
 * 既に作成済みの場合は重複しないよう、既存の同名トリガーを削除してから作り直す。
 */
function setupTrigger() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === 'onChangeHandler') {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  ScriptApp.newTrigger('onChangeHandler')
    .forSpreadsheet(ss)
    .onChange()
    .create();

  console.log('トリガーを設定しました。');
}

/**
 * Telegram連携の動作確認用。手動実行してテストメッセージが届くか確認する。
 */
function testTelegram() {
  const url = 'https://api.telegram.org/bot' + TELEGRAM_BOT_TOKEN + '/sendMessage';
  const payload = {
    chat_id: TELEGRAM_CHAT_ID,
    message_thread_id: TELEGRAM_THREAD_ID,
    text: '✅ テスト通知：このメッセージが届けば設定は正しく動作しています。',
  };
  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };
  const response = UrlFetchApp.fetch(url, options);
  console.log(response.getContentText());
}
