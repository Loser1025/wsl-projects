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
 *   1. 括弧内の読み仮名を除去（例: 北林広至(キタバヤシヒロシ) → 北林広至）
 *   2. スラッシュ以降の読みを除去（例: 太田涼允/おおたりょうすけ → 太田涼允）
 *   3. 敬称（様・さん等）を除去
 *   4. 名前の前後に別トークンとして付いている読み仮名(ひらがな/カタカナ)を除去
 *      （例: 平塚 勝也　ヒラツカ カツヤ → 平塚勝也、いとうたいき 伊藤汰樹 → 伊藤汰樹）
 *      ただし全トークンが仮名の場合はそのまま残す（純粋な仮名の名前を保護するため）
 *   5. 半角/全角スペースを除去
 *   6. 頻出異体字を正規形に統一（例: 髙橋 → 高橋）
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
 * @param {string} base64Data CSVファイルのBase64エンコード済みデータ
 * @param {string} targetSheetChoice シート名、または全シート対象なら '__ALL__'
 * @return {string} 処理結果のサマリー（ダイアログに表示する）
 */
function processFriendCsv(base64Data, targetSheetChoice) {
  const bytes = Utilities.base64Decode(base64Data);
  const blob = Utilities.newBlob(bytes);
  // 'Shift_JIS'指定だと髙・﨑・𠮷等の拡張漢字(Windowsが独自に追加した文字)が
  // 文字化けして失われることを実データで確認したため、Windows-31J(CP932)を使う
  const csvText = blob.getDataAsString('Windows-31J');
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
