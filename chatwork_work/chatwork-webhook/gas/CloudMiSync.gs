/**
 * 各日付シート(MM/DD)のI列(処理者)に「未締結」と入っている案件を、
 * 「クラウド未」シートへ横断的に集約・追記していく。
 * 一度追加した案件(message_id基準)は重複追加しない。
 */

const CLOUD_MI_SHEET_NAME = 'クラウド未';
const CLOUD_MI_STATUS_VALUE = '未締結';

/** 「クラウド未」シートが無ければヘッダー付きで新規作成して返す */
function getOrCreateCloudMiSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(CLOUD_MI_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(CLOUD_MI_SHEET_NAME);
    sheet.getRange(1, 1, 1, 11).setValues([[
      'message_id', '日付', '送信者', '内容', '面談対応(先生)', '対応者(CS)',
      '依頼者名', 'Lステ友達情報', '処理者', '処理完了', '元シート',
    ]]);
  }
  return sheet;
}

/**
 * 全日付シートをスキャンし、I列(処理者)が「未締結」の案件を
 * 「クラウド未」シートへ追記する（message_idで重複除外）
 * @return {{added: number, scannedSheets: number}}
 */
function syncUnresolvedToCloudMi() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const cloudSheet = getOrCreateCloudMiSheet_();

  const existingLastRow = cloudSheet.getLastRow();
  const existingIds = {};
  if (existingLastRow >= 2) {
    cloudSheet.getRange(2, 1, existingLastRow - 1, 1).getValues().forEach(([id]) => {
      if (id) existingIds[String(id)] = true;
    });
  }

  const sheetNames = getDateSheetNames_();
  const newRows = [];

  sheetNames.forEach((sheetName) => {
    if (sheetName === CLOUD_MI_SHEET_NAME) return;
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) return;

    // A:J = message_id,日付,送信者,内容,面談対応(先生),対応者(CS),依頼者名,Lステ友達情報,処理者,処理完了
    const data = sheet.getRange(2, 1, lastRow - 1, 10).getValues();
    data.forEach((row) => {
      const messageId = row[0];
      const shoriSha = row[8]; // I列=処理者
      if (!messageId || existingIds[String(messageId)]) return;
      if (String(shoriSha || '').trim() === CLOUD_MI_STATUS_VALUE) {
        newRows.push(row.concat([sheetName]));
        existingIds[String(messageId)] = true;
      }
    });
  });

  if (newRows.length > 0) {
    const startRow = cloudSheet.getLastRow() + 1;
    cloudSheet.getRange(startRow, 1, newRows.length, 11).setValues(newRows);
  }

  return { added: newRows.length, scannedSheets: sheetNames.length };
}

/**
 * 初回だけ手動実行する。syncUnresolvedToCloudMi用の既存トリガーだけを
 * 消してから15分毎のトリガーを張り直す（pollChatwork等、他の関数の
 * トリガーには触れない）
 */
function setupCloudMiSyncTrigger() {
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === 'syncUnresolvedToCloudMi')
    .forEach((t) => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger('syncUnresolvedToCloudMi')
    .timeBased()
    .everyMinutes(15)
    .create();

  console.log('未締結→クラウド未の同期トリガーを15分毎に設定しました');
}
