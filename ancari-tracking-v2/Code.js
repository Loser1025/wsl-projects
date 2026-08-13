/**
 * ANCARI トラッキング用 GASスクリプト v2（別ドメイン運用版）
 * すべてのイベントを直接 ANCARI_analytics スプレッドシートに記録する。
 */

var SPS_ID = '1z9Ng_xg860-AhhU1U_wLDx152kt5VK2Wz1XcyyIqt0g';

function doOptions(e) {
  return ContentService.createTextOutput('');
}

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var sps = SpreadsheetApp.openById(SPS_ID);

    switch (data.type) {
      case 'test_start':
        logEvent(sps, 'Test_Starts', data);
        updateSPSFunnel(sps, '診断テスト開始');
        break;
      case 'test_complete':
        logTestComplete(sps, data);
        updateSPSFunnel(sps, '診断テスト完了');
        updateSPSTypeCount(sps, data.typeKey, data.typeName);
        break;
      case 'form_submit':
        logFormSubmit(sps, data);
        updateSPSFunnel(sps, 'フォーム送信');
        break;
      case 'line_click':
        logEvent(sps, 'LINE_Clicks', data);
        updateSPSFunnel(sps, 'LINE登録クリック');
        break;
      case 'lp_view':
        logEvent(sps, 'LP_Views', data);
        updateSPSFunnel(sps, 'LP訪問');
        break;
      default:
        logEvent(sps, 'Other_Events', data);
    }

    return ContentService
      .createTextOutput(JSON.stringify({ status: 'ok' }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: 'error', message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ── ログ関数 ──────────────────────────

function getOrCreateSheet(ss, name, headers) {
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.appendRow(headers);
    sheet.getRange(1, 1, 1, headers.length)
      .setFontWeight('bold')
      .setBackground('#0A1628')
      .setFontColor('#FFFFFF');
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function logEvent(sps, sheetName, data) {
  var headers = ['日時', 'セッションID', 'イベント', 'UA'];
  var sheet = getOrCreateSheet(sps, sheetName, headers);
  sheet.appendRow([
    new Date(),
    data.sid || '',
    data.type || '',
    (data.ua || '').substring(0, 80)
  ]);
}

function logTestComplete(sps, data) {
  var headers = ['日時', 'セッションID', 'タイプキー', 'タイプ名', '回答'];
  var sheet = getOrCreateSheet(sps, 'Test_Completes', headers);
  sheet.appendRow([
    new Date(),
    data.sid || '',
    data.typeKey || '',
    data.typeName || '',
    data.answers || ''
  ]);
}

function logFormSubmit(sps, data) {
  var headers = ['日時', 'お名前', 'メールアドレス', 'タイプキー', 'タイプ名', 'セッションID'];
  var sheet = getOrCreateSheet(sps, '診断応募者リスト', headers);
  sheet.appendRow([
    new Date(),
    data.name || '',
    data.email || '',
    data.typeKey || '',
    data.typeName || '',
    data.sid || ''
  ]);
}

// ── ファネル集計 ──────────────────────

function updateSPSFunnel(sps, stageName) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(5000);
    var sheet = sps.getSheetByName('ファネル分析')
             || sps.getSheetByName('🎯 ファネル分析');
    if (!sheet) return;
    var lastRow = sheet.getLastRow();
    if (lastRow < 2) return;

    var stageCol = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
    for (var i = 0; i < stageCol.length; i++) {
      var cellVal = stageCol[i][0] ? stageCol[i][0].toString() : '';
      if (cellVal.indexOf(stageName) > -1 || stageName.indexOf(cellVal) > -1) {
        var targetRow = i + 2;
        var cell = sheet.getRange(targetRow, 2);
        var currentVal = cell.getValue();
        cell.setValue((currentVal && !isNaN(currentVal)) ? Number(currentVal) + 1 : 1);
        break;
      }
    }
  } catch (err) {
    Logger.log('SPS funnel error: ' + err.toString());
  } finally {
    lock.releaseLock();
  }
}

function updateSPSTypeCount(sps, typeKey, typeName) {
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(5000);
    var sheet = sps.getSheetByName('診断タイプ集計');
    if (!sheet) {
      sheet = sps.insertSheet('診断タイプ集計');
      sheet.appendRow(['タイプキー', 'タイプ名', '件数', '最終更新']);
      sheet.getRange(1, 1, 1, 4).setFontWeight('bold').setBackground('#0A1628').setFontColor('#FFFFFF');
      sheet.setFrozenRows(1);
    }

    var lastRow = sheet.getLastRow();
    var found = false;
    if (lastRow >= 2) {
      var data = sheet.getRange(2, 1, lastRow - 1, 3).getValues();
      for (var i = 0; i < data.length; i++) {
        if (data[i][0] === typeKey) {
          var row = i + 2;
          sheet.getRange(row, 3).setValue((data[i][2] || 0) + 1);
          sheet.getRange(row, 4).setValue(new Date());
          found = true;
          break;
        }
      }
    }
    if (!found) {
      sheet.appendRow([typeKey, typeName || typeKey, 1, new Date()]);
    }
  } catch (err) {
    Logger.log('SPS type count error: ' + err.toString());
  } finally {
    lock.releaseLock();
  }
}
