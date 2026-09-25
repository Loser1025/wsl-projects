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
import time

# サードパーティの大量のINFOログを抑制 (HTTPX, HTTPCore, HuggingFace Hub, Urllib3)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# プロジェクトルートディレクトリをsys.pathに追加してフラットインポート可能にする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import default_config
from audio_capturer import AudioCapturer, list_speaker_devices
from translator_engine import TranslatorEngine
from sentence_buffer import SentenceBuffer
from gui import SubtitleWindow
import settings_store

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
    try:
        settings_store.load_settings(config)
        logger.info("前回保存された設定をロードしました。")
    except Exception as e:
        logger.error(f"設定のロード中にエラーが発生しました: {e}")

    # 設定変更保存時のコールバック関数
    def on_save_settings(source_lang: str, target_lang: str, device_name: str):
        """
        GUIの設定パネルから設定が保存されたときに呼ばれるコールバック。
        設定をconfigに反映し、永続化し、AudioCapturerを再起動する。
        """
        try:
            logger.info(f"設定保存コールバック受信: source={source_lang}, target={target_lang}, device={device_name}")
            
            # 言語ペアが変わったかどうかを判定
            lang_changed = (config.SOURCE_LANG != source_lang) or (config.TARGET_LANG != target_lang)

            # configの更新
            config.SOURCE_LANG = source_lang
            config.TARGET_LANG = target_lang
            if device_name:
                config.SPEAKER_DEVICE_NAME = device_name
            else:
                config.SPEAKER_DEVICE_NAME = None

            # 設定の永続化
            settings_store.save_settings(config)
            logger.info("設定をsettings.jsonに保存しました。")

            # 言語ペアが変わった場合、古い言語設定の残骸が混ざらないようsentence_bufferをフラッシュする
            if lang_changed:
                try:
                    flushed = sentence_buffer.flush()
                    if flushed:
                        logger.info(f"言語ペア変更に伴うバッファフラッシュ: {flushed}")
                except Exception as ex:
                    logger.error(f"SentenceBufferフラッシュ時にエラー: {ex}")

            # AudioCapturerの再起動 (stop -> start)
            try:
                audio_capturer.stop()
                logger.info("新しい設定を適用するためAudioCapturerを一旦停止しました。")
            except Exception as ex:
                logger.error(f"AudioCapturer停止時にエラー: {ex}")

            try:
                audio_capturer.start()
                logger.info("新しい設定でAudioCapturerを再起動しました。")
            except Exception as ex:
                logger.error(f"AudioCapturer再起動時にエラー: {ex}")

        except Exception as e:
            logger.error(f"on_save_settings処理中にエラーが発生しました: {e}")
            logger.debug(traceback.format_exc())

    # 各コンポーネントの初期化
    translator_engine = TranslatorEngine(config=config)
    sentence_buffer = SentenceBuffer(config=config)
    # 音声チャンクを受け渡すためのオーディオキューを新設
    audio_queue = queue.Queue()
    result_queue = queue.Queue()

    # AudioCapturerのon_chunkコールバック関数
    def handle_audio_chunk(audio_chunk):
        """
        AudioCapturerのバックグラウンドスレッドから呼ばれる軽量コールバック。
        音声チャンクを audio_queue に put するだけで即座に return し、
        録音スレッドをブロックしない。
        キュー投入時刻とチャンクの音声長(秒)も一緒に積み、stt_worker側で
        「録音〜処理開始までの待ち時間」と「音声の実長」をログに出せるようにする。
        """
        try:
            queued_at = time.monotonic()
            segment_duration_sec = len(audio_chunk) / float(config.SAMPLE_RATE)
            audio_queue.put((audio_chunk, queued_at, segment_duration_sec))
        except Exception as e:
            logger.error(f"音声チャンクのキュー投入中にエラーが発生しました: {e}")

    # STT・翻訳処理を行うバックグラウンドワーカー関数を新設
    def stt_worker():
        """
        audio_queueを監視し、音声チャンクを取り出して
        transcribe → add_fragment → (文完成時) translate → result_queue.put
        の一連の重い処理を非同期で行うワーカー関数。
        """
        logger.info("STTワーカー（音声処理スレッド）を開始しました。")
        while True:
            try:
                # 音声チャンクがaudio_queueに積まれてから取り出されるまでの待ち時間を計測するため、
                # AudioCapturer側でチャンクが確定した時刻(queued_at)も一緒に受け取る
                item = audio_queue.get()
                if item is None:  # 終了シグナル
                    audio_queue.task_done()
                    break
                audio_chunk, queued_at, segment_duration_sec = item

                dequeued_at = time.monotonic()
                queue_wait_sec = dequeued_at - queued_at
                backlog = audio_queue.qsize()

                # 1. 音声認識 (Transcribe) の所要時間を計測
                t0 = time.monotonic()
                fragment = translator_engine.transcribe(audio_chunk)
                transcribe_sec = time.monotonic() - t0

                if not fragment:
                    logger.info(
                        f"[TIMING] 無音/認識結果なし | 音声長={segment_duration_sec:.2f}s "
                        f"キュー待ち={queue_wait_sec:.2f}s 認識={transcribe_sec:.2f}s 未処理キュー残={backlog}"
                    )
                    audio_queue.task_done()
                    continue

                logger.info(f"認識断片: {fragment}")

                # 2. 文バッファに追加 (SentenceBuffer)
                sentence = sentence_buffer.add_fragment(fragment)
                translate_sec = 0.0
                if sentence:
                    logger.info(f"完成文(原文): {sentence}")
                    # 3. 翻訳 (Translate) の所要時間を計測
                    t1 = time.monotonic()
                    translated = translator_engine.translate(sentence)
                    translate_sec = time.monotonic() - t1
                    logger.info(f"翻訳文: {translated}")

                    # 4. キューに格納 (original, translated)
                    result_queue.put((sentence, translated))

                # このチャンク1件にかかった総所要時間の内訳をログ出力する
                # (queue_wait: 録音〜処理開始までの待ち行列時間, transcribe/translate: 各処理の実処理時間)
                logger.info(
                    f"[TIMING] 音声長={segment_duration_sec:.2f}s "
                    f"キュー待ち={queue_wait_sec:.2f}s 認識={transcribe_sec:.2f}s 翻訳={translate_sec:.2f}s "
                    f"未処理キュー残={backlog}"
                )

                audio_queue.task_done()

            except Exception as e:
                logger.error(f"STTワーカー処理中にエラーが発生しました: {e}")
                logger.debug(traceback.format_exc())
                try:
                    audio_queue.task_done()
                except Exception:
                    pass

    # AudioCapturerのインスタンス化
    audio_capturer = AudioCapturer(config=config, on_chunk=handle_audio_chunk)

    # SubtitleWindowのインスタンス化
    try:
        window = SubtitleWindow(
            config=config,
            get_devices_fn=list_speaker_devices,
            save_settings_fn=on_save_settings
        )
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

        # キュー消費スレッドの起動 (stt_worker と pipeline_worker)
        stt_thread = threading.Thread(target=stt_worker, daemon=True)
        stt_thread.start()

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
            audio_queue.put(None)
        except Exception:
            pass

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
