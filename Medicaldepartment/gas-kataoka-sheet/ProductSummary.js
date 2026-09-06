/**
 * 「商材別」シート（上位6商材＋その他を、商材ごとに契約日ベース・反響日ベースを
 * 縦に並べたもの）を BigQuery から集計して書き込む。スナップショットなし、常に
 * SUMMARY_START_DATE 〜 実行時点(BigQueryのCURRENT_DATE)までの実績を上書きする。
 *
 * 商材の判定は product_class_id（stream.product_classes マスタ）を使用。
 * 上位6商材(痩身=8, 泌尿器=1, AGA=2, ED=12, 二重=3, 小顔=5)以外は「その他」にまとめる。
 * 解約の定義は他シートと同じ:
 *   status IN ('cancel','cooling_off') OR (status = 'contract' AND is_cancel_scheduled = 1)
 */

var SHOHIN_BETSU_CASE_SQL_ =
  'CASE product_class_id' +
  ' WHEN 8 THEN "痩身" WHEN 1 THEN "泌尿器" WHEN 2 THEN "AGA"' +
  ' WHEN 12 THEN "ED" WHEN 3 THEN "二重" WHEN 5 THEN "小顔"' +
  ' ELSE "その他" END';

function syncShohinBetsu() {
  var contractSql =
    'SELECT' +
    '  ' + SHOHIN_BETSU_CASE_SQL_ + ' AS product_group,' +
    '  FORMAT_DATE("%Y-%m", DATE(contracted_at, "Asia/Tokyo")) AS month,' +
    '  COUNT(DISTINCT contract_group_id) AS contract_count,' +
    '  SUM(contract_amount) AS contract_amount,' +
    '  COUNT(DISTINCT IF(status IN ("cancel","cooling_off") OR (status = "contract" AND is_cancel_scheduled = 1), contract_group_id, NULL)) AS kaiyaku_count,' +
    '  SUM(IF(status IN ("cancel","cooling_off") OR (status = "contract" AND is_cancel_scheduled = 1), contract_amount, 0)) AS kaiyaku_amount' +
    ' FROM `' + CONFIG.BQ_PROJECT + '.stream.contracts`' +
    ' WHERE DATE(contracted_at, "Asia/Tokyo") BETWEEN "' + CONFIG.SUMMARY_START_DATE + '" AND CURRENT_DATE("Asia/Tokyo")' +
    ' GROUP BY product_group, month' +
    ' ORDER BY product_group, month';

  writeShohinBetsuSection_(runBigQuery_(contractSql), 0);

  var inquirySql =
    'WITH first_inquiry AS (' +
    '  SELECT client_id, MIN(inquired_at) AS first_inquired_at' +
    '  FROM `' + CONFIG.BQ_PROJECT + '.stream.inquiries`' +
    '  WHERE client_id IS NOT NULL' +
    '  GROUP BY client_id' +
    ')' +
    'SELECT' +
    '  ' + SHOHIN_BETSU_CASE_SQL_.replace(/product_class_id/g, 'c.product_class_id') + ' AS product_group,' +
    '  FORMAT_DATE("%Y-%m", DATE(fi.first_inquired_at, "Asia/Tokyo")) AS month,' +
    '  COUNT(DISTINCT c.contract_group_id) AS contract_count,' +
    '  SUM(c.contract_amount) AS contract_amount,' +
    '  COUNT(DISTINCT IF(c.status IN ("cancel","cooling_off") OR (c.status = "contract" AND c.is_cancel_scheduled = 1), c.contract_group_id, NULL)) AS kaiyaku_count,' +
    '  SUM(IF(c.status IN ("cancel","cooling_off") OR (c.status = "contract" AND c.is_cancel_scheduled = 1), c.contract_amount, 0)) AS kaiyaku_amount' +
    ' FROM first_inquiry fi' +
    ' JOIN `' + CONFIG.BQ_PROJECT + '.stream.contracts` c ON c.client_id = fi.client_id' +
    ' WHERE DATE(fi.first_inquired_at, "Asia/Tokyo") BETWEEN "' + CONFIG.SUMMARY_START_DATE + '" AND CURRENT_DATE("Asia/Tokyo")' +
    ' GROUP BY product_group, month' +
    ' ORDER BY product_group, month';

  writeShohinBetsuSection_(runBigQuery_(inquirySql), CONFIG.SHOHIN_BETSU_HANKYOUBI_OFFSET);

  syncShohinBetsuOtherList_();
}

function writeShohinBetsuSection_(rows, blockOffset) {
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(CONFIG.SHOHIN_BETSU_SHEET_NAME);
  var order = CONFIG.SHOHIN_BETSU_PRODUCT_ORDER;

  rows.forEach(function (row) {
    var idx = order.indexOf(row.product_group);
    if (idx === -1) return; // 想定外の商材名は書き込まない

    var base = CONFIG.SHOHIN_BETSU_BASE_ROW + idx * CONFIG.SHOHIN_BETSU_BLOCK_ROW_SPAN + blockOffset;
    var monthNum = parseInt(row.month.split('-')[1], 10);
    var col = monthNum + 2;

    var count = Number(row.contract_count);
    var amount = Number(row.contract_amount);
    var kaiyakuCount = Number(row.kaiyaku_count);
    var kaiyakuAmount = Number(row.kaiyaku_amount);

    sheet.getRange(base + 1, col).setValue(count);
    sheet.getRange(base + 2, col).setValue(amount);
    sheet.getRange(base + 3, col).setValue(kaiyakuCount);
    sheet.getRange(base + 4, col).setValue(kaiyakuAmount);
    sheet.getRange(base + 5, col).setValue(amount > 0 ? kaiyakuAmount / amount : 0);
    sheet.getRange(base + 6, col).setValue(count > 0 ? kaiyakuCount / count : 0);
  });

  Logger.log(CONFIG.SHOHIN_BETSU_SHEET_NAME + ' を更新(オフセット' + blockOffset + '): ' + rows.length + '行');
}

// P〜R列の「その他に含まれる商材一覧」（全期間の契約金額の多い順）を更新する。
function syncShohinBetsuOtherList_() {
  var sql =
    'SELECT pc.id AS product_class_id, pc.name AS product_name, SUM(c.contract_amount) AS total_amount' +
    ' FROM `' + CONFIG.BQ_PROJECT + '.stream.contracts` c' +
    ' JOIN `' + CONFIG.BQ_PROJECT + '.stream.product_classes` pc ON pc.id = c.product_class_id' +
    ' WHERE pc.id NOT IN (8, 1, 2, 12, 3, 5)' +
    ' GROUP BY product_class_id, product_name' +
    ' ORDER BY total_amount DESC';

  var rows = runBigQuery_(sql);
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(CONFIG.SHOHIN_BETSU_SHEET_NAME);

  // 商材の増減にも対応できるよう、一旦クリアしてから書き直す。
  sheet.getRange(3, 16, CONFIG.SHOHIN_BETSU_OTHER_LIST_MAX_ROWS, 3).clearContent();

  var values = rows.map(function (r) {
    return [Number(r.product_class_id), r.product_name, Number(r.total_amount)];
  });
  if (values.length > 0) {
    sheet.getRange(3, 16, values.length, 3).setValues(values);
  }

  Logger.log('その他内訳一覧を更新: ' + values.length + '件');
}
