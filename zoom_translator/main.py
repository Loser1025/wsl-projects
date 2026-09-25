"""
zoom_translator/main.py

AudioCapturer, TranslatorEngine, SentenceBuffer, SubtitleWindowをqueueで結合し、
リアルタイム翻訳字幕アプリとして動作させるエントリーポイントモジュール。
"""

import queue
import threading
import logging
import traceback
import sys
import os

# サードパーティの大量のINFOログを抑制 (HTTPX, HTTPCore, HuggingFace Hub, Urllib3)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# プロジェクトルートディレクトリをsys.pathに追加してフラットインポート可能にする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import default_config
from audio_capturer import AudioCapturer
from translator_engine import TranslatorEngine
from sentence_buffer import SentenceBuffer
from gui import SubtitleWindow

# ロギングの設定 (自アプリのロガーはINFO)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ZoomTranslatorMain")


def main():
    """
    アプリケーションのエントリーポイント。
    設定読み込み、各コンポーネント（AudioCapturer, TranslatorEngine, SentenceBuffer, SubtitleWindow, Queue）の
    初期化と接続、およびメインループの実行を行う。
    """
    logger.info("Zoom Translator アプリケーションを起動しています...")

    # 設定の読み込み
    config = default_config

    # 各コンポーネントの初期化
    translator_engine = TranslatorEngine(config=config)
    sentence_buffer = SentenceBuffer(config=config)
    result_queue = queue.Queue()

    # AudioCapturerのon_chunkコールバック関数
    def handle_audio_chunk(audio_chunk):
        """
        AudioCapturerのバックグラウンドスレッドから呼ばれるコールバック。
        音声チャンクを translator_engine.transcribe(audio_chunk) でテキスト化し、
        sentence_buffer.add_fragment(text) に渡す。
        完成した文が得られたら translator_engine.translate(sentence) で翻訳し、
        (sentence, translated) のタプルを result_queue に格納する。
        """
        try:
            # 1. 音声認識 (Transcribe)
            fragment = translator_engine.transcribe(audio_chunk)
            if not fragment:
                return

            logger.info(f"認識断片: {fragment}")

            # 2. 文バッファに追加 (SentenceBuffer)
            sentence = sentence_buffer.add_fragment(fragment)
            if sentence:
                logger.info(f"完成文(原文): {sentence}")
                # 3. 翻訳 (Translate)
                translated = translator_engine.translate(sentence)
                logger.info(f"翻訳文: {translated}")

                # 4. キューに格納 (original, translated)
                result_queue.put((sentence, translated))

        except Exception as e:
            logger.error(f"音声チャンク処理中にエラーが発生しました: {e}")
            logger.debug(traceback.format_exc())

    # AudioCapturerのインスタンス化
    audio_capturer = AudioCapturer(config=config, on_chunk=handle_audio_chunk)

    # SubtitleWindowのインスタンス化
    try:
        window = SubtitleWindow(config=config)
    except Exception as e:
        logger.error(f"SubtitleWindowの初期化に失敗しました: {e}")
        traceback.print_exc()
        sys.exit(1)

    # バックグラウンドスレッドでresult_queueを消費してwindow.update_subtitle()を呼び出す関数
    def pipeline_worker():
        """
        result_queueを監視し、(original, translated)を取り出してSubtitleWindowの字幕を更新するループ。
        """
        logger.info("パイプラインワーカー（キュー消費者）を開始しました。")
        while True:
            try:
                item = result_queue.get()
                if item is None: # 終了シグナル
                    result_queue.task_done()
                    break
                
                original, translated = item
                window.update_subtitle(original, translated)
                result_queue.task_done()
            except Exception as e:
                logger.error(f"パイプラインワーカー処理中にエラーが発生しました: {e}")

    # pywebview起動時のコールバック（run()内でウィンドウが準備完了したときに呼ばれる）
    def start_pipeline():
        """
        windowの準備完了時に呼ばれ、AudioCapturerを開始し、キュー消費者スレッドを起動する。
        """
        logger.info("SubtitleWindowの準備が完了しました。パイプラインを開始します。")
        
        # 初期案内メッセージを表示
        try:
            window.update_subtitle("Zoom Translator 起動中...", "システム音声を待っています...")
        except Exception:
            pass

        # キュー消費スレッドの起動
        worker_thread = threading.Thread(target=pipeline_worker, daemon=True)
        worker_thread.start()

        # AudioCapturerの開始
        try:
            audio_capturer.start()
            logger.info("AudioCapturer (システム音声キャプチャ) を開始しました。")
        except Exception as e:
            logger.error(f"AudioCapturerの起動に失敗しました: {e}")

    # ウィンドウクローズ時のコールバック
    def on_closing():
        logger.info("アプリケーション終了処理を呼び出しています...")
        
        # AudioCapturerの停止
        try:
            audio_capturer.stop()
            logger.info("AudioCapturerを停止しました。")
        except Exception as e:
            logger.error(f"AudioCapturer停止時にエラー: {e}")

        # SentenceBufferに残ったフラグメントがあればflushしてログ出力
        try:
            remaining = sentence_buffer.flush()
            if remaining:
                logger.info(f"未完了のバッファ残り(フラッシュ): {remaining}")
                # 必要であれば翻訳して表示またはログ出力
                translated_rem = translator_engine.translate(remaining)
                logger.info(f"残りフラグメント翻訳: {translated_rem}")
                # キューに送信してウィンドウを更新
                result_queue.put((remaining, translated_rem))
        except Exception as e:
            logger.error(f"SentenceBufferフラッシュ時にエラー: {e}")

        # キューに終了シグナルを入れてワーカーを終了させる
        try:
            result_queue.put(None)
        except Exception:
            pass

    # windowにクローズコールバックを登録
    try:
        window.set_on_close(on_closing)
    except Exception as e:
        logger.error(f"set_on_closeの設定に失敗しました: {e}")

    # SubtitleWindowの起動（メインスレッドでブロッキング実行、on_readyでstart_pipelineコールバックを呼ぶ）
    try:
        window.run(on_ready=start_pipeline)
    except KeyboardInterrupt:
        logger.info("キーボード割り込みを検知しました。終了します。")
        on_closing()
    except Exception as e:
        logger.error(f"メインループ実行中に予期せぬエラーが発生しました: {e}")
        traceback.print_exc()
        on_closing()


if __name__ == "__main__":
    main()
