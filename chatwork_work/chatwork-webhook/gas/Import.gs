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
// 括弧内にさらに半角括弧が1段だけ入れ子になっているケース（例:「さかい(箱)」）も
// 丸ごと1つの括弧として除去できるよう、入れ子を許容する
const PAREN_RE = /[（(](?:[^（）()]|[（(][^（）()]*[）)])*[）)]/g;
// 依頼者名「本名（LINE名: ニックネーム）」末尾の括弧全体（入れ子1段まで許容）を取り出す
const APPLICANT_PAREN_CONTENT_RE = /[（(]((?:[^（）()]|[（(][^（）()]*[）)])*)[）)]\s*$/;
const LINE_NAME_RE = /LINE名[:：]\s*(.+)/;
// 「面談対応(先生): 〇〇〇〇【事務所名】」の【】部分を取り出す
const OFFICE_RE = /【(.+?)】/;
// 日付候補（YYYY-MM-DD / YYYY/MM/DD、時刻付きも可）の先頭一致
const YMD_RE = /^(\d{4})[-\/](\d{1,2})[-\/](\d{1,2})/;
const DATE_MATCH_WINDOW_MS = 7 * 24 * 60 * 60 * 1000; // 日付突合の許容幅（7日）

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

/** 「本名（LINE名: ニックネーム）」形式からLINE名部分だけを正規化して返す。無ければ空文字
 * 末尾の括弧全体（入れ子1段まで）をまず取り出してから中身を見るため、
 * ニックネーム自体に半角括弧が含まれる場合（例:「さかい(箱)」）でも途中で切れない */
function extractLineNameCandidate_(applicantRaw) {
  const s = String(applicantRaw || '');
  const parenMatch = APPLICANT_PAREN_CONTENT_RE.exec(s);
  const content = parenMatch ? parenMatch[1] : s;
  const m = LINE_NAME_RE.exec(content);
  return m ? normalizeName_(m[1].trim()) : '';
}

/** 「面談対応(先生): 〇〇〇〇【事務所名】」の【】部分を取り出す。無ければ空文字 */
function extractOffice_(teacherField) {
  const m = OFFICE_RE.exec(String(teacherField || ''));
  return m ? m[1].trim() : '';
}

/** "2026-09-14 13:45" / "2026/09/14" 等の先頭日付部分だけをUnix時刻(ms)に変換。パース不可ならnull */
function parseYmd_(s) {
  if (!s) return null;
  const m = YMD_RE.exec(String(s).trim());
  if (!m) return null;
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return isNaN(d.getTime()) ? null : d.getTime();
}

/**
 * 候補が複数ある場合に、日付が最も近い1件だけに絞り込む。
 * 最も近い候補が2件以上（同点）の場合や、許容幅(7日)を超える場合は諦めてnullを返す
 * （安全側：誤マッチよりも「該当なし」を優先）
 */
function narrowByDate_(candidates, messageDateMs, proposalIdx, interviewIdx) {
  if (messageDateMs == null) return null;
  const scored = candidates
    .map((row) => {
      const d1 = parseYmd_(row[proposalIdx]);
      const d2 = parseYmd_(row[interviewIdx]);
      const diffs = [d1, d2].filter((d) => d !== null).map((d) => Math.abs(d - messageDateMs));
      return { row: row, diff: diffs.length ? Math.min.apply(null, diffs) : Infinity };
    })
    .filter((s) => s.diff <= DATE_MATCH_WINDOW_MS);
  if (scored.length === 0) return null;
  scored.sort((a, b) => a.diff - b.diff);
  if (scored.length === 1 || scored[0].diff < scored[1].diff) return scored[0].row;
  return null;
}

/**
 * 候補配列(同じキーに複数のLステップ行がぶら下がっている場合がある)を、
 * 事務所名でまず絞り込み、それでも複数残る場合のみ日付で最終タイブレークする。
 * 事務所名が不明（本文に【】が無い等）な状態で候補が複数残る場合は、
 * 日付だけを頼りに当てにいくと誤爆リスクが高いため確定させずnullを返す
 */
