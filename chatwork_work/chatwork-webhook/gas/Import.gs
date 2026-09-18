/**
 * 1. 「ぽけてる予約一覧CSV」を受け取り、ステータスが「完了」の案件を抽出・フィルタリング
 * 2. 「Lステップ友達詳細CSV」を氏名正規化で突合
 * 3. これらを組み合わせてスプレッドシート上のデータとマッピング・更新する処理
 */

// 依頼者名の突き合わせに使う名前系の列（どれか1つでも一致すればOK）
const NAME_LABELS = ['表示名', 'LINE登録名', '本名', 'システム表示名'];

// 「事務所名」から右の列を、入力必須項目とみなす
const REQUIRED_LABELS = [
  '事務所名', '予約獲得', '提案予約日', '提案', '面談実施日',
  '受任', '担当弁護士', '業者数', '面談結果', '請求方法',
  '利用総額', 'チャージバック 利用額', '担当者',
];

// 末尾に付いていたら除去する敬称
const HONORIFIC_SUFFIXES = ['様', 'さん', '君', '殿', '氏'];

// 頻出する異体字を正規形に統一する
const KANJI_VARIANTS = {
  '髙': '高', '﨑': '崎', '邊': '辺', '邉': '辺',
  '齋': '斎', '齊': '斎', '斉': '斎',
  '澤': '沢', '廣': '広', '櫻': '桜', '塜': '塚',
  '國': '国', '曾': '曽', '龍': '竜', '濱': '浜',
  '冨': '富', '𠮷': '吉', '德': '徳', '檜': '桧',
  '峯': '峰', '栢': '柏',
};

const PURE_KANA_RE = /^[ぁ-んァ-ヶー]+$/;
const PAREN_RE = /[（(][^）)]*[）)]/g;

function unifyKanjiVariants_(s) {
  let out = '';
  for (const ch of s) {
    out += KANJI_VARIANTS[ch] || ch;
  }
  return out;
}

/**
 * 依頼者名・CSV側の名前双方に使う正規化。以下を順に行う:
 *   1. 括弧内の読み仮名を除去
 *   2. スラッシュ以降の読みを除去
 *   3. 敬称（様・さん等）を除去
 *   4. 名前の前後に別トークンとして付いている読み仮名を除去
 *   5. 半角/全角スペースを除去
 *   6. 頻出異体字を正規形に統一
 */
function normalizeName_(s) {
  if (!s) return '';
  let raw = String(s).trim();
  if (!raw) return '';
  raw = raw.replace(PAREN_RE, '');
  raw = raw.split('/')[0];
  let tokens = raw.split(/[\s　]+/).filter(Boolean);
  tokens = tokens.filter((t) => HONORIFIC_SUFFIXES.indexOf(t) === -1);
  const nonKana = tokens.filter((t) => !PURE_KANA_RE.test(t));
  const coreTokens = nonKana.length > 0 ? nonKana : tokens;
  return unifyKanjiVariants_(coreTokens.join(''));
}

/**
 * ぽけてる予約一覧CSVを解析し、ステータスが「完了」の案件を抽出してマップを返す
 * @param {string} base64Data
 * @return {Object} 完了案件の顧客名正規化キー => 予約データのマップ
 */
function parsePoketeruCompletedCsv_(base64Data) {
  const bytes = Utilities.base64Decode(base64Data);
  const blob = Utilities.newBlob(bytes);
  const csvText = blob.getDataAsString('Windows-31J');
  const rows = Utilities.parseCsv(csvText);

  if (rows.length < 2) {
    throw new Error('ぽけてる予約一覧CSVの行数が不足しています');
  }

  const header = rows[0];
  // 例: 日時, 顧客名, 電話番号, チャネル, 事務所, CS担当, 面談担当(先生), ステータス, 対応可能時間
  const customerIdx = header.indexOf('顧客名');
  const statusIdx = header.indexOf('ステータス');

  if (customerIdx === -1 || statusIdx === -1) {
    throw new Error('ぽけてる予約一覧CSVに「顧客名」または「ステータス」列が見つかりません');
  }

  const completedMap = {};
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    const status = row[statusIdx] ? row[statusIdx].trim() : '';
    if (status === '完了') {
      const customerName = row[customerIdx];
      const key = normalizeName_(customerName);
      if (key) {
        completedMap[key] = row;
      }
    }
  }
  return completedMap;
}

/**
 * Lステップ友だち詳細CSVとぽけてる予約一覧CSV（完了案件）の両方を受け取り、
 * スプレッドシートをマッピング・更新する統合処理関数
 * @param {string} lstepBase64 Lステップ友達詳細CSVのBase64
 * @param {string} poketeruBase64 ぽけてる予約一覧CSVのBase64 (省略可・null可)
 * @param {string} targetSheetChoice シート名、または '__ALL__'
 * @return {string} 処理結果サマリー
 */
function processDualCsv(lstepBase64, poketeruBase64, targetSheetChoice) {
  // 1. LステップCSVのパース
  const lstepBytes = Utilities.base64Decode(lstepBase64);
  const lstepBlob = Utilities.newBlob(lstepBytes);
  const lstepText = lstepBlob.getDataAsString('Windows-31J');
  const lstepRows = Utilities.parseCsv(lstepText);

  if (lstepRows.length < 3) {
    throw new Error('LステップCSVの行数が想定と異なります（ヘッダー2行+データ行が必要です）');
  }

  const labelRow = lstepRows[1];
  const nameIdxs = NAME_LABELS.map((label) => {
    const idx = labelRow.indexOf(label);
    if (idx === -1) throw new Error(`LステップCSVに列「${label}」が見つかりません`);
    return idx;
  });
  const requiredIdx = REQUIRED_LABELS.map((label) => {
    const idx = labelRow.indexOf(label);
    if (idx === -1) throw new Error(`LステップCSVに列「${label}」が見つかりません`);
    return idx;
  });

  const lstepByName = {};
  for (let i = 2; i < lstepRows.length; i++) {
    const row = lstepRows[i];
    nameIdxs.forEach((idx) => {
      const key = normalizeName_(row[idx]);
      if (key && !lstepByName[key]) {
        lstepByName[key] = row;
      }
    });
  }

  // 2. ぽけてる予約一覧CSVのパース（指定されている場合）
  let poketeruCompletedMap = null;
  if (poketeruBase64 && poketeruBase64.trim() !== '') {
    poketeruCompletedMap = parsePoketeruCompletedCsv_(poketeruBase64);
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
    let poketeruMatchedCount = 0;

    applicantNames.forEach(([name]) => {
      const key = normalizeName_(name);
      if (!key) {
        results.push(['']);
        return;
      }

      // ぽけてるCSVが指定されている場合の完了案件チェック（オプション/補足連携）
      if (poketeruCompletedMap) {
        const isPoketeruCompleted = !!poketeruCompletedMap[key];
        if (isPoketeruCompleted) {
          poketeruMatchedCount++;
        }
      }

      const row = lstepByName[key];
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
    
    let lineSummary = `${sheetName}: 一致${matched}件（完了${complete}件） / 未一致${notFound}件`;
    if (poketeruCompletedMap) {
      lineSummary += ` [ぽけてる完了一致: ${poketeruMatchedCount}件]`;
    }
    summaryLines.push(lineSummary);
  });

  return summaryLines.join('\n');
}

/**
 * 既存互換用の関数（LステップCSV単体処理）
 */
function processFriendCsv(base64Data, targetSheetChoice) {
  return processDualCsv(base64Data, null, targetSheetChoice);
}
