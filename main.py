"""
zoom_translator/main.py

AudioCapturer, TranslatorEngine, SubtitleWindowをqueueで結合し、
リアルタイム翻訳字幕アプリとして動作させるエントリーポイントモジュール。
"""

import queue
import threading
import logging
import traceback
import sys

from config import default_config
from audio_capturer import AudioCapturer
from translator_engine import TranslatorEngine
from gui import SubtitleWindow

# ロギングの設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ZoomTranslatorMain")


def main():
    """
    アプリケーションのエントリーポイント。
    設定読み込み、各コンポーネント（AudioCapturer, TranslatorEngine, SubtitleWindow, Queue）の初期化と接続、
    およびメインループの実行を行う。
    """
    logger.info("Zoom Translator アプリケーションを起動しています...")

    # 1. スレッド間受け渡し用の queue.Queue を用意
    result_queue = queue.Queue()

    # 2. 各コンポーネントの初期化（デフォルト設定を使用）
    config = default_config
    translator_engine = TranslatorEngine(config=config)

    # 3. AudioCapturerのon_chunkコールバックで受け取った音声チャンクを処理する関数
    def handle_audio_chunk(audio_chunk):
        """
        AudioCapturerのバックグラウンドスレッドから呼ばれるコールバック。
        音声チャンクを TranslatorEngine.transcribe_and_translate() にかけて、
        翻訳結果（または認識・翻訳テキスト）を result_queue に格納する。
        """
        try:
            # 音声認識＆翻訳の実行（例外発生時はアプリ全体が落ちないよう保護）
            transcript, translation = translator_engine.transcribe_and_translate(audio_chunk)
            
            if translation:
                logger.info(f"翻訳結果: {translation} (原文: {transcript})")
                result_queue.put(translation)
            elif transcript:
                logger.info(f"認識結果(翻訳なし): {transcript}")
                result_queue.put(transcript)
        except Exception as e:
            logger.error(f"音声処理中にエラーが発生しました: {e}")
            logger.debug(traceback.format_exc())

    # AudioCapturerのインスタンス化
    audio_capturer = AudioCapturer(config=config, on_chunk=handle_audio_chunk)

    # 4. SubtitleWindowをメインスレッドで生成
    try:
        app = SubtitleWindow(config=config)
    except Exception as e:
        logger.error(f"SubtitleWindowの初期化に失敗しました: {e}")
        traceback.print_exc()
        sys.exit(1)

    # 5. tkinterのafter()で定期的にキューをポーリングし、update_subtitle()を呼ぶ関数
    def poll_queue():
        """
        メインスレッド上で定期実行され、result_queueから最新の翻訳結果を取り出して
        SubtitleWindowの字幕を更新する。
        """
        try:
            while True:
                # キューからノンブロックで最新のテキストを取得
                text = result_queue.get_nowait()
                app.update_subtitle(text)
                result_queue.task_done()
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"キューポーリング中にエラーが発生しました: {e}")
        
        # 100ミリ秒後に再度ポーリングを実行
        app.after(100, poll_queue)

    # 6. AudioCapturerの開始
    try:
        audio_capturer.start()
        logger.info("AudioCapturer (システム音声キャプチャ) を開始しました。")
    except Exception as e:
        logger.error(f"AudioCapturerの起動に失敗しました: {e}")

    # 定期ポーリングの初回スケジュール
    app.after(100, poll_queue)

    # 初期案内メッセージを字幕に表示
    app.update_subtitle("Zoom Translator 起動中... システム音声を待っています")

    # 7. アプリケーション終了時のクリーンアップ処理を定義
    def on_closing():
        logger.info("アプリケーションを終了しています...")
        try:
            audio_capturer.stop()
            logger.info("AudioCapturerを停止しました。")
        except Exception as e:
            logger.error(f"AudioCapturer停止時にエラー: {e}")
        
        try:
            app.destroy()
        except Exception as e:
            logger.error(f"Window破棄時にエラー: {e}")

    # ウィンドウの×ボタン（閉じる操作）にクリーンアップをバインド
    app.protocol("WM_DELETE_WINDOW", on_closing)

    # 8. メインループの実行（ウィンドウクローズ時にAudioCapturer.stop()を呼ぶ）
    try:
        app.run()
    except KeyboardInterrupt:
        logger.info("キーボード割り込みを検知しました。終了します。")
        on_closing()
    except Exception as e:
        logger.error(f"メインループ実行中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
        on_closing()


if __name__ == "__main__":
    main()