function narrowCandidates_(candidates, office, officeIdx, messageDateMs, proposalIdx, interviewIdx) {
  if (!candidates || candidates.length === 0) return null;
  if (candidates.length === 1) return candidates[0];
  if (!office) return null;

  const byOffice = candidates.filter((row) => (row[officeIdx] || '').trim() === office);
  if (byOffice.length === 0) return null;
  if (byOffice.length === 1) return byOffice[0];

  return narrowByDate_(byOffice, messageDateMs, proposalIdx, interviewIdx);
}

/**
 * 依頼者名からLステップ行を特定する。本名で一意に決まらない場合は、
 * 括弧内のLINE名でも試し、複数候補が残る場合は事務所名→日付で絞り込む。
 * @return {{row: (Array|null), method: (string|null)}}
 */
function resolveLstepRow_(lstepByKey, applicantRaw, ctx) {
  const baseKey = normalizeName_(applicantRaw);
  const narrow = (candidates) => narrowCandidates_(
    candidates, ctx.office, ctx.officeIdx, ctx.messageDateMs, ctx.proposalIdx, ctx.interviewIdx
  );

  let row = narrow(lstepByKey[baseKey]);
  if (row) return { row: row, method: '本名' };

  const lineKey = extractLineNameCandidate_(applicantRaw);
  if (lineKey && lineKey !== baseKey) {
    row = narrow(lstepByKey[lineKey]);
    if (row) return { row: row, method: 'LINE名' };
  }
  return { row: null, method: null };
}

/**
 * ぽけてる予約一覧CSVを解析し、ステータスが「完了」の案件を抽出してマップを返す
 * @param {string} base64Data
 * @return {Object} 完了案件の顧客名正規化キー => 予約データのマップ
 */
function parsePoketeruCompletedCsv_(base64Data) {
  const bytes = Utilities.base64Decode(base64Data);
  const blob = Utilities.newBlob(bytes);
  // ぽけてるのCSVエクスポートはUTF-8(BOM付き)。LステップCSV(Windows-31J)とは異なるので注意
  const csvText = blob.getDataAsString('UTF-8');
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
        completedMap[key] = { row: row, name: customerName };
      }
    }
  }
  return completedMap;
}

/**
 * ぽけてる完了案件のうち、Lステップ側で「提案予約日」「担当者」が
 * どちらも未入力（空欄）の案件名の一覧を返す
 * @param {Object} poketeruCompletedMap normalizeName_キー => {row, name}
 * @param {Object} lstepByKey normalizeName_キー => Lステップ行の配列（同じキーに複数該当する場合あり）
 * @param {number[]} requiredIdx REQUIRED_LABELSに対応する列インデックス
 * @return {string[]} 該当する依頼者名（ぽけてるCSV上の表記）の一覧
 */
function findPoketeruCompletedPending_(poketeruCompletedMap, lstepByKey, requiredIdx) {
  const proposalIdx = requiredIdx[REQUIRED_LABELS.indexOf('提案予約日')];
  const assigneeIdx = requiredIdx[REQUIRED_LABELS.indexOf('担当者')];

  const pending = [];
  Object.keys(poketeruCompletedMap).forEach((key) => {
    // 事務所名・日付での絞り込みはここでは行わず、一意に決まる場合のみ判定に使う
    const candidates = lstepByKey[key];
    const lstepRow = candidates && candidates.length === 1 ? candidates[0] : null;
    const proposalBlank = !lstepRow || !lstepRow[proposalIdx] || !String(lstepRow[proposalIdx]).trim();
    const assigneeBlank = !lstepRow || !lstepRow[assigneeIdx] || !String(lstepRow[assigneeIdx]).trim();
    if (proposalBlank && assigneeBlank) {
      pending.push(poketeruCompletedMap[key].name);
    }
  });
  return pending;
}

