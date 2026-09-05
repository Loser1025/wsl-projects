/**
 * 手動実行、またはトリガー登録して使う入口。
 * スタンドアロンのスクリプトなので onOpen メニューは効かない
 * （実行するにはこのプロジェクトのエディタから関数を選んで実行、
 *   または時間主導型トリガーを設定する）。
 */
function runAll() {
  syncKeiyakubiBaseSummary();
  syncHankyoubiBaseSummary();
}
