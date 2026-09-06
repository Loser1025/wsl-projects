/**
 * 「全体」シート（契約日ベース・反響日ベースを1枚に統合、スナップショットなし）を
 * BigQuery から集計して書き込む。常に SUMMARY_START_DATE 〜 実行時点(BigQueryのCURRENT_DATE)
 * までの、現時点のステータスに基づく実績を上書きする。
 *
 * 解約の定義: status IN ('cancel','cooling_off')
 *            OR (status = 'contract' AND is_cancel_scheduled = 1)  … 処理前（解約予定フラグ）
 * 契約数・解約数は contract_group_id の重複を除いた件数（付属メニュー分は1件にまとめる）。
 */

// 契約日ベース：その月に契約したものを、その月にカウント
function syncKeiyakubiBaseSummary() {
  var sql =
    'SELECT' +
    '  FORMAT_DATE("%Y-%m", DATE(contracted_at, "Asia/Tokyo")) AS month,' +
    '  COUNT(DISTINCT contract_group_id) AS contract_count,' +
    '  SUM(contract_amount) AS contract_amount,' +
    '  COUNT(DISTINCT IF(status IN ("cancel","cooling_off") OR (status = "contract" AND is_cancel_scheduled = 1), contract_group_id, NULL)) AS kaiyaku_count,' +
    '  SUM(IF(status IN ("cancel","cooling_off") OR (status = "contract" AND is_cancel_scheduled = 1), contract_amount, 0)) AS kaiyaku_amount' +
    ' FROM `' + CONFIG.BQ_PROJECT + '.stream.contracts`' +
    ' WHERE DATE(contracted_at, "Asia/Tokyo") BETWEEN "' + CONFIG.SUMMARY_START_DATE + '" AND CURRENT_DATE("Asia/Tokyo")' +
    ' GROUP BY month' +
    ' ORDER BY month';

  var rows = runBigQuery_(sql);
  writeOverallSummary_(CONFIG.OVERALL_ROWS.keiyakubi, rows);
}

// 反響日ベース：顧客の初回問い合わせ月に、その顧客のその後の契約すべてをカウント
function syncHankyoubiBaseSummary() {
  var sql =
    'WITH first_inquiry AS (' +
    '  SELECT client_id, MIN(inquired_at) AS first_inquired_at' +
    '  FROM `' + CONFIG.BQ_PROJECT + '.stream.inquiries`' +
    '  WHERE client_id IS NOT NULL' +
    '  GROUP BY client_id' +
    ')' +
    'SELECT' +
    '  FORMAT_DATE("%Y-%m", DATE(fi.first_inquired_at, "Asia/Tokyo")) AS month,' +
    '  COUNT(DISTINCT c.contract_group_id) AS contract_count,' +
    '  SUM(c.contract_amount) AS contract_amount,' +
    '  COUNT(DISTINCT IF(c.status IN ("cancel","cooling_off") OR (c.status = "contract" AND c.is_cancel_scheduled = 1), c.contract_group_id, NULL)) AS kaiyaku_count,' +
    '  SUM(IF(c.status IN ("cancel","cooling_off") OR (c.status = "contract" AND c.is_cancel_scheduled = 1), c.contract_amount, 0)) AS kaiyaku_amount' +
    ' FROM first_inquiry fi' +
    ' JOIN `' + CONFIG.BQ_PROJECT + '.stream.contracts` c ON c.client_id = fi.client_id' +
    ' WHERE DATE(fi.first_inquired_at, "Asia/Tokyo") BETWEEN "' + CONFIG.SUMMARY_START_DATE + '" AND CURRENT_DATE("Asia/Tokyo")' +
    ' GROUP BY month' +
    ' ORDER BY month';

  var rows = runBigQuery_(sql);
  writeOverallSummary_(CONFIG.OVERALL_ROWS.hankyoubi, rows);
}

function writeOverallSummary_(rowConfig, rows) {
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(CONFIG.OVERALL_SHEET_NAME);

  rows.forEach(function (row) {
    var monthNum = parseInt(row.month.split('-')[1], 10); // 1-12
    var col = monthNum + 2; // C列(3)=1月 なので +2

    var count = Number(row.contract_count);
    var amount = Number(row.contract_amount);
    var kaiyakuCount = Number(row.kaiyaku_count);
    var kaiyakuAmount = Number(row.kaiyaku_amount);

    sheet.getRange(rowConfig.count, col).setValue(count);
    sheet.getRange(rowConfig.amount, col).setValue(amount);
    sheet.getRange(rowConfig.kaiyakuCount, col).setValue(kaiyakuCount);
    sheet.getRange(rowConfig.kaiyakuAmount, col).setValue(kaiyakuAmount);
    sheet.getRange(rowConfig.kaiyakuRateCount, col).setValue(count > 0 ? kaiyakuCount / count : 0);
    sheet.getRange(rowConfig.kaiyakuRateAmount, col).setValue(amount > 0 ? kaiyakuAmount / amount : 0);
  });

  Logger.log(CONFIG.OVERALL_SHEET_NAME + ' を更新: ' + rows.length + 'ヶ月分');
}
