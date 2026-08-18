/**
 * UNLOCK 1期生｜ワークシート提出管理タブ ビルダー＆自動同期（運営9＋受講生34＝43名）
 * 設置先：【公式】アンキャリ-ポータルシート（FF/FB）
 *   https://docs.google.com/spreadsheets/d/1p7v9OtJFiSu5ROZMmdGKFa_8VgP0CulLIt4-wo3H6iI/edit
 *
 * 使い方：
 *   1) スプレッドシート上のメニュー「⚙ワークシート進捗更新」 ➔ 「スタート🚀」 を実行
 *   → 各個人のシートを順番に開き、チェックを検知したらその都度リアルタイムに管理表へ反映します。
 */

// ====== 設定 ======
var SHEET_NAME = 'UNLOCK-WS管理';
var DAYS   = ['DAY0','DAY1','DAY2','DAY3','DAY4','DAY5','DAY6','DAY7'];
var STATUS = ['未提出','提出済','確認OK','要修正']; // プルダウン選択肢
var FOLDER_COACH   = 'https://drive.google.com/drive/folders/1aQewESVnsu_gnZHE_jScNUNJW7ZCdYrg';
var FOLDER_STUDENT = 'https://drive.google.com/drive/folders/1LfXMWL0MihpcsFu0MgZw7fSWSCxQGPYB';

