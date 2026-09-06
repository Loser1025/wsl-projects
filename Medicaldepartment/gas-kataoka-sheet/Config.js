/**
 * 設定値をまとめたファイル。
 * 集計対象期間やシート構成を変える場合はここを直す。
 */
var CONFIG = {
  BQ_PROJECT: 'stream-443709',

  SUMMARY_SPREADSHEET_ID: '1aFB2O37w-Dh0RmN_W2CultjS1X4Vb7LqxbKMb99UVp4',

  // 「全体」シート：契約日ベースと反響日ベースを1枚に統合したもの（スナップショットなし、常に現時点の実績）。
  // B列=項目ラベル、C〜N列=1〜12月。契約日ベースが上段(4〜11行目)、反響日ベースが下段(14〜21行目)。
  // 各ベースの末尾2行(サンキュー架電数・対応率)はサンキュー架電シートとの突合結果。
  OVERALL_SHEET_NAME: '全体',
  OVERALL_ROWS: {
    keiyakubi: {
      count: 4,              // 契約数
      amount: 5,              // 契約金額（税抜）
      kaiyakuCount: 6,         // 解約数(処理前＋解約)
      kaiyakuAmount: 7,        // 解約金額（税抜）
      kaiyakuRateAmount: 8,    // 解約率（金額ベース）
      kaiyakuRateCount: 9,     // 解約率（件数ベース）
      sankyuCount: 10,         // サンキュー架電数
      sankyuRate: 11           // サンキュー対応率
    },
    hankyoubi: {
      count: 14,
      amount: 15,
      kaiyakuCount: 16,
      kaiyakuAmount: 17,
      kaiyakuRateAmount: 18,
      kaiyakuRateCount: 19,
      sankyuCount: 20,
      sankyuRate: 21
    }
  },

  // 「3か月比較」シート：契約コホート・反響コホートの3か月以内実績を1枚に統合したもの。
  // 「全体」シートと同じ行番号レイアウト。
  THREE_MONTH_SHEET_NAME: '3か月比較',
  THREE_MONTH_ROWS: {
    keiyaku: {
      count: 4,
      amount: 5,
      kaiyakuCount: 6,
      kaiyakuAmount: 7,
      kaiyakuRateAmount: 8,
      kaiyakuRateCount: 9,
      sankyuCount: 10,        // サンキュー架電数(全体の契約日ベースと同じ、3か月キャップなし)
      sankyuRate: 11
    },
    hankyo: {
      count: 14,
      amount: 15,
      kaiyakuCount: 16,
      kaiyakuAmount: 17,
      kaiyakuRateAmount: 18,
      kaiyakuRateCount: 19,
      sankyuCount: 20,        // サンキュー架電数(3か月以内・契約日が反響日+3か月以内のものだけ)
      sankyuRate: 21
    }
  },

  // 「商材別」シート：上位6商材＋その他を、商材ごとに契約日ベース・反響日ベースを縦に並べたもの。
  // 1商材あたり20行のブロック（契約日ベース: ヘッダー1+指標8+空白1=10行、反響日ベースも同様10行）が、
  // SHOHIN_BETSU_PRODUCT_ORDER の順番で3行目から並ぶ。指標8行目・9行目がサンキュー架電数・対応率。
  SHOHIN_BETSU_SHEET_NAME: '商材別',
  SHOHIN_BETSU_PRODUCT_ORDER: ['痩身', '泌尿器', 'AGA', 'ED', '二重', '小顔', 'その他'],
  SHOHIN_BETSU_BASE_ROW: 3,        // 1商材目（痩身）の契約日ベースのヘッダー行
  SHOHIN_BETSU_BLOCK_ROW_SPAN: 20,  // 1商材が占める行数
  SHOHIN_BETSU_HANKYOUBI_OFFSET: 10, // ブロック内で反響日ベースが始まるオフセット
  SHOHIN_BETSU_METRIC_OFFSETS: {
    count: 1,
    amount: 2,
    kaiyakuCount: 3,
    kaiyakuAmount: 4,
    kaiyakuRateAmount: 5,
    kaiyakuRateCount: 6,
    sankyuCount: 7,
    sankyuRate: 8
  },
  // 「その他」商材の内訳一覧（P〜R列）をクリアする際の対象範囲の行数（商材数の増減に余裕を持たせる）
  SHOHIN_BETSU_OTHER_LIST_MAX_ROWS: 30,

  // 「サンキュー架電」シート：ストリームの患者ID・契約日・商材の一覧（A:C列、1行目はヘッダー）。
  // 患者ID(A列)は issued_urls.patient_id 経由で client_id に変換して契約と突合する。
  SANKYU_SHEET_NAME: 'サンキュー架電',

  // 集計は常にこの日から、実行時点(BigQueryのCURRENT_DATE)まで。
  SUMMARY_START_DATE: '2026-01-01'
};
