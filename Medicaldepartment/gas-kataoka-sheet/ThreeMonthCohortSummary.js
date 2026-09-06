/**
 * 「契約から3か月」シート（契約コホート・反響コホートを1枚に統合、スナップショットなし）を
 * BigQuery から集計して書き込む。常に SUMMARY_START_DATE 〜 実行時点(BigQueryのCURRENT_DATE)
 * までの実績をコホート月の行に上書きする(直近3か月は3か月経過前のため未確定で増減しうる)。
 *
 * 解約の定義は他シートと同じ:
 *   status IN ("cancel","cooling_off")
 *   OR (status = "contract" AND is_cancel_scheduled = 1)  … 処理前（解約予定フラグ）
 * ただし基準日(契約日 or 反響日)から3か月以内に解約(または解約予定)になったものだけをカウントする。
 */

// 契約日から3か月以内の解約数・解約金額
function syncKeiyakuKara3kagetsu() {
  var sql =
    'SELECT' +
    '  FORMAT_DATE("%Y-%m", DATE(contracted_at, "Asia/Tokyo")) AS month,' +
    '  COUNT(DISTINCT contract_group_id) AS contract_count,' +
    '  SUM(contract_amount) AS contract_amount,' +
    '  COUNT(DISTINCT IF(' +
    '    (status IN ("cancel","cooling_off") AND DATE(canceled_at, "Asia/Tokyo") <= DATE_ADD(DATE(contracted_at, "Asia/Tokyo"), INTERVAL 3 MONTH))' +
    '    OR (status = "contract" AND is_cancel_scheduled = 1 AND scheduled_cancel_date <= DATE_ADD(DATE(contracted_at, "Asia/Tokyo"), INTERVAL 3 MONTH)),' +
    '    contract_group_id, NULL)) AS kaiyaku_count,' +
    '  SUM(IF(' +
    '    (status IN ("cancel","cooling_off") AND DATE(canceled_at, "Asia/Tokyo") <= DATE_ADD(DATE(contracted_at, "Asia/Tokyo"), INTERVAL 3 MONTH))' +
    '    OR (status = "contract" AND is_cancel_scheduled = 1 AND scheduled_cancel_date <= DATE_ADD(DATE(contracted_at, "Asia/Tokyo"), INTERVAL 3 MONTH)),' +
    '    contract_amount, 0)) AS kaiyaku_amount' +
    ' FROM `' + CONFIG.BQ_PROJECT + '.stream.contracts`' +
    ' WHERE DATE(contracted_at, "Asia/Tokyo") BETWEEN "' + CONFIG.SUMMARY_START_DATE + '" AND CURRENT_DATE("Asia/Tokyo")' +
    ' GROUP BY month' +
    ' ORDER BY month';

  var rows = runBigQuery_(sql);
  writeThreeMonthSummary_(CONFIG.THREE_MONTH_ROWS.keiyaku, rows);
}

// 反響日(初回問い合わせ日)から3か月以内の契約数・解約数・金額
function syncHankyoKara3kagetsu() {
  var sql =
    'WITH first_inquiry AS (' +
    '  SELECT client_id, MIN(inquired_at) AS first_inquired_at' +
    '  FROM `' + CONFIG.BQ_PROJECT + '.stream.inquiries`' +
    '  WHERE client_id IS NOT NULL' +
    '  GROUP BY client_id' +
    ')' +
    'SELECT' +
    '  FORMAT_DATE("%Y-%m", DATE(fi.first_inquired_at, "Asia/Tokyo")) AS month,' +
    '  COUNT(DISTINCT IF(DATE(c.contracted_at,"Asia/Tokyo") <= DATE_ADD(DATE(fi.first_inquired_at,"Asia/Tokyo"), INTERVAL 3 MONTH), c.contract_group_id, NULL)) AS contract_count,' +
    '  SUM(IF(DATE(c.contracted_at,"Asia/Tokyo") <= DATE_ADD(DATE(fi.first_inquired_at,"Asia/Tokyo"), INTERVAL 3 MONTH), c.contract_amount, 0)) AS contract_amount,' +
    '  COUNT(DISTINCT IF(' +
    '    DATE(c.contracted_at,"Asia/Tokyo") <= DATE_ADD(DATE(fi.first_inquired_at,"Asia/Tokyo"), INTERVAL 3 MONTH)' +
    '    AND (' +
    '      (c.status IN ("cancel","cooling_off") AND DATE(c.canceled_at,"Asia/Tokyo") <= DATE_ADD(DATE(fi.first_inquired_at,"Asia/Tokyo"), INTERVAL 3 MONTH))' +
    '      OR (c.status = "contract" AND c.is_cancel_scheduled = 1 AND c.scheduled_cancel_date <= DATE_ADD(DATE(fi.first_inquired_at,"Asia/Tokyo"), INTERVAL 3 MONTH))' +
    '    ), c.contract_group_id, NULL)) AS kaiyaku_count,' +
    '  SUM(IF(' +
    '    DATE(c.contracted_at,"Asia/Tokyo") <= DATE_ADD(DATE(fi.first_inquired_at,"Asia/Tokyo"), INTERVAL 3 MONTH)' +
    '    AND (' +
    '      (c.status IN ("cancel","cooling_off") AND DATE(c.canceled_at,"Asia/Tokyo") <= DATE_ADD(DATE(fi.first_inquired_at,"Asia/Tokyo"), INTERVAL 3 MONTH))' +
    '      OR (c.status = "contract" AND c.is_cancel_scheduled = 1 AND c.scheduled_cancel_date <= DATE_ADD(DATE(fi.first_inquired_at,"Asia/Tokyo"), INTERVAL 3 MONTH))' +
    '    ), c.contract_amount, 0)) AS kaiyaku_amount' +
    ' FROM first_inquiry fi' +
    ' LEFT JOIN `' + CONFIG.BQ_PROJECT + '.stream.contracts` c ON c.client_id = fi.client_id' +
    ' WHERE DATE(fi.first_inquired_at, "Asia/Tokyo") BETWEEN "' + CONFIG.SUMMARY_START_DATE + '" AND CURRENT_DATE("Asia/Tokyo")' +
    ' GROUP BY month' +
    ' ORDER BY month';

  var rows = runBigQuery_(sql);
  writeThreeMonthSummary_(CONFIG.THREE_MONTH_ROWS.hankyo, rows);
}

function writeThreeMonthSummary_(rowConfig, rows) {
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(CONFIG.THREE_MONTH_SHEET_NAME);

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

  Logger.log(CONFIG.THREE_MONTH_SHEET_NAME + ' を更新: ' + rows.length + 'ヶ月分');
}
