// ===== 設定 =====
const ADDRESS_SYNC_CONFIG = {
  projectId: 'consulting-report',
  sheetName: '今月面談住所一覧',
  query: 'SELECT ' +
         '  office_key AS `事務所名`, ' +
         '  id AS `相談者ID`, ' +
         '  pre_delegation_date AS `面談予約日`, ' +
         '  address_zip AS `郵便番号`, ' +
         '  address AS `現住所`, ' +
         '  interview_date AS `面談日`, ' +
         '  document_return_date AS `書類戻り日`, ' +
         '  delegation_date AS `受任日`, ' +
         '  latest_interview_date AS `最新面談予定日` ' +
         'FROM ( ' +
         '  SELECT c.id, c.pre_delegation_date, c.address_zip, c.address, c.interview_date, c.document_return_date, c.delegation_date, ' +
         '         (SELECT MAX(interview_at) FROM `se-leadu.conpas_debt_hibiki.interviews` i WHERE i.consulter_id = c.id AND i.deleted_at IS NULL) AS latest_interview_date, ' +
         '         \'hibiki\' as office_key ' +
         '  FROM `se-leadu.conpas_debt_hibiki.consulters` c WHERE c.deleted_at is null ' +
         '  UNION ALL ' +
         '  SELECT c.id, c.pre_delegation_date, c.address_zip, c.address, c.interview_date, c.document_return_date, c.delegation_date, ' +
         '         (SELECT MAX(interview_at) FROM `se-leadu.conpas_debt_aegislo.interviews` i WHERE i.consulter_id = c.id AND i.deleted_at IS NULL) AS latest_interview_date, ' +
         '         \'aegislo\' as office_key ' +
         '  FROM `se-leadu.conpas_debt_aegislo.consulters` c WHERE c.deleted_at is null ' +
         '  UNION ALL ' +
         '  SELECT c.id, c.pre_delegation_date, c.address_zip, c.address, c.interview_date, c.document_return_date, c.delegation_date, ' +
         '         (SELECT MAX(interview_at) FROM `se-leadu.conpas_debt_thank.interviews` i WHERE i.consulter_id = c.id AND i.deleted_at IS NULL) AS latest_interview_date, ' +
         '         \'thank\' as office_key ' +
         '  FROM `se-leadu.conpas_debt_thank.consulters` c WHERE c.deleted_at is null ' +
         '  UNION ALL ' +
         '  SELECT c.id, c.pre_delegation_date, c.address_zip, c.address, c.interview_date, c.document_return_date, c.delegation_date, ' +
         '         (SELECT MAX(interview_at) FROM `se-leadu.conpas_debt_kaname.interviews` i WHERE i.consulter_id = c.id AND i.deleted_at IS NULL) AS latest_interview_date, ' +
         '         \'honoka\' as office_key ' +
         '  FROM `se-leadu.conpas_debt_kaname.consulters` c WHERE c.deleted_at is null ' +
         '  UNION ALL ' +
         '  SELECT c.id, c.pre_delegation_date, c.address_zip, c.address, c.interview_date, c.document_return_date, c.delegation_date, ' +
         '         (SELECT MAX(interview_at) FROM `se-leadu.conpas_debt_mitsuba.interviews` i WHERE i.consulter_id = c.id AND i.deleted_at IS NULL) AS latest_interview_date, ' +
         '         \'mitsuba\' as office_key ' +
         '  FROM `se-leadu.conpas_debt_mitsuba.consulters` c WHERE c.deleted_at is null ' +
         ') ' +
         'WHERE ' +
         '  DATE_TRUNC(pre_delegation_date, MONTH) = DATE_TRUNC(CURRENT_DATE(), MONTH)'
};

// ===== メイン同期関数（手動・トリガー共用）=====
function syncBigQueryData() {
  syncCurrentMonthAddresses();
}

