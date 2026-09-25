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

        # webrtcvad初期化
        vad = webrtcvad.Vad(vad_aggressiveness)

        # 1フレームあたりのサンプル数 (例: 16000Hz * 0.03s = 480 samples)
        frame_samples = int(sample_rate * (vad_frame_ms / 1000.0))
        # 1フレームあたりのバイト数 (16bit PCM = 2 bytes per sample)
        frame_bytes = frame_samples * 2

        # VADパラメータ設定
        silence_ms = self.config.VAD_SILENCE_MS
        max_segment_sec = self.config.MAX_SEGMENT_SEC
        min_segment_sec = self.config.MIN_SEGMENT_SEC

        required_silent_frames = int(silence_ms / vad_frame_ms)

        print(f"[AudioCapturer] Starting VAD recording. Device: {device_name or 'Default'}, Sample Rate: {sample_rate}Hz, VAD Mode: {vad_aggressiveness}")

        try:
            # ループバック録音はsoundcardでは「マイク」側API(all_microphones/get_microphone)に
            # include_loopback=Trueを渡す形で提供される（all_speakers/default_speakerには
            # include_loopback引数は存在しない）。
            speaker = None
            if device_name:
                try:
                    mics = sc.all_microphones(include_loopback=True)
                    for m in mics:
                        if device_name.lower() in m.name.lower():
                            speaker = m
                            break
                    if speaker is None:
                        print(f"[AudioCapturer Warning] Speaker device '{device_name}' not found. Falling back to default loopback.")
                except Exception as e:
                    print(f"[AudioCapturer Warning] Failed to find speaker '{device_name}': {e}. Falling back to default.")

            if speaker is None:
                # デフォルトスピーカーの名前を取得し、ループバック対応マイク一覧の中から
                # 同名のものを探す（見つからなければ先頭のループバックデバイスにフォールバック）
                default_spk = sc.default_speaker()
                loopback_mics = sc.all_microphones(include_loopback=True)
                for m in loopback_mics:
                    if m.name == default_spk.name:
                        speaker = m
                        break
                if speaker is None and loopback_mics:
                    speaker = loopback_mics[0]
                if speaker is None:
                    raise RuntimeError("No loopback speaker device available.")

            # soundcardのレコーダーを開始
            # blocksizeはframe_samplesに合わせるのが効率的
            with speaker.recorder(samplerate=sample_rate, channels=1, blocksize=frame_samples) as recorder:
                segment_frames = []
                in_speech = False
                silent_frames_count = 0
                current_segment_duration = 0.0

                while self._running:
                    # 録音ブロック取得 (float32, shape=(blocksize, 1))
                    data = recorder.record(numframes=frame_samples)
                    if data is None or len(data) == 0:
                        continue

                    # モノラルに変換（既に1chだが念のためflatten）
                    audio_float32 = data.flatten()

                    # webrtcvad用に対象フレームをint16 PCM (bytes) に変換
                    # float32 (-1.0 ~ 1.0) -> int16 (-32768 ~ 32767)
                    audio_int16 = np.clip(audio_float32 * 32768.0, -32768, 32767).astype(np.int16)
                    pcm_data = audio_int16.tobytes()

                    # VAD判定
                    try:
                        is_speech = vad.is_speech(pcm_data, sample_rate)
                    except Exception as e:
                        # 不正なフレーム長などの例外を防ぐ
                        continue

                    frame_duration = vad_frame_ms / 1000.0

                    if is_speech:
                        if not in_speech:
                            in_speech = True
                            # 発話開始：先行バッファ（もし持たせるなら）等。今回は即座にセグメント追加開始
                        segment_frames.append(audio_float32)
                        silent_frames_count = 0
                        current_segment_duration += frame_duration
                    else:
                        if in_speech:
                            segment_frames.append(audio_float32)
                            silent_frames_count += 1
                            current_segment_duration += frame_duration

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

                    # (2) 最大秒数 MAX_SEGMENT_SEC を超えた場合のフェイルセーフ
                    if in_speech and current_segment_duration >= max_segment_sec:
                        print(f"[AudioCapturer] Max segment duration ({max_segment_sec}s) reached. Forcing chunk emission.")
                        if segment_frames:
                            combined_segment = np.concatenate(segment_frames)
                            if len(combined_segment) >= int(sample_rate * min_segment_sec):
                                if self.on_chunk is not None:
                                    try:
                                        self.on_chunk(combined_segment)
                                    except Exception as e:
                                        print(f"[AudioCapturer Error] Exception in on_chunk callback: {e}")
                        segment_frames = []
                        in_speech = False
                        silent_frames_count = 0
                        current_segment_duration = 0.0

        except Exception as e:
            print(f"[AudioCapturer Error] Exception in capture loop: {e}")
        finally:
            # 停止時に未処理のバッファがあれば必要に応じてフラッシュ（オプション、今回は破棄または処理）
            self._running = False
            print("[AudioCapturer] VAD recording stopped.")


def list_speaker_devices() -> list[str]:
    """
    soundcardライブラリを使用してループバック可能なスピーカーデバイスの名前一覧を取得する。
    soundcard未インストール環境や取得失敗時は例外を投げずに空リストを返す。

    Returns:
        list[str]: スピーカーデバイス名のリスト
    """
    if sc is None:
        return []
    try:
        # include_loopbackはall_microphones/get_microphone側の引数(all_speakersには存在しない)
        devices = sc.all_microphones(include_loopback=True)
        names = []
        for dev in devices:
            if hasattr(dev, 'name') and dev.name:
                names.append(dev.name)
            elif isinstance(dev, str):
                names.append(dev)
        return names
    except Exception as e:
        print(f"[AudioCapturer Error] Failed to list speaker devices: {e}")
        return []
