"""
zoom_translator/main.py

AudioCapturer, TranslatorEngine, SentenceBuffer, SubtitleWindowをqueueで結合し、
スピーカー(相手の声)とマイク(あなたの声)の2系統を並行実行するリアルタイム翻訳アプリのエントリーポイント。
"""

import queue
import threading
import logging
import traceback
import sys
import os
import time

# サードパーティの大量のINFOログを抑制 (HTTPX, HTTPCore, HuggingFace Hub, Urllib3,
# argostranslateの内部処理詳細ログ, faster-whisperの音声区間ログ)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("argostranslate.utils").setLevel(logging.WARNING)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)
logging.getLogger("stanza").setLevel(logging.WARNING)

# プロジェクトルートディレクトリをsys.pathに追加してフラットインポート可能にする
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import default_config
from audio_capturer import AudioCapturer, list_speaker_devices, list_microphone_devices
from translator_engine import TranslatorEngine
from sentence_buffer import SentenceBuffer
from gui import SubtitleWindow
import settings_store

# ログをファイルにも残す(zoom_translator/logs/latest.log、起動のたびに上書き)。
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE_PATH = os.path.join(LOG_DIR, "latest.log")

# ロギングの設定 (自アプリのロガーはINFO、コンソール+ファイルの両方に出力)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE_PATH, mode="w", encoding="utf-8"),
    ],
    force=True,
)
logger = logging.getLogger("ZoomTranslatorMain")


