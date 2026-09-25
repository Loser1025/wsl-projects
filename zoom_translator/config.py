from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Zoomなどのシステム音声をリアルタイム翻訳字幕表示するデスクトップアプリの設定を保持するデータクラス"""

    # argos-translate用の言語コード（例: 'en', 'ja'）
    SOURCE_LANG: str = "en"
    TARGET_LANG: str = "ja"

    # スピーカーデバイス名（Noneの場合はデフォルト出力デバイスを使用）
    SPEAKER_DEVICE_NAME: Optional[str] = None

    # 音声サンプリングレート（Hz）
    SAMPLE_RATE: int = 16000

    # 音声チャンクの継続時間（秒）
    CHUNK_DURATION_SEC: float = 4.0

    # Whisperモデルサイズ（例: 'tiny', 'base', 'small', 'medium', 'large'）
    WHISPER_MODEL_SIZE: str = "small"

    # Whisperの演算データ型（例: 'int8', 'float16', 'float32'）
    WHISPER_COMPUTE_TYPE: str = "int8"

    # 字幕フォントファミリー
    SUBTITLE_FONT_FAMILY: str = "Arial"

    # 字幕フォントサイズ
    SUBTITLE_FONT_SIZE: int = 16

    # 字幕背景カラー（透過キー用）
    SUBTITLE_BG_COLOR: str = "#000000"

    # 字幕文字カラー
    SUBTITLE_FG_COLOR: str = "#FFFFFF"

    # ウィンドウの透明度（0.0〜1.0）
    WINDOW_ALPHA: float = 0.8


# モジュールレベルのデフォルト設定インスタンス
default_config = Config()
