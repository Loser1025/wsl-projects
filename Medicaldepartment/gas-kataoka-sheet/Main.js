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
    .addToUi();
}

function runAll() {
  syncKeiyakubiBaseSummary();
  syncHankyoubiBaseSummary();
}
