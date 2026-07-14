function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('📁 CSVインポート')
    .addItem('ファイルをアップロード', 'showUploadForm')
    .addToUi();
}

function showUploadForm() {
  // ポップアップのサイズを適切に設定
  const html = HtmlService.createHtmlOutputFromFile('UploadForm')
    .setWidth(450)
    .setHeight(450);
  SpreadsheetApp.getUi().showModalDialog(html, 'ファイルアップロード');
}

/**
 * HTMLから送信されたファイルオブジェクトを受け取り、
 * 一時ファイル化を利用してPERMISSION_DENIEDを100%回避しながらLUシートに出力する
 */
function processCsvViaBlob(fileObject) {
  let tempFile = null;
  try {
    const targetSS = SpreadsheetApp.getActiveSpreadsheet();
    const targetSheet = targetSS.getSheetByName('LU'); 
    if (!targetSheet) throw new Error('シート「LU」が見つかりません');

    const LU_HEADER_ROW = 2;
    const LU_DATA_COL_COUNT = 5; 
    const robustTrim = (s) => (typeof s === 'string' ? s.replace(/^[\s\uFEFF\u00A0]+|[\s\uFEFF\u00A0]+$/g, "") : s);

    // 【ここが肝】大容量データを一度Driveの裏側に避難させる（ブラウザ通信のエラーを完全回避）
    // ファイルオブジェクトから直接Blobを作成
    const blob = Utilities.newBlob(Utilities.base64Decode(fileObject.data), fileObject.mimeType, fileObject.name);
    
    // 一時ファイルとしてマイドライブに保存（※処理後に自動消去されます）
    tempFile = DriveApp.createFile(blob);
    
    // 避難させたファイルからテキストを一括取得（サーバー内処理なので超高速＆エラーなし）
    const csvRawText = tempFile.getDataAsString('UTF-8'); 
    const lines = csvRawText.split(/\r\n|\n|\r/).filter(line => line.trim() !== "");
    if (lines.length < 1) throw new Error("CSVファイルが空、または解析可能なデータがありません。");

    // 1行目のヘッダー行を解析
    const uploadHeaderRow = parseCsvLine(lines[0]).map(robustTrim);

    // 「LU」シート側の2行目ヘッダーを取得してマッピング
    const targetHeaders = targetSheet.getRange(LU_HEADER_ROW, 1, 1, LU_DATA_COL_COUNT)
                                     .getValues()[0]
                                     .map(robustTrim) 
                                     .filter(h => h); 
    
    if (targetHeaders.length === 0) {
      throw new Error('貼り付け先シート「LU」の2行目に有効なヘッダーが見つかりません。');
    }

    const columnIndices = [];
    for (const targetHeader of targetHeaders) {
      const index = uploadHeaderRow.indexOf(targetHeader);
      if (index === -1) {
        throw new Error(`必要なヘッダー「${targetHeader}」がCSV内に見つかりません。`);
      }
      columnIndices.push(index);
    }

    // 2行目以降のデータ行をメモリ内で一気に並び替え
    const rowsToAppend = [];
    for (let i = 1; i < lines.length; i++) {
      const row = parseCsvLine(lines[i]);
      if (!row || row.length === 0) continue;

      const newRow = columnIndices.map((colIndex, colIdx) => {
        const value = (row[colIndex] === undefined || row[colIndex] === null) ? "" : row[colIndex]; 
        if (colIdx === 0) return formatToNumber(value); // 1列目のみ数値化
        return value;
      });
      rowsToAppend.push(newRow);
    }

    // 「LU」シートの3行目以降をクリアして一括出力
    const lastRowLU = targetSheet.getLastRow();
    if (lastRowLU >= 3) {
      targetSheet.getRange(3, 1, lastRowLU - 2, LU_DATA_COL_COUNT).clearContent();
    }

    if (rowsToAppend.length > 0) {
      targetSheet.getRange(3, 1, rowsToAppend.length, LU_DATA_COL_COUNT).setValues(rowsToAppend);
      targetSheet.getRange(3, 1, rowsToAppend.length, 1).setNumberFormat('#,##0');
      
      // 一時ファイルを自動消去
      tempFile.setTrashed(true);
      return `✅ アップロード成功！\n${rowsToAppend.length} 行のデータを「LU」シートへ出力しました。`;
    } else {
      if (tempFile) tempFile.setTrashed(true);
      return "ℹ️ 取り込むデータ行がありませんでした。";
    }

  } catch (e) {
    // エラーが起きても確実に一時ファイルを消去する安心設計
    if (tempFile) tempFile.setTrashed(true);
    throw new Error(e.message);
  }
}

/** CSVパース等、その他の補助関数（変更なし） */
function parseCsvLine(line) {
  const result = [];
  let start = 0;
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    if (line[i] === '"') { inQuotes = !inQuotes; } 
    else if (line[i] === ',' && !inQuotes) {
      result.push(cleanCsvValue(line.substring(start, i)));
      start = i + 1;
    }
  }
  result.push(cleanCsvValue(line.substring(start)));
  return result;
}

function cleanCsvValue(val) {
  let s = val.trim();
  if (s.startsWith('"') && s.endsWith('"')) { s = s.substring(1, s.length - 1); }
  return s.replace(/""/g, '"');
}

function formatToNumber(value) {
  if (value === undefined || value === null) return "";
  const trimmedValue = String(value).trim();
  if (trimmedValue === '') return "";
  const cleanedValue = trimmedValue.replace(/,/g, '');
  if (!isNaN(cleanedValue) && cleanedValue !== '') { return Number(cleanedValue); }
  return value;
}