/**
 * スプレッドシートの拡張機能から作られたプロジェクト（コンテナバインド）。
 * このスプレッドシートを開いたときにメニューが表示される。
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('BQ集計')
    .addItem('契約日ベースを更新', 'syncKeiyakubiBaseSummary')
    .addItem('反響日ベースを更新', 'syncHankyoubiBaseSummary')
    .addItem('両方まとめて更新', 'runAll')
    .addItem('（デバッグ）判定内容をログ表示', 'debugSnapshotBlock')
    .addToUi();
}

function runAll() {
  syncKeiyakubiBaseSummary();
  syncHankyoubiBaseSummary();
}

// 「今日」の判定がおかしいときに、実際どう判定されているか確認するための関数。
// 実行後、Apps Scriptエディタの「実行数」からログを見てください。
function debugSnapshotBlock() {
  var gasToday = new Date();
  var bqToday = getBigQueryToday_();
  var block = getCurrentSnapshotBlock_();

  Logger.log('GAS側のnew Date(): ' + gasToday);
  Logger.log('BigQuery側のCURRENT_DATE: ' + bqToday);
  Logger.log('判定されたブロック: ' + JSON.stringify(block));
}