/**
 * Lステップ友だち詳細CSVとぽけてる予約一覧CSV（完了案件）の両方を受け取り、
 * スプレッドシートをマッピング・更新する統合処理関数
 * @param {string} lstepBase64 Lステップ友達詳細CSVのBase64
 * @param {string} poketeruBase64 ぽけてる予約一覧CSVのBase64 (省略可・null可)
 * @param {string} targetSheetChoice シート名、または '__ALL__'
 * @return {Object} { sheets: [...], pending: {count, names}|null } 形式の処理結果
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

  // キー => Lステップ行の配列（同一人物が複数の名前列で一致した場合はID重複除去、
  // 別人が同じニックネーム等でキーが衝突した場合はそのまま複数件残す＝後段の絞り込みに使う）
  const lstepByKey = {};
  const idIdx = 0; // 先頭列がID
  for (let i = 2; i < lstepRows.length; i++) {
    const row = lstepRows[i];
    nameIdxs.forEach((idx) => {
      const key = normalizeName_(row[idx]);
      if (!key) return;
      const list = lstepByKey[key] || (lstepByKey[key] = []);
      if (!list.some((r) => r[idIdx] === row[idIdx])) list.push(row);
    });
  }
  const officeIdx = requiredIdx[REQUIRED_LABELS.indexOf('事務所名')];
  const proposalDateIdx = requiredIdx[REQUIRED_LABELS.indexOf('提案予約日')];
  const interviewDateIdx = requiredIdx[REQUIRED_LABELS.indexOf('面談実施日')];

  // 2. ぽけてる予約一覧CSVのパース（指定されている場合）
  let poketeruCompletedMap = null;
  let poketeruPending = [];
  if (poketeruBase64 && poketeruBase64.trim() !== '') {
    poketeruCompletedMap = parsePoketeruCompletedCsv_(poketeruBase64);
    poketeruPending = findPoketeruCompletedPending_(poketeruCompletedMap, lstepByKey, requiredIdx);
  }

  const targets = targetSheetChoice === '__ALL__'
    ? getDateSheetNames_()
    : [targetSheetChoice];

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetResults = [];

  targets.forEach((sheetName) => {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      sheetResults.push({ name: sheetName, error: 'シートが見つかりません' });
      return;
    }
    const lastRow = sheet.getLastRow();
    if (lastRow < 2) {
      sheetResults.push({ name: sheetName, error: '対象データなし' });
      return;
    }

    // B:日付, C:送信者, D:内容, E:面談対応(先生), F:対応者(CS), G:依頼者名 をまとめて取得
    const rowsData = sheet.getRange(2, 2, lastRow - 1, 6).getValues();
    const results = [];
    let matched = 0;
    let complete = 0;
    let notFound = 0;
    let poketeruMatchedCount = 0;

    rowsData.forEach((r) => {
      const messageDateStr = r[0]; // B列
      const teacherField = r[3]; // E列
      const name = r[5]; // G列
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

      const resolved = resolveLstepRow_(lstepByKey, name, {
        office: extractOffice_(teacherField),
        officeIdx: officeIdx,
        messageDateMs: parseYmd_(messageDateStr),
        proposalIdx: proposalDateIdx,
        interviewIdx: interviewDateIdx,
      });
      const row = resolved.row;
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
      // 本名の直接一致以外（LINE名フォールバック等）で決まった場合は、目視確認できるよう明記する
      const methodSuffix = resolved.method === 'LINE名' ? '［LINE名突合］' : '';
      if (missing.length === 0) {
        results.push([`済${methodSuffix}`]);
        complete++;
      } else {
        results.push([`未：${missing.join('、')}${methodSuffix}`]);
      }
    });

    sheet.getRange(2, 8, results.length, 1).setValues(results); // H列=友達情報

    sheetResults.push({
      name: sheetName,
      error: null,
      matched: matched,
      complete: complete,
      notFound: notFound,
      poketeruMatched: poketeruCompletedMap ? poketeruMatchedCount : null,
    });
  });

  const result = { sheets: sheetResults, pending: null };
  if (poketeruCompletedMap) {
    result.pending = { count: poketeruPending.length, names: poketeruPending };
  }
  return result;
}

/**
 * 既存互換用の関数（LステップCSV単体処理）
 */
function processFriendCsv(base64Data, targetSheetChoice) {
  return processDualCsv(base64Data, null, targetSheetChoice);
}
