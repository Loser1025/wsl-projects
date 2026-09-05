/**
 * 設定値をまとめたファイル。
 * 集計対象期間やシート構成を変える場合はここを直す。
 */
var CONFIG = {
  BQ_PROJECT: 'stream-443709',

  // 月次集計シート（契約日ベース／反響日ベース）
  SUMMARY_SPREADSHEET_ID: '1aFB2O37w-Dh0RmN_W2CultjS1X4Vb7LqxbKMb99UVp4',
  KEIYAKUBI_SHEET_NAME: '全体_契約日ベース',
  HANKYOUBI_SHEET_NAME: '全体_反響日ベース',

  // 集計対象期間（「8月末」ブロック＝1〜8月分）。
  // 別のブロック（9月末など）を埋めるときはここと BLOCK_ROWS を変更する。
  SUMMARY_START_DATE: '2026-01-01',
  SUMMARY_END_DATE: '2026-08-31',

  // 「全体_契約日ベース」「全体_反響日ベース」は同じレイアウトで、
  // ラベル行＋6指標行＋空白行の8行が1ブロック（8月末＝4〜11行目、9月15日＝12〜19行目…）で繰り返される。
  // 今回対象にしているのは先頭の「8月末」ブロック。
  BLOCK_ROWS: {
    contractCount: 5,   // 契約数
    contractAmount: 6,  // 契約金額（税抜）
    kaiyakuCount: 7,    // 解約数(処理前＋解約)
    kaiyakuAmount: 8    // 解約金額（税抜）
  }
};