// ===== 今月面談住所一覧の同期実行 =====
function syncCurrentMonthAddresses() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(ADDRESS_SYNC_CONFIG.sheetName);

  if (!sheet) {
    sheet = ss.insertSheet(ADDRESS_SYNC_CONFIG.sheetName);
  }

  try {
    const data = fetchBigQueryDataByQuery(ADDRESS_SYNC_CONFIG.query);

    if (!data || data.length === 0) {
      Logger.log('データが0件でした。');
      updateStatusCell(sheet, 'データ0件 - ' + formatNow());
    } else {
      writeToSheet(sheet, data);
      updateStatusCell(sheet, '最終同期: ' + formatNow() + '  (' + (data.length - 1) + '行)');
      Logger.log('同期完了: ' + (data.length - 1) + '行');
    }

  } catch (e) {
    Logger.log('エラー: ' + e.message);
    updateStatusCell(sheet, 'エラー: ' + e.message + ' - ' + formatNow());
    throw e;
  }
}

// ===== 汎用的なクエリ実行関数 =====
function fetchBigQueryDataByQuery(sqlQuery) {
  // BigQueryサービスが有効かチェック
  if (typeof BigQuery === 'undefined') {
    throw new Error('BigQuery APIサービスが有効になっていません。[リソース] > [Google の拡張サービス] (または [サービス] +) から BigQuery API を有効にしてください。');
  }

  const jobConfig = {
    configuration: {
      query: {
        query: sqlQuery,
        useLegacySql: false,
      },
    },
  };

  try {
    let job = BigQuery.Jobs.insert(jobConfig, ADDRESS_SYNC_CONFIG.projectId);
    const jobId = job.jobReference.jobId;
    const location = job.jobReference.location;

    Logger.log('BigQueryジョブを開始しました。JobId: ' + jobId);

    let status = job.status.state;
    let attempts = 0;
    while (status !== 'DONE' && attempts < 60) {
      Utilities.sleep(2000);
      job = BigQuery.Jobs.get(ADDRESS_SYNC_CONFIG.projectId, jobId, { location: location });
      status = job.status.state;
      attempts++;
    }

    if (status !== 'DONE') {
      throw new Error('BigQueryジョブがタイムアウトしました。状態: ' + status);
    }
    
    if (job.status.errorResult) {
      const errorMsg = 'BigQueryエラー: ' + job.status.errorResult.message + ' (理由: ' + job.status.errorResult.reason + ')';
      Logger.log(errorMsg);
      throw new Error(errorMsg);
    }

    let results = BigQuery.Jobs.getQueryResults(ADDRESS_SYNC_CONFIG.projectId, jobId, { maxResults: 10000, location: location });
    let rows = results.rows || [];

    while (results.pageToken) {
      results = BigQuery.Jobs.getQueryResults(ADDRESS_SYNC_CONFIG.projectId, jobId, {
        pageToken: results.pageToken,
        maxResults: 10000,
        location: location,
      });
      rows = rows.concat(results.rows || []);
    }

    if (!results.schema || rows.length === 0) {
      return [];
    }

    const headers = results.schema.fields.map(function(f) { return f.name; });
    const dataRows = rows.map(function(row) {
      return row.f.map(function(cell) { return cell.v === null ? '' : cell.v; });
    });

    Logger.log('データ取得完了: ' + dataRows.length + '件');
    return [headers].concat(dataRows);

  } catch (e) {
    const fullError = 'BigQuery実行例外: ' + e.toString() + ' \nSQL: ' + sqlQuery;
    Logger.log(fullError);
    throw new Error(fullError);
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

function formatNow() {
  return Utilities.formatDate(new Date(), 'JST', 'yyyy/MM/dd HH:mm:ss');
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('BigQuery同期')
    .addItem('今月面談住所一覧を同期', 'syncCurrentMonthAddresses')
    .addItem('15分ごとの自動同期を設定', 'setupTrigger')
    .addItem('自動同期を停止', 'removeTrigger')
    .addToUi();
}
