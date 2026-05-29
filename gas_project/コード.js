// ===== 設定 =====
const CONFIG = {
  projectId: 'consulting-report',
  datasetId: 'consulting_report_alloffices',
  viewId: '01C_alloffiices_summaryA',
  sheetName: 'BQ_同期データ', // 書き込み先シート名
};

const HIBIKI_CONFIG = {
  sheetName: '響LU反響数',
  query: 'SELECT ' +
         '  DATE(`調整反響日`) AS inquiry_date, ' +
         '  COUNT(*) AS inquiry_count ' +
         'FROM ' +
         '  `consulting-report.consulting_report_alloffices.01C_alloffiices_summary` ' +
         'WHERE ' +
         '  `LU登録事務所` >= \'hibiki\' ' +
         'GROUP BY ' +
         '  inquiry_date ' +
         'ORDER BY ' +
         '  inquiry_date DESC'
};

// ===== メイン同期関数（手動・トリガー共用）=====
function syncBigQueryData() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(CONFIG.sheetName);

  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.sheetName);
  }

  try {
    const data = fetchBigQueryData();

    if (!data || data.length === 0) {
      Logger.log('データが0件でした。');
      updateStatusCell(sheet, 'データ0件 - ' + formatNow());
    } else {
      writeToSheet(sheet, data);
      updateStatusCell(sheet, '最終同期: ' + formatNow() + '  (' + (data.length - 1) + '行)');
      Logger.log('同期完了: ' + (data.length - 1) + '行');
    }

    // 続けて「響LU反響数」も同期
    syncHibikiInquiryCount();

  } catch (e) {
    Logger.log('エラー: ' + e.message);
    updateStatusCell(sheet, 'エラー: ' + e.message + ' - ' + formatNow());
    throw e;
  }
}

// ===== BigQueryからデータ取得 (デフォルト) =====
function fetchBigQueryData() {
  const query = 'SELECT * FROM `' + CONFIG.projectId + '.' + CONFIG.datasetId + '.' + CONFIG.viewId + '`';
  return fetchBigQueryDataByQuery(query);
}

// ===== 汎用的なクエリ実行関数 =====
function fetchBigQueryDataByQuery(sqlQuery) {
  const jobConfig = {
    configuration: {
      query: {
        query: sqlQuery,
        useLegacySql: false,
      },
    },
  };

  let job = BigQuery.Jobs.insert(jobConfig, CONFIG.projectId);
  const jobId = job.jobReference.jobId;
  const location = job.jobReference.location;

  let status = job.status.state;
  let attempts = 0;
  while (status !== 'DONE' && attempts < 60) {
    Utilities.sleep(2000);
    job = BigQuery.Jobs.get(CONFIG.projectId, jobId, { location: location });
    status = job.status.state;
    attempts++;
  }

  if (status !== 'DONE') throw new Error('BigQueryジョブがタイムアウトしました。');
  if (job.status.errorResult) throw new Error('BigQueryエラー: ' + job.status.errorResult.message);

  let results = BigQuery.Jobs.getQueryResults(CONFIG.projectId, jobId, { maxResults: 10000, location: location });
  let rows = results.rows || [];

  while (results.pageToken) {
    results = BigQuery.Jobs.getQueryResults(CONFIG.projectId, jobId, {
      pageToken: results.pageToken,
      maxResults: 10000,
      location: location,
    });
    rows = rows.concat(results.rows || []);
  }

  if (!results.schema || rows.length === 0) return [];

  const headers = results.schema.fields.map(function(f) { return f.name; });
  const dataRows = rows.map(function(row) {
    return row.f.map(function(cell) { return cell.v === null ? '' : cell.v; });
  });

  return [headers].concat(dataRows);
}

// ===== 響LU反響数の同期実行 =====
function syncHibikiInquiryCount() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(HIBIKI_CONFIG.sheetName);

  if (!sheet) {
    sheet = ss.insertSheet(HIBIKI_CONFIG.sheetName);
  }

  try {
    const data = fetchBigQueryDataByQuery(HIBIKI_CONFIG.query);

    if (!data || data.length === 0) {
      updateStatusCell(sheet, 'データ0件 - ' + formatNow());
      return;
    }

    writeToSheet(sheet, data);
    updateStatusCell(sheet, '最終同期: ' + formatNow() + ' (' + (data.length - 1) + '件)');
    Logger.log('響LU反響数 同期完了');

  } catch (e) {
    Logger.log('エラー: ' + e.message);
    updateStatusCell(sheet, 'エラー: ' + e.message);
  }
}

// ===== スプレッドシートへの書き込み (フィルターなし) =====
function writeToSheet(sheet, data) {
  // 既存のフィルタがあれば解除（エラー防止）
  const filter = sheet.getFilter();
  if (filter) {
    filter.remove();
  }
  
  sheet.clearContents();

  const numRows = data.length;
  const numCols = data[0].length;

  sheet.getRange(1, 1, numRows, numCols).setValues(data);

  // ヘッダー行の装飾
  const headerRange = sheet.getRange(1, 1, 1, numCols);
  headerRange.setBackground('#4A90D9');
  headerRange.setFontColor('#FFFFFF');
  headerRange.setFontWeight('bold');

  // 列幅を自動調整
  sheet.autoResizeColumns(1, numCols);
}

// ===== ステータスセルの更新 =====
function updateStatusCell(sheet, message) {
  const lastRow = sheet.getLastRow();
  const statusRow = lastRow > 0 ? lastRow + 2 : 1;
  const cell = sheet.getRange(statusRow, 1);
  cell.setValue(message);
  cell.setFontColor('#888888');
  cell.setFontStyle('italic');
}

// ===== トリガー設定・メニュー関連 =====
function setupTrigger() {
  deleteTrigger('syncBigQueryData');
  ScriptApp.newTrigger('syncBigQueryData')
    .timeBased()
    .everyMinutes(15)
    .create();
  SpreadsheetApp.getUi().alert('15分ごとの自動同期を設定しました。');
}

function deleteTrigger(functionName) {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === functionName)
    .forEach(t => ScriptApp.deleteTrigger(t));
}

function removeTrigger() {
  deleteTrigger('syncBigQueryData');
  SpreadsheetApp.getUi().alert('自動同期を停止しました。');
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('BigQuery同期')
    .addItem('全データを同期', 'syncBigQueryData')
    .addItem('響LU反響数のみ同期', 'syncHibikiInquiryCount')
    .addSeparator()
    .addItem('自動同期を開始（15分ごと）', 'setupTrigger')
    .addItem('自動同期を停止', 'removeTrigger')
    .addToUi();
}

function formatNow() {
  return Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy/MM/dd HH:mm:ss');
}