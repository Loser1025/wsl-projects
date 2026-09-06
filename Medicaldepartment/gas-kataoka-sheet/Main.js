/**
 * スプレッドシートの拡張機能から作られたプロジェクト（コンテナバインド）。
 * このスプレッドシートを開いたときにメニューが表示される。
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('BQ集計')
    .addItem('すべてまとめて更新', 'runAll')
    .addItem('1時間ごとの自動更新を設定', 'setupHourlyTrigger')
    .addToUi();
}

function syncOverallSummary() {
  syncKeiyakubiBaseSummary();
  syncHankyoubiBaseSummary();
}

function runAll() {
  syncOverallSummary();
  syncShohinBetsu();
  syncKeiyakuKara3kagetsu();
  syncHankyoKara3kagetsu();
  // サンキュー架電の対応率は各表の契約数を参照するため、必ず最後に実行する。
  syncSankyuKaiden();
  writeLastUpdatedAt_();
}

// 「全体」シートのA1に最終更新日時を書き込む。
function writeLastUpdatedAt_() {
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(CONFIG.OVERALL_SHEET_NAME);
  sheet.getRange(1, 1).setValue('更新日時: ' + Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy/MM/dd HH:mm:ss'));
}
