function ping() {
  return 'pong ' + new Date().toISOString();
}

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
 * HTMLから送信されたファイルオブジェクトを受け取り、LUシートに出力する
 */
function processCsvViaBlob(fileObject) {
  try {
    const targetSS = SpreadsheetApp.getActiveSpreadsheet();
    const targetSheet = targetSS.getSheetByName('LU'); 
    if (!targetSheet) throw new Error('シート「LU」が見つかりません');

    const LU_HEADER_ROW = 2;
    const LU_DATA_COL_COUNT = 5; 
    const robustTrim = (s) => (typeof s === 'string' ? s.replace(/^[\s\uFEFF\u00A0]+|[\s\uFEFF\u00A0]+$/g, "") : s);

    // ファイルオブジェクトから直接Blobを作成してテキスト化
    const blob = Utilities.newBlob(Utilities.base64Decode(fileObject.data), fileObject.mimeType, fileObject.name);
    const csvRawText = blob.getDataAsString('UTF-8');
    // クォート内の改行を誤って行区切りとして扱わないよう、CSV全体を1回でパースする
    const parsedRows = parseCsv(csvRawText).filter(row => row.length > 1 || (row[0] !== undefined && row[0] !== ""));
    if (parsedRows.length < 1) throw new Error("CSVファイルが空、または解析可能なデータがありません。");

    // 1行目のヘッダー行を解析
    const uploadHeaderRow = parsedRows[0].map(robustTrim);

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
    for (let i = 1; i < parsedRows.length; i++) {
      const row = parsedRows[i];
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
      return `✅ アップロード成功！\n${rowsToAppend.length} 行のデータを「LU」シートへ出力しました。`;
    } else {
      return "ℹ️ 取り込むデータ行がありませんでした。";
    }

  } catch (e) {
    throw new Error(e.message);
  }
}

/**
 * CSV全体を1パスでパースする。ダブルクォートで囲まれたセル内の改行・カンマは
 * データの一部として扱われるため、行区切りとして誤爆しない。
 */
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  let i = 0;
  const len = text.length;

  while (i < len) {
    const ch = text[i];

    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
        inQuotes = false; i++; continue;
      }
      field += ch; i++; continue;
    }

    if (ch === '"') { inQuotes = true; i++; continue; }
    if (ch === ',') { row.push(field); field = ''; i++; continue; }
    if (ch === '\r') { i++; continue; }
    if (ch === '\n') {
      row.push(field); field = '';
      rows.push(row); row = [];
      i++; continue;
    }
    field += ch; i++;
  }

  row.push(field);
  if (row.length > 1 || row[0] !== '') rows.push(row);

  return rows.map(r => r.map(v => v.trim()));
}

function formatToNumber(value) {
  if (value === undefined || value === null) return "";
  const trimmedValue = String(value).trim();
  if (trimmedValue === '') return "";
  const cleanedValue = trimmedValue.replace(/,/g, '');
  if (!isNaN(cleanedValue) && cleanedValue !== '') { return Number(cleanedValue); }
  return value;
}