// 名簿：[氏名, グループ, 事業部, ワークシートID]
var ROSTER = [
  // ---- 運営・コーチ陣（9名）----
  ['富樫敬済','運営','','1E8x3LTJN-Eun13vmTbBqYF0Q_9uiQT4d'],
  ['廣田珠輝','運営','','1c8Ex4rm_QbShxUDx4mFwinmXujjJIzt6'],
  ['村山達哉','運営','','12do-dGUck9-GYX9x4EG6YLoA9ALNuTJI'],
  ['森下愛加','運営','','1BLmYEZXYN1LL2yCEePDOp6av1sIvaX4z'],
  ['水澤七彩','運営','','1OWaO7Ev1lkmE76tSnuFXR2CQtSi373w8'],
  ['渡辺直人','運営','','1LFomZYURRC_vvjZzOimkAlvHPqOsgfoZ'],
  ['溝口習','運営','','1SLdiIKVYPAO_P6v1H6CPH6XdEEEf3O0W'],
  ['石原卓也','運営','','1PwbKD_GZTy2H25mrbr5IhsyALFZGgx0B'],
  ['鈴木貴大','運営','','19VW9AFaTBAmYiZ8QI0djAOY0E3-qDB8v'],
  // ---- 受講生（34名）----
  ['エスパニョーラコジヘルナンド','受講生','メディカル','1NM9HpZHxMul7qP-PZbKvOrGAIJj6RaF6'],
  ['伊藤美月','受講生','メディカル','1MnzX5d_7eUji7WzrgWpnmKVY8-QY-Sef'],
  ['前田澪奈','受講生','メディカル','1GWKY2z8narJEKJyMX9M2V72oZmkKBMJa'],
  ['加藤亮平','受講生','カスタマーリレーション','1fdnN0Obtzf2hX0-fEd2zYp8ncEGLt3Tt'],
  ['吉村行雲','受講生','カスタマーリレーション','1vnq2WwUVmrgedAZtm-L5v9ra_MA1-Dsd'],
  ['坂口実結花','受講生','カスタマーリレーション','1JQWyP2B5BB0DWgTYZxyGmV9Vilgcvrji'],
  ['壁屋臣','受講生','SC事業部','1ZLoJpNZGTl8M7XWBjYUXcMmMgB70cqg7'],
  ['安齋慎太郎','受講生','カスタマーリレーション','17DIVxMNFCjWZttC4wogVlgDvB4VgKXdw'],
  ['宮里楓','受講生','HRコンサルティング','1B-VZ1lDiQHVEshkCGkRX9SocgPSDaoFA'],
  ['屋良部愛美','受講生','メディカル','1sqTCSkMsSeoN9qtX9cwXVsNsugKqubOj'],
  ['山﨑陽向','受講生','カスタマーリレーション','1Igtcg7lY6mhH5B1C0vm5O8EjweC67AqL'],
  ['帆足光太郎','受講生','SC事業部','1VFnmjP8SzxilwO9Z-rlspBHQO22-CbQf'],
  ['本田顕士','受講生','カスタマーリレーション','1uhwmsvvkNm4rX4YgHwfnMzen4Wfkoxgu'],
  ['村上萌','受講生','カスタマーリレーション','1AJwkZ3yAFY3H4KmGhWJaQEk1_GnTyr0H'],
  ['松岡早紀','受講生','カスタマーリレーション','1acDjC2YoaCEIwUxSsQnD2bCOyxaUB_K2'],
  ['柴田大悟','受講生','カスタマーリレーション','1jJORv57Ld5HeRyHkgapskDYDgVqguyNm'],
  ['栗原堅太','受講生','カスタマーリレーション','1Bglc37EMjXNodkuuAAGcTFOvfbqcTPm2'],
  ['森本風子','受講生','カスタマーリレーション','1jJBf6lZITbTQfhsPvGsw7TC7JmLdP5N-'],
  ['森田喜童','受講生','SC事業部','1q1GFMdqUBUC7js6jW10FWr7bx5zu0u-R'],
  ['橋本遥菜','受講生','カスタマーリレーション','1MT_dr9e6Vsj6CtbPmz7cQkU4LUkchT89'],
  ['泉杏奈','受講生','人材開発部','1BIFTv6zhJzUsoOlfKK0U3oHLnbTEV2YE'],
  ['渡邉ひまり','受講生','メディカル','1hxbObPV0etioac0H37STLRSjHD9bmKSC'],
  ['澄川惣士','受講生','メディカル','1AypEbhhBX-D5xmkK8o7EJoSC3Dh7-uU6'],
  ['皆川雅斗','受講生','カスタマーリレーション','1JcNvRdw_uEeIJSyHwdT4T1qKz-npET8C'],
  ['石野宇宙','受講生','カスタマーリレーション','17OaqQo_6cBcn-Y-ahMk0F7znWq88GKjr'],
  ['細井翔吾','受講生','カスタマーリレーション','1RPSiVCpjlLabg1gXHYAfNqteQD57KTaN'],
  ['翁俊輔','受講生','SC事業部','11USrfYSb094Zd8v4vltU3ybZIoUSUZbr'],
  ['藤村俊枝','受講生','カスタマーリレーション','1wFU50mwHG7tlukz4Ky9T5B0y38mLOQmc'],
  ['鈴木絃晟','受講生','カスタマーリレーション','16E47mDyYWMYLAT5bonSpwoH0mu50dHeU'],
  ['鈴木貫一郎','受講生','HRコンサルティング','1aYmKOQ2ERrrPlt-Z4qtigolDtc-ru8tZ'],
  ['長谷川ひらり','受講生','カスタマーリレーション','1tKP-3qb0f1kjNcIYvEJPb3JmaFJyuS7W'],
  ['阿部藍','受講生','カスタマーリレーション','1TkY4bNVrt0HCGKFvHLs9at6_3Mm9dMvO'],
  ['齊藤孝徳','受講生','メディカル','1lLwkQZcuJ8ReMSimqR3wDwY8ywb-J553'],
  ['齊藤貴将','受講生','メディカル','1GPt0M1xvYAzQs2rplxp7vHNoi7R0SDuF']
];
// ==================

/**
 * スプレッドシートが開かれたときに自動で実行され、指定のカスタムメニューを追加します。
 */
function onOpen() {
  var ui = SpreadsheetApp.getUi();
  ui.createMenu('⚙ワークシート進捗更新')
    .addItem('スタート🚀', 'buildUnlockWsTracker')
    .addToUi();
}

