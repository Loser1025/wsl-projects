/**
 * スプレッドシート起動時にメニューを追加する。
 * このファイルはスプレッドシートに紐づいたスクリプト（拡張機能 > Apps Script
 * から作成したプロジェクト）に設置する必要がある。独立スクリプトでは
 * onOpen()によるメニュー追加ができない。
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('友達情報')
    .addItem('CSVから友達情報を更新', 'showUploadDialog')
    .addToUi();
}

function showUploadDialog() {
  const sheetNames = getDateSheetNames_();
  const template = HtmlService.createTemplateFromFile('UploadDialog');
  template.sheetNames = sheetNames;
  const html = template.evaluate().setWidth(420).setHeight(380);
  SpreadsheetApp.getUi().showModalDialog(html, '友達情報の更新');
}

/** タブ名が MM/DD 形式のシート（テンプレは除く）を全て返す */
function getDateSheetNames_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheets()
    .map((s) => s.getName())
    .filter((name) => /^\d{2}\/\d{2}$/.test(name));
}
