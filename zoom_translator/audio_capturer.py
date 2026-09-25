"""
AudioCapturer module for capturing system audio (speaker output) loopback using soundcard
and detecting speech segments using webrtcvad.
"""

import threading
import time
from typing import Callable, Optional
import numpy as np

try:
    import soundcard as sc
except ImportError:
    sc = None

try:
    import webrtcvad
except ImportError:
    webrtcvad = None

from config import Config, default_config


class AudioCapturer:
    """
    soundcardライブラリを使用してWindowsのデフォルトスピーカー出力をループバック録音し、
    webrtcvadライブラリを用いて発話区切り検出(VAD)を行って文単位の音声チャンクを
    コールバック関数に渡すクラス。
    """

    def __init__(self, config: Config = default_config, on_chunk: Optional[Callable[[np.ndarray], None]] = None):
        """
        AudioCapturerの初期化。

        Args:
            config (Config): 設定オブジェクト (default_config)
            on_chunk (Callable[[np.ndarray], None], optional): チャンク取得時に呼ばれるコールバック関数。
                                                                 引数としてfloat32のnumpy配列(モノラル)を受け取る。
        """
        self.config = config
        self.on_chunk = on_chunk
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """
        バックグラウンドスレッドを起動し、ループバック録音とVAD処理を開始する。
        """
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """
        録音スレッドを安全に停止する。
        """
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _capture_loop(self) -> None:
        """
        soundcardからストリーム録音し、webrtcvadで小フレームごとの発話/無音を判定しながら、
        自然な発話セグメント単位（VAD無音継続 or 最大秒数超過フェイルセーフ）で
        バッファリングしてon_chunkコールバックに渡す内部ループ。
        """
        if sc is None:
            print("[AudioCapturer Error] soundcard library is not installed.")
            return

        if webrtcvad is None:
            print("[AudioCapturer Error] webrtcvad library is not installed.")
            return

        sample_rate = self.config.SAMPLE_RATE
        # webrtcvadがサポートするサンプリングレートは 8000, 16000, 32000, 48000 のみ
        if sample_rate not in (8000, 16000, 32000, 48000):
            print(f"[AudioCapturer Error] Unsupported sample rate for webrtcvad: {sample_rate}Hz. Supported: 8000, 16000, 32000, 48000")
            return

        device_name = self.config.SPEAKER_DEVICE_NAME
        vad_aggressiveness = self.config.VAD_AGGRESSIVENESS
        vad_frame_ms = self.config.VAD_FRAME_MS  # 10, 20, 30 ms

        if vad_frame_ms not in (10, 20, 30):
            print(f"[AudioCapturer Error] Unsupported VAD frame ms: {vad_frame_ms}. Supported: 10, 20, 30")
            return

        vad_silence_ms = self.config.VAD_SILENCE_MS
        max_segment_sec = self.config.MAX_SEGMENT_SEC
        min_segment_sec = self.config.MIN_SEGMENT_SEC

        # 1小フレームあたりのサンプル数 (例: 16000Hz * 0.03s = 480 サンプル)
        frame_samples = int(sample_rate * vad_frame_ms / 1000)

        try:
            # webrtcvadインスタンスの初期化
            vad = webrtcvad.Vad(vad_aggressiveness)

            # スピーカーデバイスの取得
            if device_name:
                speaker = sc.get_microphone(id=str(device_name), include_loopback=True)
            else:
                # デフォルトのスピーカー（ループバック用）を取得
                speaker = sc.default_speaker()
                if speaker is None:
                    print("[AudioCapturer Error] Default speaker not found.")
                    return
                try:
                    speaker = sc.get_microphone(speaker.name, include_loopback=True)
                except Exception:
                    mics = sc.all_speakers(include_loopback=True)
                    if mics:
                        speaker = mics[0]
                    else:
                        raise RuntimeError("No loopback speaker device available.")

            print(f"[AudioCapturer] Starting VAD recording from speaker: {speaker.name} (Sample Rate: {sample_rate}Hz, Frame: {vad_frame_ms}ms, Aggressiveness: {vad_aggressiveness})")

            # セグメント管理用の変数
            segment_frames = []  # float32の小フレーム配列のリスト
            in_speech = False
            silent_frames_count = 0
            # 無音判定に必要な連続無音フレーム数
            required_silent_frames = int(vad_silence_ms / vad_frame_ms)
            if required_silent_frames < 1:
                required_silent_frames = 1

            current_segment_duration = 0.0

            # soundcardのレコーダーを起動 (フレーム単位またはブロック単位で取得)
            with speaker.recorder(samplerate=sample_rate) as recorder:
                while self._running:
                    # 1小フレーム分の音声データを取得 (float32, 2ch等の可能性があるため録音時はframe_samples分取得)
                    data = recorder.record(numframes=frame_samples)
                    if data is None or len(data) == 0:
                        time.sleep(0.005)
                        continue

                    # ステレオ(またはマルチチャンネル)の場合はモノラルに変換（平均を取る）
                    if data.ndim > 1 and data.shape[1] > 1:
                        mono_data = np.mean(data, axis=1)
                    else:
                        mono_data = data.flatten()

                    # float32のnumpy配列として保証
                    mono_data = mono_data.astype(np.float32)

                    # webrtcvadに渡すためint16 PCMバイト列に変換
                    # float32 (-1.0 ~ 1.0) を int16 (-32768 ~ 32767) にスケーリングしてクリップ
                    audio_int16 = (mono_data * 32767.0).clip(-32768, 32767).astype(np.int16)
                    frame_bytes = audio_int16.tobytes()

                    # webrtcvadで発話判定
                    try:
                        is_speech = vad.is_speech(frame_bytes, sample_rate)
                    except Exception as e:
                        # ま稀にフレームサイズ違反等のエラーが出た場合のフォールバック
                        is_speech = False

                    frame_duration = vad_frame_ms / 1000.0

                    if is_speech:
                        if not in_speech:
                            # 発話開始
                            in_speech = True
                            segment_frames = []
                            current_segment_duration = 0.0
                        
                        segment_frames.append(mono_data)
                        current_segment_duration += frame_duration
                        silent_frames_count = 0

                        # (4) 発話が途切れず MAX_SEGMENT_SEC を超えた場合のフェイルセーフ
                        if current_segment_duration >= max_segment_sec:
                            if segment_frames:
                                combined_segment = np.concatenate(segment_frames)
                                if len(combined_segment) >= int(sample_rate * min_segment_sec):
                                    if self.on_chunk is not None:
                                        try:
                                            self.on_chunk(combined_segment)
                                        except Exception as e:
                                            print(f"[AudioCapturer Error] Exception in on_chunk callback: {e}")
                            # バッファ・状態のリセット
                            segment_frames = []
                            in_speech = False
                            silent_frames_count = 0
                            current_segment_duration = 0.0

                    else:
                        # 無音フレーム
                        if in_speech:
                            segment_frames.append(mono_data)
                            current_segment_duration += frame_duration
                            silent_frames_count += 1

                            # (3) 連続無音が VAD_SILENCE_MS 以上続いたらセグメント確定
                            if silent_frames_count >= required_silent_frames:
                                if segment_frames:
                                    combined_segment = np.concatenate(segment_frames)
                                    # MIN_SEGMENT_SEC 未満の短いセグメントはノイズとして破棄
                                    if len(combined_segment) >= int(sample_rate * min_segment_sec):
                                        if self.on_chunk is not None:
                                            try:
                                                self.on_chunk(combined_segment)
                                            except Exception as e:
                                                print(f"[AudioCapturer Error] Exception in on_chunk callback: {e}")
                                    else:
                                        print(f"[AudioCapturer] Discarded short segment (duration: {len(combined_segment)/sample_rate:.2f}s < {min_segment_sec}s)")

                                # バッファ・状態のリセット
                                segment_frames = []
                                in_speech = False
                                silent_frames_count = 0
                                current_segment_duration = 0.0
                        else:
                            # 非発話中かつ無音の場合は何もしない（あるいは無駄なバッファリングなし）
                            pass

        except Exception as e:
            print(f"[AudioCapturer Error] Exception in capture loop: {e}")
        finally:
            # 停止時に未処理のバッファがあれば必要に応じてフラッシュ（オプション、今回は破棄または処理）
            self._running = False
            print("[AudioCapturer] VAD recording stopped.")