/**
 * メイン処理：同期トラッカーの構築と実行
 */
function buildUnlockWsTracker() {
  console.log('====== [START] buildUnlockWsTracker 実行開始 ======');

  // ─── 二重起動を防止するロック処理 ───
  var lock = LockService.getScriptLock();
  try {
    lock.waitLock(10000);
  } catch (e) {
    console.warn('[スキップ] すでに別の処理（手動またはトリガー）が実行中のため、今回の実行はスキップしました。');
    try {
      SpreadsheetApp.getUi().alert('現在、別の同期処理が実行中です。数分後に再度お試しください。');
    } catch(uiError){}
    return;
  }
  // ──────────────────────────────────────────

  try {
    // スプレッドシートを開く
    var ss = SpreadsheetApp.openById('1TgD_I6JJd8WQW7jYHZNdp30VDk-uRV_CK3hvtNwHWSA');

    var sh = ss.getSheetByName(SHEET_NAME);
    if (!sh) {
      console.log('指定のシートが見つからないため、新規作成します。シート名: ' + SHEET_NAME);
      sh = ss.insertSheet(SHEET_NAME);
    }

    console.log('既存の管理シートから現在の手入力データを一時退避中...');
    var prev = readExisting_(sh);

    console.log('管理シートの枠組みを一度初期化します...');
    sh.clear();
    sh.clearConditionalFormatRules();

    var headerRow = 3, dataStart = headerRow + 1;
    var headers = ['No','氏名','グループ','事業部'].concat(DAYS).concat(['提出率','備考']);
    var nCols   = headers.length;
    var dayCol0 = 5;                      // DAY0 の列
    var rateCol = dayCol0 + DAYS.length;
    var noteCol = rateCol + 1;

    // タイトル等ヘッダーの設定
    sh.getRange(1,1).setValue('UNLOCK 1期生｜ワークシート提出管理（運営9＋受講生34＝43名）').setFontSize(14).setFontWeight('bold');
    sh.getRange(2,1).setValue('凡例： 未提出 ／ 提出済 ／ 確認OK（コーチ確認済）／ 要修正（差し戻し） ｜ 更新は 1人ずつリアルタイムに行われます（手入力値は保持）')
      .setFontColor('#666666').setFontSize(9);

    sh.getRange(headerRow,1,1,nCols).setValues([headers])
      .setFontWeight('bold').setFontColor('#ffffff').setBackground('#1f2a44')
      .setHorizontalAlignment('center').setVerticalAlignment('middle');

    console.log('--- メンバー個別のシートスキャン＆リアルタイム書き込みを開始します ---');
    var targetText = "上記すべてを確認し、提出します（自己宣言）";
    var sheetNameRegex = /DAY\d+/i;
    var autoUpdatedCount = 0;

    // ループ内で1人ずつ「スキャン ➔ 管理シートへ即時上書き ➔ 画面強制更新」を行う
    for (var i = 0; i < ROSTER.length; i++) {
      var name     = ROSTER[i][0];
      var grp      = ROSTER[i][1];
      var dept     = ROSTER[i][2];
      var folderId = ROSTER[i][3];
      var currentRowNum = dataStart + i;

      var rowValues = new Array(nCols).fill('');
      rowValues[0] = i + 1;
      rowValues[1] = name;
      rowValues[2] = grp;
      rowValues[3] = dept;

      for (var d = 0; d < DAYS.length; d++) {
        var k = name + '|' + DAYS[d];
        rowValues[dayCol0 - 1 + d] = (prev[k] != null && prev[k] !== '') ? prev[k] : '未提出';
      }
      rowValues[noteCol - 1] = prev[name + '|備考'] || '';

      if (!folderId) {
        console.log('   [スキップ] ' + (i+1) + '/' + ROSTER.length + ' : ' + name + ' (ワークシートID未登録)');
      } else {
        try {
          var studentTargetSs = SpreadsheetApp.openById(folderId);
          var studentSheets = studentTargetSs.getSheets();
          var localDetectLogs = [];

          studentSheets.forEach(function(sheet) {
            var rawSheetName = sheet.getName();
            if (sheetNameRegex.test(rawSheetName)) {
              var matchedDay = rawSheetName.match(sheetNameRegex)[0].toUpperCase();
              var dIdx = DAYS.indexOf(matchedDay);

              if (dIdx >= 0) {
                var values = sheet.getDataRange().getValues();
                var isSubmitted = false;
                var debugFound = false;

                for (var r = 0; r < values.length; r++) {
                  for (var c = 0; c < values[r].length; c++) {
                    var cellVal = values[r][c];
                    // DEBUG: 完全一致に失敗するケースを検知するため、部分一致（trim後）も別途調べる
                    if (!debugFound && typeof cellVal === 'string' && cellVal.trim() === targetText.trim() && cellVal !== targetText) {
                      console.log('   [DEBUG][不一致警告] ' + name + '/' + rawSheetName + ' r=' + r + ',c=' + c +
                        ' : trim()後は一致するが厳密一致(===)は失敗。実際値=' + JSON.stringify(cellVal));
                    }
                    if (cellVal === targetText) {
                      debugFound = true;
                      var leftVal  = c > 0 ? values[r][c - 1] : undefined;
                      var rightVal = c < values[r].length - 1 ? values[r][c + 1] : undefined;
                      console.log('   [DEBUG][宣言文セル検出] ' + name + '/' + rawSheetName +
                        ' r=' + r + ',c=' + c +
                        ' left=' + JSON.stringify(leftVal) + '(' + typeof leftVal + ')' +
                        ' right=' + JSON.stringify(rightVal) + '(' + typeof rightVal + ')');
                      if (c > 0) {
                        if (leftVal === true || leftVal === "TRUE" || leftVal === "true" || leftVal === "☑") {
                          isSubmitted = true;
                        }
                      }
                      break;
                    }
                  }
                  if (isSubmitted) break;
                }

                if (!debugFound) {
                  console.log('   [DEBUG][宣言文セル未検出] ' + name + '/' + rawSheetName + ' : targetTextに一致するセルがシート内に見つかりませんでした');
                }

                if (isSubmitted) {
                  var currentStatusInRow = rowValues[dayCol0 - 1 + dIdx];
                  if (currentStatusInRow === '未提出') {
                    rowValues[dayCol0 - 1 + dIdx] = '提出済';
                    autoUpdatedCount++;
                    localDetectLogs.push(matchedDay + ':提出済に更新✓');
                  } else {
                    localDetectLogs.push(matchedDay + ':変更なし(' + currentStatusInRow + ')');
                  }
                } else {
                  localDetectLogs.push(matchedDay + ':未提出');
                }
              }
            }
          });

          console.log('   [同期成功] ' + (i+1) + '/' + ROSTER.length + ' : ' + name + ' (' + localDetectLogs.join(', ') + ')');

        } catch (e) {
          console.warn('   [❌ 同期エラー] ' + (i+1) + '/' + ROSTER.length + ' : ' + name + ' のシートの読み込みに失敗。エラー: ' + e.toString());
        }
      }

      var targetRowRange = sh.getRange(currentRowNum, 1, 1, nCols);
      targetRowRange.setValues([rowValues]);

      if (folderId) {
        var rich = SpreadsheetApp.newRichTextValue()
          .setText(name).setLinkUrl('https://drive.google.com/file/d/' + folderId + '/view').build();
        sh.getRange(currentRowNum, 2).setRichTextValue(rich);
      }

      var a1 = sh.getRange(currentRowNum, dayCol0).getA1Notation();
      var b1 = sh.getRange(currentRowNum, dayCol0 + DAYS.length - 1).getA1Notation();
      sh.getRange(currentRowNum, rateCol)
        .setFormula('=IFERROR((COUNTIF(' + a1 + ': ' + b1 + ',"提出済")+COUNTIF(' + a1 + ': ' + b1 + ',"確認OK"))/' + DAYS.length + ',0)')
        .setNumberFormat('0%');

      var rule = SpreadsheetApp.newDataValidation().requireValueInList(STATUS, true).setAllowInvalid(false).build();
      sh.getRange(currentRowNum, dayCol0, 1, DAYS.length).setDataValidation(rule);

      SpreadsheetApp.flush();
    }
    console.log('--- メンバー個別のリアルタイム書き込みがすべて完了しました ---');

    console.log('表全体の最終デザイン体裁を整えています...');
    var allDayRange = sh.getRange(dataStart, dayCol0, ROSTER.length, DAYS.length);
    sh.setConditionalFormatRules([
      mkRule_('未提出','#f4cccc','#990000',allDayRange),
      mkRule_('提出済','#fff2cc','#7f6000',allDayRange),
      mkRule_('確認OK','#d9ead3','#274e13',allDayRange),
      mkRule_('要修正','#fce5cd','#b45f06',allDayRange)
    ]);

    sh.setFrozenRows(headerRow);
    sh.setFrozenColumns(2);
    sh.setColumnWidth(1,40); sh.setColumnWidth(2,150); sh.setColumnWidth(3,64); sh.setColumnWidth(4,150);
    for (var c=dayCol0;c<dayCol0+DAYS.length;c++) sh.setColumnWidth(c,66);
    sh.setColumnWidth(rateCol,66); sh.setColumnWidth(noteCol,260);
    sh.getRange(dataStart,dayCol0,ROSTER.length,DAYS.length+1).setHorizontalAlignment('center');
    sh.getRange(dataStart,3,ROSTER.length,1).setHorizontalAlignment('center');
    sh.getRange(headerRow,1,ROSTER.length+1,nCols)
      .setBorder(true,true,true,true,true,true,'#cccccc',SpreadsheetApp.BorderStyle.SOLID);

    var fr = dataStart + ROSTER.length + 1;
    sh.getRange(fr,1).setFormula('=HYPERLINK("'+FOLDER_STUDENT+'","▶ 受講生別ワークシート フォルダ")').setFontColor('#1155cc');
    sh.getRange(fr+1,1).setFormula('=HYPERLINK("'+FOLDER_COACH+'","▶ 運営・コーチ陣ワークシート フォルダ")').setFontColor('#1155cc');

    ss.setActiveSheet(sh);
    console.log('今回の同期で「未提出」から「提出済」へ自動昇格した総数: ' + autoUpdatedCount + ' 件');
    console.log('====== [END] buildUnlockWsTracker 全工程処理完了 ======');
    try { SpreadsheetApp.getUi().alert('UNLOCK-WS管理 のリアルタイム更新がすべて完了しました！（対象: '+ROSTER.length+'名）'); } catch(e){}

  } finally {
    lock.releaseLock();
    console.log('スクリプトのロックを解除しました。');
  }
}

/**
 * 補助関数：条件付き書式のルールを作成
 */
function mkRule_(text,bg,fg,range){
  return SpreadsheetApp.newConditionalFormatRule()
    .whenTextEqualTo(text).setBackground(bg).setFontColor(fg).setRanges([range]).build();
}

/**
 * 補助関数：既存のシートから手入力データを退避
 */
function readExisting_(sh){
  var map = {};
  if (sh.getLastRow() < 4) return map;
  var v = sh.getDataRange().getValues();
  var hr = -1;
  for (var r=0;r<v.length;r++){ if (v[r][1]==='氏名'){ hr=r; break; } }
  if (hr<0) return map;
  var head = v[hr];
  for (var r=hr+1;r<v.length;r++){
    var name = v[r][1];
    if (!name) continue;
    for (var c=0;c<head.length;c++){
      if (DAYS.indexOf(head[c])>=0) map[name+'|'+head[c]] = v[r][c];
      if (head[c]==='備考')         map[name+'|備考']      = v[r][c];
    }
  }
  return map;
}
