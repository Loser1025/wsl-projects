/**
 * Lステップの「友だち詳細」CSVエクスポートを読み込み、依頼者名（G列）と
 * 表示名/LINE登録名/本名/システム表示名の4項目で突き合わせて、
 * 事務所名より右の全項目が埋まっているかをH列（友達情報）に書き込む。
 *
 * CSVの想定フォーマット:
 *   1行目: 内部の友だち情報ID（友だち情報_XXXXXXX 等）
 *   2行目: 表示ラベル（ID, 表示名, LINE登録名, 本名, システム表示名, 事務所名, ...）
 *   3行目以降: 実データ（Shift-JIS）
 */

// 依頼者名の突き合わせに使う名前系の列（どれか1つでも一致すればOK）
const NAME_LABELS = ['表示名', 'LINE登録名', '本名', 'システム表示名'];

// 「事務所名」から右の列を、入力必須項目とみなす
const REQUIRED_LABELS = [
  '事務所名', '予約獲得', '提案予約日', '提案', '面談実施日',
  '受任', '担当弁護士', '業者数', '面談結果', '請求方法',
  '利用総額', 'チャージバック 利用額', '担当者',
];

function normalizeName_(s) {
  if (!s) return '';
  return String(s).replace(/[\s　]/g, '');
}

/**
 * @param {string} base64Data CSVファイルのBase64エンコード済みデータ
 * @param {string} targetSheetChoice シート名、または全シート対象なら '__ALL__'
 * @return {string} 処理結果のサマリー（ダイアログに表示する）
 */
function processFriendCsv(base64Data, targetSheetChoice) {
  const bytes = Utilities.base64Decode(base64Data);
  const blob = Utilities.newBlob(bytes);
  const csvText = blob.getDataAsString('Shift_JIS');
  const rows = Utilities.parseCsv(csvText);

  if (rows.length < 3) {
    throw new Error('CSVの行数が想定と異なります（ヘッダー2行+データ行が必要です）');
  }

  const labelRow = rows[1];
  const nameIdxs = NAME_LABELS.map((label) => {
    const idx = labelRow.indexOf(label);
    if (idx === -1) throw new Error(`CSVに列「${label}」が見つかりません`);
    return idx;
  });
  const requiredIdx = REQUIRED_LABELS.map((label) => {
    const idx = labelRow.indexOf(label);
    if (idx === -1) throw new Error(`CSVに列「${label}」が見つかりません`);
    return idx;
  });

  // 名前 -> 行データ のマップを作る。表示名/LINE登録名/本名/システム表示名の
  // いずれか1つでも一致すればヒットするよう、4項目すべてをキーとして登録する
  // （同じキーが複数の友だちで重複する場合は最初に見つかった方を優先）
  const byName = {};
  for (let i = 2; i < rows.length; i++) {
    const row = rows[i];
    nameIdxs.forEach((idx) => {
      const key = normalizeName_(row[idx]);
      if (key && !byName[key]) {
        byName[key] = row;
      }
    });
  }

  const targets = targetSheetChoice === '__ALL__'
    ? getDateSheetNames_()
    : [targetSheetChoice];

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const summaryLines = [];

  targets.forEach((sheetName) => {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      summaryLines.push(`${sheetName}: シートが見つかりません`);
      return;
    }
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) {
      summaryLines.push(`${sheetName}: 対象データなし`);
      return;
    }

    const applicantNames = sheet.getRange(2, 7, lastRow - 1, 1).getValues(); // G列=依頼者名
    const results = [];
    let matched = 0;
    let complete = 0;
    let notFound = 0;

    applicantNames.forEach(([name]) => {
      const key = normalizeName_(name);
      if (!key) {
        results.push(['']);
        return;
      }
      const row = byName[key];
      if (!row) {
        results.push(['該当なし']);
        notFound++;
        return;
      }
      matched++;
      const missing = [];
      requiredIdx.forEach((idx, i) => {
        if (!row[idx] || !String(row[idx]).trim()) missing.push(REQUIRED_LABELS[i]);
      });
      if (missing.length === 0) {
        results.push(['済']);
        complete++;
      } else {
        results.push([`未：${missing.join('、')}`]);
      }
    });

    sheet.getRange(2, 8, results.length, 1).setValues(results); // H列=友達情報
    summaryLines.push(`${sheetName}: 一致${matched}件（完了${complete}件） / 未一致${notFound}件`);
  });

  return summaryLines.join('\n');
}
