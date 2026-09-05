/**
 * 「今、集計対象にすべきブロック」を判定する。
 * まだ到達していない直近のスナップショット日（15日／月末）をターゲットとし、
 * 集計終了日は「今日」と「そのスナップショット日」の早い方（＝基本は今日）にする。
 * これにより、チェックポイント当日が来る前でも常に最新日まで反映され、
 * チェックポイント当日を過ぎたら値が確定し、次のブロックに自動で切り替わる。
 * 例：実行日が9/6なら「9月15日」ブロックに、今日(9/6)までの実績を書き込む。
 */
function getCurrentSnapshotBlock_() {
  var today = new Date();
  var dates = CONFIG.SNAPSHOT_DATES;

  var targetIndex = dates.length - 1; // 全部通過済みなら最後のブロックに書く
  for (var i = 0; i < dates.length; i++) {
    var snapDate = new Date(dates[i].year, dates[i].month - 1, dates[i].day);
    if (today <= snapDate) {
      targetIndex = i;
      break;
    }
  }

  var snap = dates[targetIndex];
  var snapDate = new Date(snap.year, snap.month - 1, snap.day);
  var endDate = today < snapDate ? today : snapDate;

  var baseRow = CONFIG.BLOCK_BASE_ROW + targetIndex * CONFIG.BLOCK_ROW_SPAN;

  return {
    label: snap.label,
    endDate: Utilities.formatDate(endDate, 'Asia/Tokyo', 'yyyy-MM-dd'),
    rows: {
      contractCount: baseRow + 1,  // 契約数
      contractAmount: baseRow + 2, // 契約金額（税抜）
      kaiyakuCount: baseRow + 3,   // 解約数(処理前＋解約)
      kaiyakuAmount: baseRow + 4   // 解約金額（税抜）
    }
  };
}
