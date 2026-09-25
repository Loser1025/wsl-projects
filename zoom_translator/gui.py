import json
import logging
import threading
from typing import Callable, Optional

from config import Config, default_config

# ロガーの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# pywebviewが利用可能かどうかを安全にインポート・確認
try:
    import webview
    PYWEBVIEW_AVAILABLE = True
except ImportError:
    PYWEBVIEW_AVAILABLE = False
    logger.warning("pywebview is not installed. SubtitleWindow will be non-functional.")


class SubtitleWindow:
    """pywebviewを使用した画面下部中央固定のロワーサード型字幕表示ウィンドウクラス"""

    def __init__(self, config: Config = default_config):
        self.config = config
        self.window = None

        if not PYWEBVIEW_AVAILABLE:
            logger.error("pywebview is not available. Cannot create SubtitleWindow.")
            return

        # HTML / CSS / JS のロワーサード型字幕デザイン
        # 黒系半透明背景、角丸、上段に小さめグレーの英語原文、下段に大きく太字の白文字で日本語訳文
        # テキスト更新時にふわっとフェードインするCSSトランジション付き
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {
                    margin: 0;
                    padding: 0;
                    background-color: transparent;
                    overflow: hidden;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                    user-select: none;
                }
                .container {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    width: 100vw;
                    height: 100vh;
                    box-sizing: border-box;
                    padding: 10px;
                }
                .lower-third {
                    background: rgba(20, 20, 20, 0.75);
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                    border-radius: 12px;
                    padding: 14px 24px;
                    text-align: center;
                    max-width: 95%;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    transition: all 0.3s ease-in-out;
                }
                .original {
                    font-size: 14px;
                    color: #aaaaaa;
                    margin-bottom: 6px;
                    line-height: 1.3;
                    word-break: break-word;
                    opacity: 0;
                    transform: translateY(4px);
                    transition: opacity 0.4s ease, transform 0.4s ease;
                }
                .translated {
                    font-size: 22px;
                    font-weight: 700;
                    color: #ffffff;
                    line-height: 1.4;
                    word-break: break-word;
                    opacity: 0;
                    transform: translateY(4px);
                    transition: opacity 0.4s ease, transform 0.4s ease;
                }
                .fade-in {
                    opacity: 1 !important;
                    transform: translateY(0) !important;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="lower-third">
                    <div id="original-text" class="original">Waiting for speech...</div>
                    <div id="translated-text" class="translated">音声待ち...</div>
                </div>
            </div>

            <script>
                function updateSubtitle(original, translated) {
                    const origEl = document.getElementById('original-text');
                    const transEl = document.getElementById('translated-text');

                    // フェードアウト効果のため一度クラスを外す
                    origEl.classList.remove('fade-in');
                    transEl.classList.remove('fade-in');

                    // 少し遅延させてからテキスト更新＆フェードインクラス付与
                    setTimeout(() => {
                        origEl.innerText = original || "";
                        transEl.innerText = translated || "";
                        
                        origEl.classList.add('fade-in');
                        transEl.classList.add('fade-in');
                    }, 50);
                }
            </script>
        </body>
        </html>
        """

        # 画面サイズおよび座標の計算
        # デフォルトの画面サイズを1920x1080と仮定しつつ、webview.screensから取得を試みる
        screen_width = 1920
        screen_height = 1080
        try:
            if hasattr(webview, "screens") and webview.screens:
                screen_width = webview.screens[0].width
                screen_height = webview.screens[0].height
                logger.info(f"Detected screen resolution: {screen_width}x{screen_height}")
        except Exception as e:
            logger.warning(f"Failed to get screen resolution via webview.screens: {e}. Falling back to 1920x1080.")

        window_width = self.config.GUI_WINDOW_WIDTH
        window_height = self.config.GUI_WINDOW_HEIGHT
        bottom_margin = self.config.GUI_BOTTOM_MARGIN

        # 画面中央になるx座標、画面下端からbottom_marginピクセル分の余白を空けたy座標
        x_coord = (screen_width - window_width) // 2
        y_coord = screen_height - window_height - bottom_margin

        # ウィンドウの作成 (frameless=True, easy_drag=True, on_top=True)
        try:
            self.window = webview.create_window(
                title="Zoom Translator",
                html=html_content,
                width=window_width,
                height=window_height,
                frameless=True,
                easy_drag=True,
                on_top=True,
                x=x_coord,
                y=y_coord,
            )
            logger.info("SubtitleWindow created successfully.")
        except Exception as e:
            logger.error(f"Failed to create pywebview window: {e}")
            self.window = None

    def update_subtitle(self, original: str, translated: str) -> None:
        """字幕の原文と訳文を更新する。JavaScriptのupdateSubtitle関数を呼び出す。"""
        if not PYWEBVIEW_AVAILABLE or not self.window:
            return

        try:
            # json.dumpsで適切にエスケープしてXSSや構文崩れを防ぐ
            orig_json = json.dumps(original if original else "")
            trans_json = json.dumps(translated if translated else "")
            js_code = f"updateSubtitle({orig_json}, {trans_json});"
            self.window.evaluate_js(js_code)
        except Exception as e:
            # 呼び出し元をクラッシュさせないよう例外を握りつぶしてログ出力に留める
            logger.debug(f"Failed to evaluate JS for subtitle update: {e}")

    def run(self, on_ready: Optional[Callable[[], None]] = None) -> None:
        """ウィンドウのイベントループを開始する。on_readyが指定されていれば別スレッドで実行する。"""
        if not PYWEBVIEW_AVAILABLE:
            logger.error("pywebview is not available. Cannot run SubtitleWindow.")
            return

        if on_ready:
            def _run_with_ready():
                # ウィンドウ表示後に別スレッドでon_readyを実行するpywebview標準パターン
                # webview.startはブロッキングなので、別スレッドから少し遅延して呼ぶ
                import time
                time.sleep(0.5)
                try:
                    on_ready()
                except Exception as e:
                    logger.error(f"Error in on_ready callback: {e}")

            threading.Thread(target=_run_with_ready, daemon=True).start()

        try:
            webview.start()
        except Exception as e:
            logger.error(f"Error starting webview loop: {e}")

    def set_on_close(self, callback: Callable[[], None]) -> None:
        """ウィンドウが閉じられた時のコールバックを登録する。"""
        if not PYWEBVIEW_AVAILABLE or not self.window:
            return

        try:
            # self.window.events.closed にコールバックを追加
            self.window.events.closed += callback
        except Exception as e:
            logger.warning(f"Failed to set on_close event callback: {e}")


# 単体確認用の簡易動作確認処理
if __name__ == "__main__":
    import time

    print("=== SubtitleWindow 単体テスト実行 ===")
    app = SubtitleWindow()

    def dummy_sequence():
        time.sleep(2.0)
        print("-> ダミー字幕1を表示")
        app.update_subtitle("Hello world, this is a test of pywebview lower third subtitle.", "こんにちは世界、これはpywebviewロワーサード字幕のテストです。")
        
        time.sleep(4.0)
        print("-> ダミー字幕2を表示")
        app.update_subtitle("Real-time translation makes international meetings much easier.", "リアルタイム翻訳により国際会議がはるかに簡単になります。")

        time.sleep(5.0)
        print("-> ダミー字幕3を表示")
        app.update_subtitle("Enjoy your seamless communication experience!", "シームレスなコミュニケーション体験をお楽しみください！")

    app.run(on_ready=dummy_sequence)
