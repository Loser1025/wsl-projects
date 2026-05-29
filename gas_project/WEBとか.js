function exportBigQueryToColumnR() {
  // === 設定項目 ===
  const projectId = 'consulting-report'; // BigQueryのプロジェクトIDを入力
  const sheetName = 'WEB/シミュ2'; // 書き出し先のシート名
  
  const sql = "SELECT " +
    "  `反響日`, " +
    "  `集客区分`, " +
    "  COUNT(*) AS `件数` " +
    "FROM " +
    "  `consulting-report.consulting_report_alloffices.01C_alloffiices_summary` " +
    "WHERE " +
    "  `反響日` >= DATE_TRUNC(CURRENT_DATE(), MONTH) " +
    "GROUP BY " +
    "  `反響日`, " +
    "  `集客区分` " +
    "ORDER BY " +
    "  `反響日` DESC, " +
    "  `件数` DESC";
  

  // === BigQueryからデータ取得 ===
  const request = {
    query: sql,
    useLegacySql: false
  };
  
  let queryResults = BigQuery.Jobs.query(request, projectId);
  const jobId = queryResults.jobReference.jobId;

  // クエリの完了を待機
  while (!queryResults.jobComplete) {
    Utilities.sleep(500);
    queryResults = BigQuery.Jobs.getQueryResults(projectId, jobId);
  }

  const rows = queryResults.rows;
  const data = [];
  
  // ヘッダー（項目名）の取得
  const headers = queryResults.schema.fields.map(field => field.name);
  data.push(headers);

  // データの整形
  if (rows) {
    rows.forEach(row => {
      const formattedRow = row.f.map(cell => cell.v);
      data.push(formattedRow);
    });
  }

  // === スプレッドシートへの書き出し（R列以降） ===
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  if (!sheet) {
    console.error('シート「' + sheetName + '」が見つかりません。');
    return;
  }

  const startColumn = 18; // R列は18番目
  
  // R列以降（18列目〜）の既存データをクリア（A-Q列は維持）
  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastCol >= startColumn) {
    sheet.getRange(1, startColumn, Math.max(lastRow, 1), lastCol - startColumn + 1).clearContent();
  }

  // R列を起点にデータを貼り付け
  if (data.length > 0) {
    sheet.getRange(1, startColumn, data.length, data[0].length).setValues(data);
    // ヘッダーのみ太字にする（R列〜）
    sheet.getRange(1, startColumn, 1, data[0].length).setFontWeight("bold");
  }
  
  console.log('R列以降への書き出しが完了しました。');
}