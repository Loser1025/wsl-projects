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

  // 集計は常にこの日から、実行日時点で最新の「15日／月末」スナップショットまで
  SUMMARY_START_DATE: '2026-01-01',

  // 「全体_契約日ベース」「全体_反響日ベース」は同じレイアウトで、
  // ラベル行＋6指標行＋空白行の8行を1ブロックとして「◯月15日」「◯月末」が繰り返される。
  // 先頭ブロック（8月末）のラベル行が何行目かと、ブロックのスパン行数だけ設定すればよい。
  BLOCK_BASE_ROW: 4,   // 「8月末」ラベル行
  BLOCK_ROW_SPAN: 8,   // 1ブロックの行数

  // シート上に用意されているスナップショット日（このシートのテンプレートに合わせて記載）。
  // 実行日がこのどれかを過ぎていれば、直近で過ぎた日付のブロックに書き込む。
  SNAPSHOT_DATES: [
    { label: '8月末', year: 2026, month: 8, day: 31 },
    { label: '9月15日', year: 2026, month: 9, day: 15 },
    { label: '9月末', year: 2026, month: 9, day: 30 },
    { label: '10月15日', year: 2026, month: 10, day: 15 },
    { label: '10月末', year: 2026, month: 10, day: 31 },
    { label: '11月15日', year: 2026, month: 11, day: 15 },
    { label: '11月末', year: 2026, month: 11, day: 30 },
    { label: '12月15日', year: 2026, month: 12, day: 15 },
    { label: '12月末', year: 2026, month: 12, day: 31 }
  ]
};