def main():
    """
    アプリケーションのエントリーポイント。
    設定読み込み、各コンポーネント（AudioCapturerx2, TranslatorEngine(共有), SentenceBufferx2, SubtitleWindow, Queuex4）の
    初期化と接続、およびメインループの実行を行う。
    """
    logger.info("Zoom Translator (2系統並行実行) アプリケーションを起動しています...")

    # (1) config = default_config の直後で settings_store.load_settings(config) を呼ぶ
    config = default_config
    try:
        settings_store.load_settings(config)
        logger.info(f"前回保存された設定をロードしました: SPEAKER_DEVICE={config.SPEAKER_DEVICE_NAME}, MIC_DEVICE={config.MIC_DEVICE_NAME}")
    except Exception as e:
        logger.error(f"設定のロード中にエラーが発生しました: {e}")

    # (2) TranslatorEngine(config=config) は1インスタンスのみ作成し、スピーカー用・マイク用の両方の翻訳呼び出しで共有する
    translator_engine = TranslatorEngine(config=config)

    # 独立した2つの SentenceBuffer を作成 (バッファ状態は独立させる必要があるため)
    speaker_sentence_buffer = SentenceBuffer(config=config)
    mic_sentence_buffer = SentenceBuffer(config=config)

    # (3) audio_queue・result_queueもスピーカー用・マイク用でそれぞれ独立させる
    speaker_audio_queue = queue.Queue()
    speaker_result_queue = queue.Queue()

    mic_audio_queue = queue.Queue()
    mic_result_queue = queue.Queue()

    # (4) AudioCapturer用コールバック関数
    def handle_speaker_chunk(audio_np):
        """スピーカーからの音声チャンク受信時コールバック (キュー投入時刻・音声長を一緒に積む)"""
        try:
            now = time.monotonic()
            duration_sec = float(len(audio_np)) / float(config.AUDIO_SAMPLE_RATE)
            speaker_audio_queue.put((now, audio_np, duration_sec))
        except Exception as e:
            logger.error(f"[speaker] 音声チャンクのキュー投入時にエラー: {e}")

    def handle_mic_chunk(audio_np):
        """マイクからの音声チャンク受信時コールバック (キュー投入時刻・音声長を一緒に積む)"""
        try:
            now = time.monotonic()
            duration_sec = float(len(audio_np)) / float(config.AUDIO_SAMPLE_RATE)
            mic_audio_queue.put((now, audio_np, duration_sec))
        except Exception as e:
            logger.error(f"[mic] 音声チャンクのキュー投入時にエラー: {e}")

    # AudioCapturerを2つ作成
    speaker_audio_capturer = AudioCapturer(
        config=config,
        on_chunk=handle_speaker_chunk,
        source_type="speaker"
    )
    mic_audio_capturer = AudioCapturer(
        config=config,
        on_chunk=handle_mic_chunk,
        source_type="mic"
    )

    # (5) stt_worker相当の処理をパラメータ化して共通関数として定義
    def stt_worker(audio_q, sentence_buf, result_q, source_lang, target_lang, label):
        """
        音声認識(STT)・文バッファリング・翻訳(Translate)を行うワーカー関数。
        スピーカー用・マイク用でそれぞれ独立したスレッドとして起動する。
        """
        logger.info(f"{label} STTワーカーを開始しました。(source={source_lang}, target={target_lang})")
        while True:
            try:
                item = audio_q.get()
                if item is None:  # 終了シグナル
                    audio_q.task_done()
                    break

                enqueued_time, audio_chunk, segment_duration_sec = item
                queue_wait_sec = time.monotonic() - enqueued_time
                backlog = audio_q.qsize()

                # 1. 音声認識 (Whisper)
                t0 = time.monotonic()
                fragment = translator_engine.transcribe(audio_chunk, language=source_lang)
                transcribe_sec = time.monotonic() - t0

                if not fragment:
                    logger.info(
                        f"[TIMING] {label} 無音/認識結果なし | 音声長={segment_duration_sec:.2f}s "
                        f"キュー待ち={queue_wait_sec:.2f}s 認識={transcribe_sec:.2f}s 未処理キュー残={backlog}"
                    )
                    audio_q.task_done()
                    continue

                logger.info(f"{label} 認識断片: {fragment}")

                # 2. 文バッファに追加 (SentenceBuffer)
                sentence = sentence_buf.add_fragment(fragment)
                translate_sec = 0.0
                if sentence:
                    logger.info(f"{label} 完成文(原文): {sentence}")
                    # 3. 翻訳 (Translate)
                    t1 = time.monotonic()
                    translated = translator_engine.translate(sentence, source_lang=source_lang, target_lang=target_lang)
                    translate_sec = time.monotonic() - t1
                    logger.info(f"{label} 翻訳文: {translated}")

                    # 4. キューに格納 (original, translated)
                    result_q.put((sentence, translated))
                else:
                    # 文が未完成の間も sentence_buffer.peek() で蓄積中テキストを取得し仮翻訳して即座に表示
                    peeked_text = sentence_buf.peek()
                    if peeked_text:
                        t1 = time.monotonic()
                        translated_peek = translator_engine.translate(peeked_text, source_lang=source_lang, target_lang=target_lang)
                        translate_sec = time.monotonic() - t1
                        logger.info(f"[TIMING] {label} [暫定] 蓄積中原文: {peeked_text} -> 暫定翻訳文: {translated_peek}")
                        result_q.put((peeked_text, translated_peek))

                total_sec = queue_wait_sec + transcribe_sec + translate_sec
                logger.info(
                    f"[TIMING] {label} 処理完了 | 音声長={segment_duration_sec:.2f}s "
                    f"キュー待ち={queue_wait_sec:.2f}s 認識={transcribe_sec:.2f}s 翻訳={translate_sec:.2f}s "
                    f"合計={total_sec:.2f}s 未処理キュー残={backlog}"
                )

                audio_q.task_done()
            except Exception as e:
                logger.error(f"{label} STTワーカー処理中にエラーが発生しました: {e}")
                traceback.print_exc()

    # (6) result_queueを消費してGUIを更新する処理をパラメータ化
    def pipeline_worker(result_q, update_fn, label):
        """
        result_qを監視し、(original, translated)を取り出して指定されたGUI更新関数を呼び出すワーカー。
        """
        logger.info(f"{label} パイプラインワーカー（キュー消費者）を開始しました。")
        while True:
            try:
                item = result_q.get()
                if item is None:  # 終了シグナル
                    result_q.task_done()
                    break

                original, translated = item
                update_fn(original, translated)
                result_q.task_done()
            except Exception as e:
                logger.error(f"{label} パイプラインワーカー処理中にエラーが発生しました: {e}")

    # (8) on_save_settings(speaker_device: str, mic_device: str) の実装
    def on_save_settings(speaker_device: str, mic_device: str):
        """
        GUIの設定パネルから設定が保存されたときに呼ばれるコールバック。
        configのSPEAKER_DEVICE_NAMEとMIC_DEVICE_NAMEを更新(空文字ならNone)、settings_storeで永続化し、
        スピーカー・マイク両方のAudioCapturerをstop→startして新デバイスで再接続する。
        """
        try:
            logger.info(f"設定保存コールバック受信: speaker_device={speaker_device}, mic_device={mic_device}")

            # configの更新
            config.SPEAKER_DEVICE_NAME = speaker_device if speaker_device else None
            config.MIC_DEVICE_NAME = mic_device if mic_device else None

            # 設定の永続化
            settings_store.save_settings(config)
            logger.info("設定をsettings.jsonに保存しました。")

            # スピーカー用 AudioCapturerの再起動 (stop -> start)
            try:
                speaker_audio_capturer.stop()
                logger.info("スピーカー用 AudioCapturerを停止しました。")
            except Exception as ex:
                logger.error(f"スピーカー用 AudioCapturer停止時にエラー: {ex}")

            try:
                speaker_audio_capturer.start()
                logger.info("新しいデバイスでスピーカー用 AudioCapturerを再開始しました。")
            except Exception as ex:
                logger.error(f"スピーカー用 AudioCapturer再開始時にエラー: {ex}")

            # マイク用 AudioCapturerの再起動 (stop -> start)
            try:
                mic_audio_capturer.stop()
                logger.info("マイク用 AudioCapturerを停止しました。")
            except Exception as ex:
                logger.error(f"マイク用 AudioCapturer停止時にエラー: {ex}")

            try:
                mic_audio_capturer.start()
                logger.info("新しいデバイスでマイク用 AudioCapturerを再開始しました。")
            except Exception as ex:
                logger.error(f"マイク用 AudioCapturer再開始時にエラー: {ex}")

        except Exception as e:
            logger.error(f"on_save_settings処理中にエラーが発生しました: {e}")
            traceback.print_exc()

    # (7) SubtitleWindowのインスタンス化
    window = SubtitleWindow(
        config=config,
        get_speaker_devices_fn=list_speaker_devices,
        get_mic_devices_fn=list_microphone_devices,
        save_settings_fn=on_save_settings
    )

    # (9) start_pipeline()の実装
    def start_pipeline():
        """
        windowの準備完了時に呼ばれる。まずtranslator_engine.warmup()を1回呼び、
        完了後にスピーカー用・マイク用の両方のstt_workerスレッドとresult_queue消費スレッドを起動し、
        両方のAudioCapturerをstart()する。
        """
        logger.info("SubtitleWindowの準備が完了しました。モデルの事前ロードを開始します。")

        # 準備中案内表示
        try:
            window.update_speaker_subtitle("Zoom Translator 準備中...", "モデルを読み込んでいます...")
            window.update_mic_subtitle("Zoom Translator 準備中...", "모델을 로딩 중입니다...")
        except Exception:
            pass

        # Whisper / NLLB / argos の事前ロード (1回呼び出しで共有)
        try:
            translator_engine.warmup()
            logger.info("モデルの事前ロードが完了しました。")
        except Exception as e:
            logger.error(f"モデルの事前ロード中にエラーが発生しました: {e}")

        # 準備完了の案内表示
        try:
            window.update_speaker_subtitle("Zoom Translator 起動中...", "スピーカー音声を待っています...")
            window.update_mic_subtitle("Zoom Translator 起動中...", "마이크 음성을 기다리고 있습니다...")
        except Exception:
            pass

        # スピーカー用スレッド起動
        speaker_stt_thread = threading.Thread(
            target=stt_worker,
            args=(speaker_audio_queue, speaker_sentence_buffer, speaker_result_queue, config.SPEAKER_SOURCE_LANG, config.SPEAKER_TARGET_LANG, "[speaker]"),
            daemon=True
        )
        speaker_stt_thread.start()

        speaker_worker_thread = threading.Thread(
            target=pipeline_worker,
            args=(speaker_result_queue, window.update_speaker_subtitle, "[speaker]"),
            daemon=True
        )
        speaker_worker_thread.start()

        # マイク用スレッド起動
        mic_stt_thread = threading.Thread(
            target=stt_worker,
            args=(mic_audio_queue, mic_sentence_buffer, mic_result_queue, config.MIC_SOURCE_LANG, config.MIC_TARGET_LANG, "[mic]"),
            daemon=True
        )
        mic_stt_thread.start()

        mic_worker_thread = threading.Thread(
            target=pipeline_worker,
            args=(mic_result_queue, window.update_mic_subtitle, "[mic]"),
            daemon=True
        )
        mic_worker_thread.start()

        # 両方のAudioCapturerを開始
        try:
            speaker_audio_capturer.start()
            logger.info("スピーカー用 AudioCapturer を開始しました。")
        except Exception as e:
            logger.error(f"スピーカー用 AudioCapturerの起動に失敗しました: {e}")

        try:
            mic_audio_capturer.start()
            logger.info("マイク用 AudioCapturer を開始しました。")
        except Exception as e:
            logger.error(f"マイク用 AudioCapturerの起動に失敗しました: {e}")

    # (10) on_closing()の実装
    def on_closing():
        logger.info("アプリケーション終了処理を呼び出しています...")

        # 両方のAudioCapturerをstop()
        try:
            speaker_audio_capturer.stop()
            logger.info("スピーカー用 AudioCapturerを停止しました。")
        except Exception as e:
            logger.error(f"スピーカー用 AudioCapturer停止時にエラー: {e}")

        try:
            mic_audio_capturer.stop()
            logger.info("マイク用 AudioCapturerを停止しました。")
        except Exception as e:
            logger.error(f"マイク用 AudioCapturer停止時にエラー: {e}")

        # スピーカー用 SentenceBuffer 残りフラッシュ
        try:
            remaining_spk = speaker_sentence_buffer.flush()
            if remaining_spk:
                logger.info(f"[speaker] 未完了バッファ残り(フラッシュ): {remaining_spk}")
                translated_spk = translator_engine.translate(remaining_spk, source_lang=config.SPEAKER_SOURCE_LANG, target_lang=config.SPEAKER_TARGET_LANG)
                speaker_result_queue.put((remaining_spk, translated_spk))
        except Exception as e:
            logger.error(f"[speaker] SentenceBufferフラッシュ時にエラー: {e}")

        # マイク用 SentenceBuffer 残りフラッシュ
        try:
            remaining_mic = mic_sentence_buffer.flush()
            if remaining_mic:
                logger.info(f"[mic] 未完了バッファ残り(フラッシュ): {remaining_mic}")
                translated_mic = translator_engine.translate(remaining_mic, source_lang=config.MIC_SOURCE_LANG, target_lang=config.MIC_TARGET_LANG)
                mic_result_queue.put((remaining_mic, translated_mic))
        except Exception as e:
            logger.error(f"[mic] SentenceBufferフラッシュ時にエラー: {e}")

        # キューに終了シグナル (None) を入れる
        try:
            speaker_audio_queue.put(None)
        except Exception:
            pass

        try:
            speaker_result_queue.put(None)
        except Exception:
            pass

        try:
            mic_audio_queue.put(None)
        except Exception:
            pass

        try:
            mic_result_queue.put(None)
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
