/**
 * リマインド機能の「起こし役」専用GAS。
 * 業務ロジック(メール/LINE送信・シート更新)は一切持たず、
 * Vercel側の /api/cron/remind を1分おきに叩くだけ。
 *
 * セットアップ手順:
 * 1. 共有スプレッドシートを開き、拡張機能 > Apps Script
 * 2. このファイルの中身を貼り付けて保存
 * 3. 左メニュー「プロジェクトの設定」の「スクリプト プロパティ」に
 *    CRON_SECRET = 2e5aeddef18c9d0ef6849b18ab3a6b5eff630ff11ceb36ce を追加
 *    (Vercel側の環境変数 CRON_SECRET と同じ値。.env.local に設定済み)
 * 4. エディタ上部の関数選択で setupTrigger を選び、一度だけ手動実行
 *    (実行時にGoogleアカウントの権限承認ダイアログが出るので許可する)
 * 5. 左メニュー「トリガー」で、pingReminderCron が1分ごとに登録されていることを確認
 */

const REMINDER_ENDPOINT = "https://slim-clinic-console.vercel.app/api/cron/remind";

function pingReminderCron() {
  const secret = PropertiesService.getScriptProperties().getProperty("CRON_SECRET");
  if (!secret) {
    console.error("CRON_SECRET is not set in Script Properties");
    return;
  }

  const res = UrlFetchApp.fetch(REMINDER_ENDPOINT, {
    method: "get",
    headers: { Authorization: "Bearer " + secret },
    muteHttpExceptions: true,
  });

  // 送信0件の空振りが大半なので、200以外の異常時だけログに残す
  if (res.getResponseCode() !== 200) {
    console.error("reminder cron failed: " + res.getResponseCode() + " " + res.getContentText());
  }
}

// 初回に一度だけ手動実行してトリガーを登録するための関数
function setupTrigger() {
  // 既存の同名トリガーが重複登録されないよう先に削除
  ScriptApp.getProjectTriggers()
    .filter((t) => t.getHandlerFunction() === "pingReminderCron")
    .forEach((t) => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger("pingReminderCron")
    .timeBased()
    .everyMinutes(1)
    .create();
}
