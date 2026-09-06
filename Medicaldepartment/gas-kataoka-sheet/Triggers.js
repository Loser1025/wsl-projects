/**
 * runAll()（4シート全部の更新）を1時間ごとに実行するトリガーの設定・解除。
 */
function setupHourlyTrigger() {
  deleteTrigger_('runAll');
  ScriptApp.newTrigger('runAll')
    .timeBased()
    .everyHours(1)
    .create();
  SpreadsheetApp.getUi().alert('1時間ごとの自動更新（全4シート）を設定しました。');
}

function removeHourlyTrigger() {
  deleteTrigger_('runAll');
  SpreadsheetApp.getUi().alert('自動更新を停止しました。');
}

function deleteTrigger_(functionName) {
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === functionName; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });
}
