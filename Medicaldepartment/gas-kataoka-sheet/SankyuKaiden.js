/**
 * 「サンキュー架電」シート(A:D列 = ストリームID・契約日・問い合わせ日時・商材)を読み込み、
 * 「全体」「3か月比較」「商材別」の各表にサンキュー架電数・対応率(架電数/契約数)を書き込む。
 *
 * 契約日・問い合わせ日はシート側に直接入力されているため、BigQueryでの突合は行わない
 * (BigQuery突合は一度だけ手動で実行し、C列(問い合わせ日時)に結果を書き込み済み)。
 */

function syncSankyuKaiden() {
  var list = readSankyuList_();
  if (list.length === 0) {
    Logger.log('サンキュー架電シートにデータがありません。');
    return;
  }

  var startMonth = CONFIG.SUMMARY_START_DATE.slice(0, 7);

  var byMonth = {};              // 契約月 -> 件数 (全商材合計)
  var byMonthProduct = {};       // "月|商材" -> 件数
  var byInquiryMonth = {};       // 反響月(集計対象期間内) -> 件数 (全商材合計)
  var byInquiryMonthProduct = {}; // "月|商材" -> 件数
  var byInquiryMonthWithin3mo = {}; // 反響月(集計対象期間内、契約が反響+3か月以内) -> 件数

  list.forEach(function (r) {
    if (r.contractMonth) {
      byMonth[r.contractMonth] = (byMonth[r.contractMonth] || 0) + 1;
      byMonthProduct[r.contractMonth + '|' + r.product] = (byMonthProduct[r.contractMonth + '|' + r.product] || 0) + 1;
    }

    if (r.inquiryMonth && r.inquiryMonth >= startMonth) {
      byInquiryMonth[r.inquiryMonth] = (byInquiryMonth[r.inquiryMonth] || 0) + 1;
      byInquiryMonthProduct[r.inquiryMonth + '|' + r.product] = (byInquiryMonthProduct[r.inquiryMonth + '|' + r.product] || 0) + 1;

      if (r.contractDate && r.inquiryDate && r.contractDate <= addMonths_(r.inquiryDate, 3)) {
        byInquiryMonthWithin3mo[r.inquiryMonth] = (byInquiryMonthWithin3mo[r.inquiryMonth] || 0) + 1;
      }
    }
  });

  writeSankyuOverall_(byMonth, byInquiryMonth);
  writeSankyuThreeMonth_(byMonth, byInquiryMonthWithin3mo);
  writeSankyuShohinBetsu_(byMonthProduct, byInquiryMonthProduct);
}

// サンキュー架電シートを読み込み、[{contractDate, contractMonth, inquiryDate, inquiryMonth, product}] を返す。
function readSankyuList_() {
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(CONFIG.SANKYU_SHEET_NAME);
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];

  var values = sheet.getRange(2, 1, lastRow - 1, 4).getValues();
  var list = [];
  values.forEach(function (row) {
    var contractDate = parseSankyuDate_(row[1]);
    var inquiryDate = parseSankyuDate_(row[2]);
    var product = row[3] ? String(row[3]).trim() : '';
    if (!contractDate || !product) return;

    list.push({
      contractDate: contractDate,
      contractMonth: formatYearMonth_(contractDate),
      inquiryDate: inquiryDate,
      inquiryMonth: inquiryDate ? formatYearMonth_(inquiryDate) : null,
      product: product
    });
  });
  return list;
}

// セルの値(Dateオブジェクト or "YYYY/MM/DD"文字列 or 日時文字列)をDateに変換する。空なら null。
function parseSankyuDate_(value) {
  if (!value) return null;
  if (Object.prototype.toString.call(value) === '[object Date]') return value;

  var s = String(value).trim();
  if (!s) return null;
  var m = s.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})/);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

function formatYearMonth_(date) {
  return Utilities.formatDate(date, 'Asia/Tokyo', 'yyyy-MM');
}

function addMonths_(date, months) {
  var d = new Date(date.getTime());
  d.setMonth(d.getMonth() + months);
  return d;
}

function writeSankyuOverall_(byMonth, byInquiryMonth) {
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(CONFIG.OVERALL_SHEET_NAME);
  writeSankyuRow_(sheet, CONFIG.OVERALL_ROWS.keiyakubi, byMonth);
  writeSankyuRow_(sheet, CONFIG.OVERALL_ROWS.hankyoubi, byInquiryMonth);
}

function writeSankyuThreeMonth_(byMonth, byInquiryMonthWithin3mo) {
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(CONFIG.THREE_MONTH_SHEET_NAME);
  writeSankyuRow_(sheet, CONFIG.THREE_MONTH_ROWS.keiyaku, byMonth);
  writeSankyuRow_(sheet, CONFIG.THREE_MONTH_ROWS.hankyo, byInquiryMonthWithin3mo);
}

// rowConfigのcount行(既に書き込み済みの契約数)を読み取り、サンキュー架電数・対応率を書き込む。
function writeSankyuRow_(sheet, rowConfig, byMonth) {
  for (var monthNum = 1; monthNum <= 12; monthNum++) {
    var col = monthNum + 2;
    var monthKey = CONFIG.SUMMARY_START_DATE.slice(0, 4) + '-' + ('0' + monthNum).slice(-2);
    var sankyuCount = byMonth[monthKey] || 0;
    var contractCount = Number(sheet.getRange(rowConfig.count, col).getValue()) || 0;

    sheet.getRange(rowConfig.sankyuCount, col).setValue(sankyuCount);
    sheet.getRange(rowConfig.sankyuRate, col).setValue(contractCount > 0 ? sankyuCount / contractCount : 0);
  }
}

function writeSankyuShohinBetsu_(byMonthProduct, byInquiryMonthProduct) {
  var sheet = SpreadsheetApp.openById(CONFIG.SUMMARY_SPREADSHEET_ID).getSheetByName(CONFIG.SHOHIN_BETSU_SHEET_NAME);
  var order = CONFIG.SHOHIN_BETSU_PRODUCT_ORDER;
  var offsets = CONFIG.SHOHIN_BETSU_METRIC_OFFSETS;

  order.forEach(function (product, idx) {
    writeSankyuShohinBlock_(sheet, CONFIG.SHOHIN_BETSU_BASE_ROW + idx * CONFIG.SHOHIN_BETSU_BLOCK_ROW_SPAN, offsets, product, byMonthProduct);
    writeSankyuShohinBlock_(sheet, CONFIG.SHOHIN_BETSU_BASE_ROW + idx * CONFIG.SHOHIN_BETSU_BLOCK_ROW_SPAN + CONFIG.SHOHIN_BETSU_HANKYOUBI_OFFSET, offsets, product, byInquiryMonthProduct);
  });
}

function writeSankyuShohinBlock_(sheet, base, offsets, product, byMonthProduct) {
  var countRow = base + offsets.count;
  var sankyuCountRow = base + offsets.sankyuCount;
  var sankyuRateRow = base + offsets.sankyuRate;

  for (var monthNum = 1; monthNum <= 12; monthNum++) {
    var col = monthNum + 2;
    var monthKey = CONFIG.SUMMARY_START_DATE.slice(0, 4) + '-' + ('0' + monthNum).slice(-2);
    var sankyuCount = byMonthProduct[monthKey + '|' + product] || 0;
    var contractCount = Number(sheet.getRange(countRow, col).getValue()) || 0;

    sheet.getRange(sankyuCountRow, col).setValue(sankyuCount);
    sheet.getRange(sankyuRateRow, col).setValue(contractCount > 0 ? sankyuCount / contractCount : 0);
  }
}
