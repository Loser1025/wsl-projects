from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Zoomなどのシステム音声をリアルタイム翻訳字幕表示するデスクトップアプリの設定を保持するデータクラス"""

    # argos-translate用の言語コード（例: 'en', 'ja'）
    SOURCE_LANG: str = "ja"
    TARGET_LANG: str = "ko"

    # スピーカーデバイス名（Noneの場合はデフォルト出力デバイスを使用）
    SPEAKER_DEVICE_NAME: Optional[str] = None

    # 音声サンプリングレート（Hz）
    SAMPLE_RATE: int = 16000

    # 音声チャンクの継続時間（秒）
    CHUNK_DURATION_SEC: float = 4.0

    # Whisperモデルサイズ（例: 'tiny', 'base', 'small', 'medium', 'large-v3'）
    # 実測でmedium+beam5は8秒の音声認識に11〜19秒かかり実時間に追いつかなかったため、
    # 速度優先でsmallに変更する（実時間より遅いと待ち行列が無限に伸び続けるため精度より優先度が高い）
    WHISPER_MODEL_SIZE: str = "small"

    # Whisperの演算データ型（例: 'int8', 'float16', 'float32'）
    WHISPER_COMPUTE_TYPE: str = "int8"

    # ビームサーチの探索幅（大きいほど精度が上がるが処理が遅くなる）。速度優先で1(貪欲探索)に抑える
    BEAM_SIZE: int = 1

    # VADで切り出した短い音声チャンクで前チャンクの文脈を引きずりハルシネーション（存在しない文の混入）が起きるのを防ぐためFalseにする
    WHISPER_CONDITION_ON_PREVIOUS_TEXT: bool = False

    # faster-whisper内蔵のVADフィルタで無音区間の誤認識を抑制する。
    # audio_capturer.py側で既にVAD区切り済みのためデフォルトはFalse(二重VADの無駄な処理時間を省く)
    WHISPER_VAD_FILTER: bool = False

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

    # --- VAD（音声区切り検出）関連設定 ---
    # webrtcvadの0-3感度（数値が大きいほど非音声と判定しやすくなる）
    VAD_AGGRESSIVENESS: int = 2
    # webrtcvadが要求するフレーム長ミリ秒（10, 20, 30のいずれか）
    VAD_FRAME_MS: int = 30
    # 無音がこのミリ秒以上続いたら発話区切りとみなす
    VAD_SILENCE_MS: int = 500
    # 無音が来なくても強制的にチャンクを区切る上限秒数
    MAX_SEGMENT_SEC: float = 8.0
    # これより短い音声はノイズとして破棄する秒数
    MIN_SEGMENT_SEC: float = 0.5

    # --- 文単位バッファリング関連設定 ---
    # 文末とみなす記号文字列（日本語の全角句読点も含める。SOURCE_LANGが日本語の場合、
    # Whisperの認識結果は「。」「！」「？」で終わることが多く、半角記号だけだと
    # 文単位バッファリングが文の完成を検出できなくなるため）
    SENTENCE_END_CHARS: str = ".?!。！？"
    # 句読点が来なくても強制的に翻訳に回す最大待ち秒数
    SENTENCE_MAX_WAIT_SEC: float = 6.0

    # --- GUI関連設定 ---
    # GUIウィンドウの幅（px）
    GUI_WINDOW_WIDTH: int = 900
    # GUIウィンドウの高さ（px）
    GUI_WINDOW_HEIGHT: int = 180
    # 画面下端からの余白（px）
    GUI_BOTTOM_MARGIN: int = 60


# モジュールレベルのデフォルト設定インスタンス
default_config = Config()
