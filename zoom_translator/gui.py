import json
import logging
import threading
from typing import Callable, Optional

from config import Config, default_config

# ロガーの設定(ルートロガーの設定はエントリーポイントのmain.pyが行うため、ここではbasicConfigを呼ばない。
# 呼んでしまうとmain.py側の後続のlogging.basicConfig()呼び出しが無効化される)
logger = logging.getLogger(__name__)

# pywebviewが利用可能かどうかを安全にインポート・確認
try:
    import webview
    PYWEBVIEW_AVAILABLE = True
except ImportError:
    PYWEBVIEW_AVAILABLE = False
    logger.warning("pywebview is not installed. SubtitleWindow will be non-functional.")


class _SettingsAPI:
    """pywebviewのjs_api用ブリッジクラス。JavaScriptからPythonの保存処理・ウィンドウリサイズを呼び出すためのもの。"""

    def __init__(
        self,
        save_settings_fn: Optional[Callable[[str, str], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
        on_close_settings: Optional[Callable[[], None]] = None,
    ):
        self.save_settings_fn = save_settings_fn
        # SubtitleWindowのインスタンス(ネイティブウィンドウを内部に持つ)を直接属性として
        # 持たせると、pywebviewがjs_apiオブジェクトの属性をJS側へ公開しようとして
        # ネイティブGUIオブジェクトの循環参照を再帰的に辿り無限再帰でクラッシュする
        # (実機で確認済みの不具合)。そのため、必ず単純な関数(クロージャ)だけを保持する。
        self._on_open_settings = on_open_settings
        self._on_close_settings = on_close_settings

    def save_settings(self, speaker_device: str, mic_device: str) -> None:
        """設定保存コールバックを安全に呼び出す。"""
        logger.info(f"[_SettingsAPI] save_settings called with speaker={speaker_device}, mic={mic_device}")
        if self.save_settings_fn:
            try:
                self.save_settings_fn(speaker_device, mic_device)
            except Exception as e:
                logger.error(f"Error in save_settings_fn: {e}")

    def open_settings_panel(self) -> None:
        """
        設定パネル表示時に、通常の字幕バーでは設定項目が収まらないため、
        ウィンドウ自体を縦方向に拡大する(横幅は字幕バーと同じ幅を維持)。
        """
        if self._on_open_settings:
            try:
                self._on_open_settings()
            except Exception as e:
                logger.warning(f"Failed to resize window for settings panel: {e}")

    def close_settings_panel(self) -> None:
        """設定パネルを閉じるとき、元の字幕バーサイズ・位置に戻す。"""
        if self._on_close_settings:
            try:
                self._on_close_settings()
            except Exception as e:
                logger.warning(f"Failed to resize window back to subtitle bar: {e}")


class SubtitleWindow:
    """pywebviewを使用した画面下部中央固定のロワーサード型字幕表示ウィンドウクラス (2段構成: 上段=相手/スピーカー, 下段=あなた/マイク)"""

    def __init__(
        self,
        config: Config = default_config,
        get_speaker_devices_fn: Optional[Callable[[], list]] = None,
        get_mic_devices_fn: Optional[Callable[[], list]] = None,
        save_settings_fn: Optional[Callable[[str, str], None]] = None,
    ):
        self.config = config
        self.window = None
        self.save_settings_fn = save_settings_fn

        if not PYWEBVIEW_AVAILABLE:
            logger.error("pywebview is not available. Cannot create SubtitleWindow.")
            return

        # スピーカーデバイス一覧の取得（防御的処理: 失敗や未指定なら空リスト）
        speaker_devices = []
        if get_speaker_devices_fn is not None:
            try:
                speaker_devices = get_speaker_devices_fn()
                if not isinstance(speaker_devices, list):
                    speaker_devices = list(speaker_devices)
            except Exception as e:
                logger.error(f"Failed to get speaker devices via get_speaker_devices_fn: {e}")
                speaker_devices = []

        # マイクデバイス一覧の取得（防御的処理: 失敗や未指定なら空リスト）
        mic_devices = []
        if get_mic_devices_fn is not None:
            try:
                mic_devices = get_mic_devices_fn()
                if not isinstance(mic_devices, list):
                    mic_devices = list(mic_devices)
            except Exception as e:
                logger.error(f"Failed to get mic devices via get_mic_devices_fn: {e}")
                mic_devices = []

        speaker_devices_json = json.dumps(speaker_devices)
        mic_devices_json = json.dumps(mic_devices)
        current_speaker = getattr(self.config, "SPEAKER_DEVICE_NAME", "")
        current_mic = getattr(self.config, "MIC_DEVICE_NAME", "")

        # HTML / CSS / JS のロワーサード型字幕デザイン(上段=相手/スピーカー、下段=あなた/マイク)および設定パネルオーバーレイ
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
                    text-align: left;
                    max-width: 95%;
                    width: 1000px;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    transition: all 0.3s ease-in-out;
                }
                .settings-btn {
                    position: absolute;
                    top: 10px;
                    right: 14px;
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
                /* 2段構成のセクション共通スタイル */
                .subtitle-row {
                    margin-bottom: 10px;
                }
                .subtitle-row:last-child {
                    margin-bottom: 0;
                }
                .row-header {
                    display: flex;
                    align-items: center;
                    font-size: 13px;
                    font-weight: 600;
                    margin-bottom: 3px;
                }
                /* 相手側(スピーカー): 水色系 */
                .speaker-header {
                    color: #38bdf8;
                }
                /* あなた側(マイク): 緑系 */
                .mic-header {
                    color: #4ade80;
                }
                .divider {
                    height: 1px;
                    background: rgba(255, 255, 255, 0.12);
                    margin: 10px 0;
                }
                .original {
                    font-size: 13px;
                    color: #9ca3af;
                    margin-bottom: 4px;
                    line-height: 1.3;
                    word-break: break-word;
                    opacity: 0;
                    transform: translateY(4px);
                    transition: opacity 0.4s ease, transform 0.4s ease;
                    display: -webkit-box;
                    -webkit-line-clamp: 1;
                    -webkit-box-orient: vertical;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }
                .translated {
                    font-size: 20px;
                    font-weight: 700;
                    color: #ffffff;
                    line-height: 1.35;
                    word-break: break-word;
                    opacity: 0;
                    transform: translateY(4px);
                    transition: opacity 0.4s ease, transform 0.4s ease;
                    display: -webkit-box;
                    -webkit-line-clamp: 3;
                    -webkit-box-orient: vertical;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }
                .fade-in {
                    opacity: 1 !important;
                    transform: translateY(0) !important;
                }
                /* 設定パネルオーバーレイ */
                .settings-panel {
                    display: none;
                    padding: 4px 6px;
                }
                .settings-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 14px;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                    padding-bottom: 8px;
                }
                .settings-title {
                    font-size: 15px;
                    font-weight: 600;
                    color: #ffffff;
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
                    margin-bottom: 12px;
                }
                .form-group label {
                    display: block;
                    font-size: 12px;
                    color: #cccccc;
                    margin-bottom: 4px;
                }
                .form-group select {
                    width: 100%;
                    padding: 8px;
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
                    margin-top: 16px;
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
                    <!-- 歯車ボタン (設定を開く) -->
                    <button class="settings-btn" id="gear-btn" title="設定">&#9881; 設定</button>

                    <!-- 字幕表示ビュー (2段構成) -->
                    <div id="subtitle-view">
                        <!-- 上段: 相手 (スピーカー側) -->
                        <div class="subtitle-row">
                            <div class="row-header speaker-header">🔊 相手 (スピーカー)</div>
                            <div class="original" id="speaker-original"></div>
                            <div class="translated" id="speaker-translated"></div>
                        </div>

                        <!-- 区切り線 -->
                        <div class="divider"></div>

                        <!-- 下段: あなた (マイク側) -->
                        <div class="subtitle-row">
                            <div class="row-header mic-header">🎤 あなた (マイク)</div>
                            <div class="original" id="mic-original"></div>
                            <div class="translated" id="mic-translated"></div>
                        </div>
                    </div>

                    <!-- 設定パネルビュー -->
                    <div id="settings-view" class="settings-panel">
                        <div class="settings-header">
                            <span class="settings-title">⚙ 設定</span>
                            <button class="close-btn" id="panel-close-btn">&times;</button>
                        </div>
                        <div class="form-group">
                            <label for="speaker-device-select">スピーカー (相手の声) デバイス</label>
                            <select id="speaker-device-select">
                                <option value="">自動 (Default Loopback)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="mic-device-select">マイク (あなたの声) デバイス</label>
                            <select id="mic-device-select">
                                <option value="">自動 (Default Microphone)</option>
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
                const speakerDevices = __SPEAKER_DEVICES_JSON__;
                const micDevices = __MIC_DEVICES_JSON__;
                const currentSpeaker = __CURRENT_SPEAKER__;
                const currentMic = __CURRENT_MIC__;

                document.addEventListener('DOMContentLoaded', () => {
                    const speakerSel = document.getElementById('speaker-device-select');
                    const micSel = document.getElementById('mic-device-select');

                    // スピーカーデバイス選択肢の構築
                    if (speakerSel) {
                        speakerDevices.forEach(dev => {
                            const opt = document.createElement('option');
                            opt.value = dev;
                            opt.textContent = dev;
                            if (dev === currentSpeaker) {
                                opt.selected = true;
                            }
                            speakerSel.appendChild(opt);
                        });
                    }

                    // マイクデバイス選択肢の構築
                    if (micSel) {
                        micDevices.forEach(dev => {
                            const opt = document.createElement('option');
                            opt.value = dev;
                            opt.textContent = dev;
                            if (dev === currentMic) {
                                opt.selected = true;
                            }
                            micSel.appendChild(opt);
                        });
                    }

                    // 設定パネルを開く
                    document.getElementById('gear-btn').addEventListener('click', () => {
                        document.getElementById('subtitle-view').style.display = 'none';
                        document.getElementById('settings-view').style.display = 'block';
                        if (window.pywebview && window.pywebview.api) {
                            window.pywebview.api.open_settings_panel();
                        }
                    });

                    // 設定パネルを閉じる
                    const closePanel = () => {
                        document.getElementById('settings-view').style.display = 'none';
                        document.getElementById('subtitle-view').style.display = 'block';
                        if (window.pywebview && window.pywebview.api) {
                            window.pywebview.api.close_settings_panel();
                        }
                    };

                    document.getElementById('panel-close-btn').addEventListener('click', closePanel);
                    document.getElementById('cancel-btn').addEventListener('click', closePanel);

                    // 保存ボタン押下
                    document.getElementById('save-btn').addEventListener('click', () => {
                        const speakerVal = speakerSel ? speakerSel.value : '';
                        const micVal = micSel ? micSel.value : '';

                        if (window.pywebview && window.pywebview.api) {
                            window.pywebview.api.save_settings(speakerVal, micVal);
                        }
                        closePanel();
                    });
                });

                // 上段 (相手/スピーカー) 字幕更新用関数
                function updateSpeakerSubtitle(original, translated) {
                    const origEl = document.getElementById('speaker-original');
                    const transEl = document.getElementById('speaker-translated');

                    if (origEl) {
                        origEl.textContent = original || '';
                        if (original && original.trim() !== '') {
                            origEl.classList.add('fade-in');
                        } else {
                            origEl.classList.remove('fade-in');
                        }
                    }

                    if (transEl) {
                        transEl.textContent = translated || '';
                        if (translated && translated.trim() !== '') {
                            transEl.classList.add('fade-in');
                        } else {
                            transEl.classList.remove('fade-in');
                        }
                    }
                }

                // 下段 (あなた/マイク) 字幕更新用関数
                function updateMicSubtitle(original, translated) {
                    const origEl = document.getElementById('mic-original');
                    const transEl = document.getElementById('mic-translated');

                    if (origEl) {
                        origEl.textContent = original || '';
                        if (original && original.trim() !== '') {
                            origEl.classList.add('fade-in');
                        } else {
                            origEl.classList.remove('fade-in');
                        }
                    }

                    if (transEl) {
                        transEl.textContent = translated || '';
                        if (translated && translated.trim() !== '') {
                            transEl.classList.add('fade-in');
                        } else {
                            transEl.classList.remove('fade-in');
                        }
                    }
                }
            </script>
        </body>
        </html>
        """

        html_content = (
            html_content
            .replace("__SPEAKER_DEVICES_JSON__", speaker_devices_json)
            .replace("__MIC_DEVICES_JSON__", mic_devices_json)
            .replace("__CURRENT_SPEAKER__", json.dumps(current_speaker))
            .replace("__CURRENT_MIC__", json.dumps(current_mic))
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

        # 設定パネル表示中はウィンドウを縦方向に拡大するため、後で_SettingsAPIから
        # 参照できるようジオメトリ情報をインスタンス変数として保持しておく
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.window_width = window_width
        self.window_height = window_height
        self.bottom_margin = bottom_margin
        self.x_coord = x_coord
        self.y_coord = y_coord
        # 設定パネル(デバイス選択2つ+ボタン等)が収まる高さ。横幅は字幕バーと同じに保つ
        self.settings_panel_height = 340

        # 設定パネルの開閉時にウィンドウをリサイズ/移動するクロージャ。
        # self(SubtitleWindow)を直接js_apiの属性として持たせるとpywebviewが
        # ネイティブウィンドウを再帰的に辿ってクラッシュするため、単純な関数のみを渡す。
        def _resize_for_settings() -> None:
            if self.window is None:
                return
            y = self.screen_height - self.settings_panel_height - self.bottom_margin
            self.window.resize(self.window_width, self.settings_panel_height)
            self.window.move(self.x_coord, y)

        def _resize_for_subtitle() -> None:
            if self.window is None:
                return
            self.window.resize(self.window_width, self.window_height)
            self.window.move(self.x_coord, self.y_coord)

        # js_apiインスタンスの生成
        settings_api = _SettingsAPI(
            save_settings_fn=self.save_settings_fn,
            on_open_settings=_resize_for_settings,
            on_close_settings=_resize_for_subtitle,
        )

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
            logger.info("SubtitleWindow created successfully with settings API (2-row layout).")
        except Exception as e:
            logger.error(f"Failed to create pywebview window: {e}")
            self.window = None

    def update_speaker_subtitle(self, original: str, translated: str) -> None:
        """上段 (相手/スピーカー) の字幕原文と訳文を更新する。JavaScriptのupdateSpeakerSubtitle関数を呼び出す。"""
        if not PYWEBVIEW_AVAILABLE or not self.window:
            return

        try:
            orig_json = json.dumps(original if original else "")
            trans_json = json.dumps(translated if translated else "")
            js_code = f"updateSpeakerSubtitle({orig_json}, {trans_json});"
            self.window.evaluate_js(js_code)
        except Exception as e:
            logger.debug(f"Failed to evaluate JS for speaker subtitle update: {e}")

    def update_mic_subtitle(self, original: str, translated: str) -> None:
        """下段 (あなた/マイク) の字幕原文と訳文を更新する。JavaScriptのupdateMicSubtitle関数を呼び出す。"""
        if not PYWEBVIEW_AVAILABLE or not self.window:
            return

        try:
            orig_json = json.dumps(original if original else "")
            trans_json = json.dumps(translated if translated else "")
            js_code = f"updateMicSubtitle({orig_json}, {trans_json});"
            self.window.evaluate_js(js_code)
        except Exception as e:
            logger.debug(f"Failed to evaluate JS for mic subtitle update: {e}")

    def run(self, on_ready: Optional[Callable[[], None]] = None) -> None:
        """ウィンドウのイベントループを開始する。on_readyが指定されていれば別スレッドで実行する。"""
        if not PYWEBVIEW_AVAILABLE:
            logger.error("pywebview is not available. Cannot run SubtitleWindow.")
            return

        if on_ready:
            def _run_with_ready():
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

    print("=== SubtitleWindow 単体テスト実行 (2段構成) ===")

    def dummy_get_speaker_devices():
        return ["Speakers (Realtek Audio)", "Virtual Audio Cable"]

    def dummy_get_mic_devices():
        return ["Microphone (Realtek Audio)", "USB Microphone"]

    def dummy_save_settings(speaker_device: str, mic_device: str):
        print(f"[テスト保存コールバック成功] speaker={speaker_device}, mic={mic_device}")

    app = SubtitleWindow(
        config=default_config,
        get_speaker_devices_fn=dummy_get_speaker_devices,
        get_mic_devices_fn=dummy_get_mic_devices,
        save_settings_fn=dummy_save_settings,
    )

    def dummy_sequence():
        time.sleep(2.0)
        print("-> 上段(相手)にダミー字幕を表示")
        app.update_speaker_subtitle(
            "Hello from the speaker side!",
            "スピーカー側からのこんにちは！",
        )

        time.sleep(3.0)
        print("-> 下段(あなた)にダミー字幕を表示")
        app.update_mic_subtitle(
            "Hello from the microphone side!",
            "マイク側からのこんにちは！",
        )

        time.sleep(4.0)
        print("-> 上段・下段を同時更新テスト")
        app.update_speaker_subtitle(
            "How is the meeting going?",
            "会議の進捗はいかがですか？",
        )
        app.update_mic_subtitle(
            "Everything is going very well.",
            "すべて順調に進んでいます。",
        )

    app.run(on_ready=dummy_sequence)
