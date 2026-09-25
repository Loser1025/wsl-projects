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


class _SettingsAPI:
    """pywebviewのjs_api用ブリッジクラス。JavaScriptからPythonの保存処理を呼び出すためのもの。"""

    def __init__(self, save_settings_fn: Optional[Callable[[str, str, str], None]] = None):
        self.save_settings_fn = save_settings_fn

    def save_settings(self, source_lang: str, target_lang: str, device_name: str) -> None:
        """設定保存コールバックを安全に呼び出す。"""
        logger.info(f"[_SettingsAPI] save_settings called with source={source_lang}, target={target_lang}, device={device_name}")
        if self.save_settings_fn:
            try:
                self.save_settings_fn(source_lang, target_lang, device_name)
            except Exception as e:
                logger.error(f"Error in save_settings_fn: {e}")


class SubtitleWindow:
    """pywebviewを使用した画面下部中央固定のロワーサード型字幕表示ウィンドウクラス"""

    def __init__(
        self,
        config: Config = default_config,
        get_devices_fn: Optional[Callable[[], list]] = None,
        save_settings_fn: Optional[Callable[[str, str, str], None]] = None,
    ):
        self.config = config
        self.window = None
        self.save_settings_fn = save_settings_fn

        if not PYWEBVIEW_AVAILABLE:
            logger.error("pywebview is not available. Cannot create SubtitleWindow.")
            return

        # デバイス一覧の取得（get_devices_fnがNoneの場合は空リスト）
        devices = []
        if get_devices_fn is not None:
            try:
                devices = get_devices_fn()
                if not isinstance(devices, list):
                    devices = list(devices)
            except Exception as e:
                logger.error(f"Failed to get devices via get_devices_fn: {e}")
                devices = []

        devices_json = json.dumps(devices)
        current_source = getattr(self.config, "SOURCE_LANG", "en")
        current_target = getattr(self.config, "TARGET_LANG", "ja")
        current_device = getattr(self.config, "SPEAKER_DEVICE_NAME", "")

        # HTML / CSS / JS のロワーサード型字幕デザインおよび設定パネルオーバーレイ
        # 字幕バー右上の歯車アイコン「⚙」をクリックすると字幕コンテナを隠し、設定パネルを表示する
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
                    position: relative;
                    background: rgba(20, 20, 20, 0.75);
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                    border-radius: 12px;
                    padding: 14px 24px;
                    text-align: center;
                    max-width: 95%;
                    width: 600px;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    transition: all 0.3s ease-in-out;
                }
                .settings-btn {
                    position: absolute;
                    top: 8px;
                    right: 12px;
                    background: transparent;
                    border: none;
                    color: #aaaaaa;
                    font-size: 16px;
                    cursor: pointer;
                    padding: 2px 6px;
                    border-radius: 4px;
                    transition: color 0.2s, background 0.2s;
                }
                .settings-btn:hover {
                    color: #ffffff;
                    background: rgba(255, 255, 255, 0.1);
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
                /* 設定パネルオーバーレイ */
                .settings-panel {
                    display: none;
                    text-align: left;
                    color: #ffffff;
                    padding: 4px 8px;
                }
                .settings-panel h3 {
                    margin: 0 0 12px 0;
                    font-size: 16px;
                    font-weight: 600;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.2);
                    padding-bottom: 6px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                .close-btn {
                    background: transparent;
                    border: none;
                    color: #aaaaaa;
                    font-size: 18px;
                    cursor: pointer;
                    padding: 0 4px;
                }
                .close-btn:hover {
                    color: #ffffff;
                }
                .form-group {
                    margin-bottom: 10px;
                }
                .form-group label {
                    display: block;
                    font-size: 12px;
                    color: #cccccc;
                    margin-bottom: 4px;
                }
                .form-group select {
                    width: 100%;
                    padding: 6px 8px;
                    background: rgba(40, 40, 40, 0.9);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 6px;
                    color: #ffffff;
                    font-size: 13px;
                    box-sizing: border-box;
                }
                .form-actions {
                    display: flex;
                    justify-content: flex-end;
                    gap: 8px;
                    margin-top: 14px;
                }
                .btn {
                    padding: 6px 14px;
                    border-radius: 6px;
                    font-size: 13px;
                    font-weight: 600;
                    cursor: pointer;
                    border: none;
                }
                .btn-save {
                    background: #3b82f6;
                    color: #ffffff;
                }
                .btn-save:hover {
                    background: #2563eb;
                }
                .btn-cancel {
                    background: rgba(255, 255, 255, 0.1);
                    color: #cccccc;
                }
                .btn-cancel:hover {
                    background: rgba(255, 255, 255, 0.2);
                    color: #ffffff;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="lower-third">
                    <button class="settings-btn" id="gear-btn" title="Settings">⚙</button>
                    
                    <!-- 字幕表示ビュー -->
                    <div id="subtitle-view">
                        <div id="original-text" class="original">Waiting for speech...</div>
                        <div id="translated-text" class="translated">音声入力を待機中...</div>
                    </div>

                    <!-- 設定パネルオーバーレイ -->
                    <div id="settings-view" class="settings-panel">
                        <h3>
                            <span>設定 (Settings)</span>
                            <button class="close-btn" id="panel-close-btn">&times;</button>
                        </h3>
                        <div class="form-group">
                            <label for="source-lang-select">原文言語 (Source Language)</label>
                            <select id="source-lang-select">
                                <option value="en">English (en)</option>
                                <option value="ja">日本語 (ja)</option>
                                <option value="ko">한국어 (ko)</option>
                                <option value="zh">中文 (zh)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="target-lang-select">訳文言語 (Target Language)</label>
                            <select id="target-lang-select">
                                <option value="en">English (en)</option>
                                <option value="ja">日本語 (ja)</option>
                                <option value="ko">한국어 (ko)</option>
                                <option value="zh">中文 (zh)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="device-select">録音デバイス (Audio Device)</label>
                            <select id="device-select">
                                <option value="">自動 (Default Loopback)</option>
                            </select>
                        </div>
                        <div class="form-actions">
                            <button class="btn btn-cancel" id="cancel-btn">キャンセル</button>
                            <button class="btn btn-save" id="save-btn">保存</button>
                        </div>
                    </div>
                </div>
            </div>

            <script>
                // デバイス一覧をJavaScriptに埋め込み
                const availableDevices = __DEVICES_JSON__;
                const currentSource = __CURRENT_SOURCE__;
                const currentTarget = __CURRENT_TARGET__;
                const currentDevice = __CURRENT_DEVICE__;

                // 初期選択の反映
                document.addEventListener('DOMContentLoaded', () => {
                    const srcSel = document.getElementById('source-lang-select');
                    const tgtSel = document.getElementById('target-lang-select');
                    const devSel = document.getElementById('device-select');

                    if (srcSel) srcSel.value = currentSource;
                    if (tgtSel) tgtSel.value = currentTarget;

                    // デバイス選択肢の構築
                    availableDevices.forEach(dev => {
                        const opt = document.createElement('option');
                        opt.value = dev;
                        opt.textContent = dev;
                        if (dev === currentDevice) {
                            opt.selected = true;
                        }
                        devSel.appendChild(opt);
                    });

                    // 歯車ボタンクリックで設定パネルを表示
                    document.getElementById('gear-btn').addEventListener('click', () => {
                        document.getElementById('subtitle-view').style.display = 'none';
                        document.getElementById('settings-view').style.display = 'block';
                    });

                    // 閉じる・キャンセルボタンで字幕表示に戻す
                    const closePanel = () => {
                        document.getElementById('settings-view').style.display = 'none';
                        document.getElementById('subtitle-view').style.display = 'block';
                    };

                    document.getElementById('panel-close-btn').addEventListener('click', closePanel);
                    document.getElementById('cancel-btn').addEventListener('click', closePanel);

                    // 保存ボタンクリック
                    document.getElementById('save-btn').addEventListener('click', async () => {
                        const sourceLang = srcSel.value;
                        const targetLang = tgtSel.value;
                        const deviceName = devSel.value;

                        try {
                            if (window.pywebview && window.pywebview.api) {
                                await window.pywebview.api.save_settings(sourceLang, targetLang, deviceName);
                            } else {
                                console.log('pywebview.api not available, simulated save:', sourceLang, targetLang, deviceName);
                            }
                        } catch (e) {
                            console.error('Failed to save settings:', e);
                        }

                        closePanel();
                    });
                });

                function updateSubtitle(original, translated) {
                    const origEl = document.getElementById('original-text');
                    const transEl = document.getElementById('translated-text');

                    // 一旦フェードアウト
                    origEl.classList.remove('fade-in');
                    transEl.classList.remove('fade-in');

                    setTimeout(() => {
                        origEl.textContent = original;
                        transEl.textContent = translated;

                        // フェードイン
                        origEl.classList.add('fade-in');
                        transEl.classList.add('fade-in');
                    }, 50);
                }
            </script>
        </body>
        </html>
        """

        # プレースホルダーを置換
        html_content = (
            html_content.replace("__DEVICES_JSON__", devices_json)
            .replace("__CURRENT_SOURCE__", json.dumps(current_source))
            .replace("__CURRENT_TARGET__", json.dumps(current_target))
            .replace("__CURRENT_DEVICE__", json.dumps(current_device))
        )

        # スクリーン解像度やウィンドウサイズの計算
        screen_width = 1920
        screen_height = 1080
        window_width = self.config.GUI_WINDOW_WIDTH
        window_height = self.config.GUI_WINDOW_HEIGHT
        bottom_margin = self.config.GUI_BOTTOM_MARGIN

        if PYWEBVIEW_AVAILABLE and hasattr(webview, 'screens') and webview.screens:
            try:
                screen = webview.screens[0]
                screen_width = screen.width
                screen_height = screen.height
            except Exception as e:
                logger.debug(f"Could not get screen dimensions via webview.screens: {e}")

        x_coord = (screen_width - window_width) // 2
        y_coord = screen_height - window_height - bottom_margin

        # js_apiインスタンスの生成
        settings_api = _SettingsAPI(save_settings_fn=self.save_settings_fn)

        # ウィンドウの作成 (frameless=True, easy_drag=True, on_top=True, js_api=settings_api)
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
                js_api=settings_api,
            )
            logger.info("SubtitleWindow created successfully with settings API.")
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
            self.window.events.closed += callback
        except Exception as e:
            logger.warning(f"Failed to set on_close event callback: {e}")


# 単体確認用の簡易動作確認処理
if __name__ == "__main__":
    import time

    print("=== SubtitleWindow 単体テスト実行 ===")

    def dummy_get_devices():
        return ["Speakers (Realtek High Definition Audio)", "Virtual Audio Cable", "Zoom Audio Device"]

    def dummy_save_settings(source_lang: str, target_lang: str, device_name: str):
        print(f"[テスト保存コールバック成功] source={source_lang}, target={target_lang}, device={device_name}")

    app = SubtitleWindow(
        config=default_config,
        get_devices_fn=dummy_get_devices,
        save_settings_fn=dummy_save_settings,
    )

    def dummy_sequence():
        time.sleep(2.0)
        print("-> ダミー字幕1を表示")
        app.update_subtitle(
            "Hello world, this is a test of pywebview lower third subtitle.",
            "こんにちは世界、これはpywebviewロワーサード字幕のテストです。",
        )

        time.sleep(4.0)
        print("-> ダミー字幕2を表示")
        app.update_subtitle(
            "Real-time translation makes international meetings much easier.",
            "リアルタイム翻訳により国際会議がはるかに簡単になります。",
        )

        time.sleep(5.0)
        print("-> ダミー字幕3を表示")
        app.update_subtitle("Enjoy your seamless communication experience!", "シームレスなコミュニケーション体験をお楽しみください！")

    app.run(on_ready=dummy_sequence)
