/**
 * 「全体_契約日ベース」「全体_反響日ベース」の契約数・契約金額・解約数・解約金額を
 * BigQuery から集計して書き込む。集計終了日と書き込み先の行は、実行日時点で
 * 直近に到達したスナップショット日（15日／月末）に応じて自動で切り替わる（SnapshotBlock.js参照）。
 *
 * 解約の定義: status IN ('cancel','cooling_off')
 *            OR (status = 'contract' AND is_cancel_scheduled = 1)  … 処理前（解約予定フラグ）
 * 契約数・解約数は contract_group_id の重複を除いた件数（付属メニュー分は1件にまとめる）。
 * 契約数・解約数とも、対象は「契約日が集計期間内（開始日〜ブロックの締め日）」のもの。
 *
 * 反響日ベースも、初回問い合わせ月だけでなく契約日にもブロックの締め日で上限をかけている。
 * こうしないと、確定済みのはずのブロック（例:8月末）の数字が、後日その顧客が追加契約するたびに
 * 変わり続けてしまう（真の意味で「確定」しない）ため。これにより、変動するのは常に
 * 進行中の最新ブロックだけになり、一度確定したブロックは以後変化しない。
 */

// 契約日ベース：その月に契約したものを、その月にカウント
function syncKeiyakubiBaseSummary() {
  var block = getCurrentSnapshotBlock_();

  var sql =
    'SELECT' +
    '  FORMAT_DATE("%Y-%m", DATE(contracted_at, "Asia/Tokyo")) AS month,' +
    '  COUNT(DISTINCT contract_group_id) AS contract_count,' +
    '  SUM(contract_amount) AS contract_amount,' +
    '  COUNT(DISTINCT IF(status IN ("cancel","cooling_off") OR (status = "contract" AND is_cancel_scheduled = 1), contract_group_id, NULL)) AS kaiyaku_count,' +
    '  SUM(IF(status IN ("cancel","cooling_off") OR (status = "contract" AND is_cancel_scheduled = 1), contract_amount, 0)) AS kaiyaku_amount' +
    ' FROM `' + CONFIG.BQ_PROJECT + '.stream.contracts`' +
    ' WHERE DATE(contracted_at, "Asia/Tokyo") BETWEEN "' + CONFIG.SUMMARY_START_DATE + '" AND "' + block.endDate + '"' +
    ' GROUP BY month' +
    ' ORDER BY month';

  var rows = runBigQuery_(sql);
  writeMonthlySummary_(CONFIG.KEIYAKUBI_SHEET_NAME, rows, block);
}

// 反響日ベース：顧客の初回問い合わせ月に、その顧客のその後の契約すべてをカウント
function syncHankyoubiBaseSummary() {
  var block = getCurrentSnapshotBlock_();

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
    ' FROM `' + CONFIG.BQ_PROJECT + '.stream.contracts` c' +
    ' JOIN first_inquiry fi ON c.client_id = fi.client_id' +
    ' WHERE DATE(fi.first_inquired_at, "Asia/Tokyo") BETWEEN "' + CONFIG.SUMMARY_START_DATE + '" AND "' + block.endDate + '"' +
    '   AND DATE(c.contracted_at, "Asia/Tokyo") <= "' + block.endDate + '"' +
    ' GROUP BY month' +
    ' ORDER BY month';

  var rows = runBigQuery_(sql);
  writeMonthlySummary_(CONFIG.HANKYOUBI_SHEET_NAME, rows, block);
}

function writeMonthlySummary_(sheetName, rows, block) {
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(sheetName);

  rows.forEach(function (row) {
    var monthNum = parseInt(row.month.split('-')[1], 10); // 1-12
    var col = monthNum + 2; // C列(3)=1月 なので +2

    sheet.getRange(block.rows.contractCount, col).setValue(Number(row.contract_count));
    sheet.getRange(block.rows.contractAmount, col).setValue(Number(row.contract_amount));
    sheet.getRange(block.rows.kaiyakuCount, col).setValue(Number(row.kaiyaku_count));
    sheet.getRange(block.rows.kaiyakuAmount, col).setValue(Number(row.kaiyaku_amount));
  });

  Logger.log(sheetName + ' を更新（' + block.label + 'ブロック、〜' + block.endDate + '）: ' + rows.length + 'ヶ月分');
}
