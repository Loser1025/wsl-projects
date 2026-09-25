"""
AudioCapturer module for capturing system audio (speaker output) loopback using soundcard.
"""

import threading
import time
from typing import Callable, Optional
import numpy as np

try:
    import soundcard as sc
except ImportError:
    sc = None

from config import Config, default_config


class AudioCapturer:
    """
    soundcardライブラリを使用してWindowsのデフォルトスピーカー出力をループバック録音し、
    一定時間ごとにnumpy配列のチャンクをコールバック関数に渡すクラス。
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
        バックグラウンドスレッドを起動し、ループバック録音を開始する。
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
        録音を継続的に実行し、指定された時間ごとにチャンクをコールバックに渡す内部ループ。
        """
        if sc is None:
            print("[AudioCapturer Error] soundcard library is not installed.")
            return

        sample_rate = self.config.SAMPLE_RATE
        chunk_duration = self.config.CHUNK_DURATION_SEC
        device_name = self.config.SPEAKER_DEVICE_NAME

        # チャンクあたりのサンプル数
        num_frames = int(sample_rate * chunk_duration)

        try:
            # スピーカーデバイスの取得
            if device_name:
                speaker = sc.get_microphone(id=str(device_name), include_loopback=True)
            else:
                # デフォルトのスピーカー（ループバック用）を取得
                speaker = sc.default_speaker()
                if speaker is None:
                    print("[AudioCapturer Error] Default speaker not found.")
                    return
                # ループバック用のマイク/スピーカーを取得
                # soundcardでは sc.get_microphone(sc.default_speaker().name, include_loopback=True) が一般的
                try:
                    speaker = sc.get_microphone(speaker.name, include_loopback=True)
                except Exception:
                    # フォールバックとして利用可能なループバックデバイスを探す
                    mics = sc.all_speakers(include_loopback=True)
                    if mics:
                        speaker = mics[0]
                    else:
                        raise RuntimeError("No loopback speaker device available.")

            print(f"[AudioCapturer] Starting recording from speaker: {speaker.name} (Sample Rate: {sample_rate}Hz)")

            # レコーダーの起動
            with speaker.recorder(samplerate=sample_rate) as recorder:
                while self._running:
                    # 録音データを取得 (num_frames分, 型はfloat32, 2chの場合はステレオ)
                    data = recorder.record(numframes=num_frames)
                    if data is None or len(data) == 0:
                        continue

                    # ステレオ(またはマルチチャンネル)の場合はモノラルに変換（平均を取る）
                    if data.ndim > 1 and data.shape[1] > 1:
                        mono_data = np.mean(data, axis=1)
                    else:
                        mono_data = data.flatten()

                    # float32のnumpy配列として保証
                    mono_data = mono_data.astype(np.float32)

                    # コールバック関数が指定されていれば呼び出す
                    if self.on_chunk is not None:
                        try:
                            self.on_chunk(mono_data)
                        except Exception as e:
                            print(f"[AudioCapturer Error] Exception in on_chunk callback: {e}")

        except Exception as e:
            print(f"[AudioCapturer Error] Exception in capture loop: {e}")
        finally:
            self._running = False
            print("[AudioCapturer] Recording stopped.")
