/**
 * Google Calendar → Telegram 朝の予定通知
 *
 * セットアップ手順:
 * 1. スクリプトエディタで「プロジェクトの設定」→「スクリプト プロパティ」を開き、以下を追加:
 *      TELEGRAM_BOT_TOKEN = <BotFatherから取得したトークン>
 *      TELEGRAM_CHAT_ID   = <通知先のchat ID>
 * 2. 関数 setupTrigger を一度だけ実行(初回は権限の承認を求められます)。
 *    これで毎朝8:00頃に sendDailyAgenda が自動実行されるトリガーが作られます。
 * 3. 動作確認したい場合は sendDailyAgenda を直接実行してください。
 */

function setupTrigger() {
  // 既存の同名トリガーを削除してから、8:00台に実行する新しいトリガーを作成する
  ScriptApp.getProjectTriggers()
    .filter(function (t) { return t.getHandlerFunction() === 'sendDailyAgenda'; })
    .forEach(function (t) { ScriptApp.deleteTrigger(t); });

  ScriptApp.newTrigger('sendDailyAgenda')
    .timeBased()
    .everyDays(1)
    .atHour(8)
    .nearMinute(0)
    .create();

  Logger.log('毎朝8:00頃に実行するトリガーを作成しました。');
}

function sendDailyAgenda() {
  var message = buildAgendaMessage_(new Date());
  sendTelegramMessage_(message);
}

function buildAgendaMessage_(date) {
  var events = CalendarApp.getDefaultCalendar().getEventsForDay(date);
  var dateLabel = Utilities.formatDate(date, 'Asia/Tokyo', 'M月d日(E)');
  var lines = ['📅 ' + dateLabel + 'の予定'];

  if (events.length === 0) {
    lines.push('今日は予定なし');
  } else {
    events
      .sort(function (a, b) { return a.getStartTime() - b.getStartTime(); })
      .forEach(function (ev) {
        var timeLabel = ev.isAllDayEvent()
          ? '終日'
          : Utilities.formatDate(ev.getStartTime(), 'Asia/Tokyo', 'HH:mm') +
            '-' +
            Utilities.formatDate(ev.getEndTime(), 'Asia/Tokyo', 'HH:mm');
        lines.push('・' + timeLabel + ' ' + ev.getTitle());
      });
  }

  return lines.join('\n');
}

function sendTelegramMessage_(text) {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('TELEGRAM_BOT_TOKEN');
  var chatId = props.getProperty('TELEGRAM_CHAT_ID');

  if (!token || !chatId) {
    throw new Error(
      'スクリプト プロパティに TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID を設定してください。'
    );
  }

  var url = 'https://api.telegram.org/bot' + token + '/sendMessage';
  var response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ chat_id: chatId, text: text }),
    muteHttpExceptions: true,
  });

  var code = response.getResponseCode();
  if (code !== 200) {
    Logger.log('Telegram送信エラー(' + code + '): ' + response.getContentText());
    throw new Error('Telegram送信に失敗しました: ' + response.getContentText());
  }
}
