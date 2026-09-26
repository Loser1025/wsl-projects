import time
from typing import Optional
from config import Config, default_config


class SentenceBuffer:
    """音声認識で断片的に得られるテキストを、句読点またはタイムアウトまでバッファリングし、
    まとまった1文として取り出すためのクラス。
    """

    def __init__(self, config: Config = default_config) -> None:
        """SentenceBufferを初期化する。

        Args:
            config (Config): 設定オブジェクト（SENTENCE_END_CHARS, SENTENCE_MAX_WAIT_SECを使用）
        """
        self.config = config
        self._buffer: str = ""
        self._first_added_time: Optional[float] = None

    def add_fragment(self, text: str) -> Optional[str]:
        """新しいテキスト断片をバッファに追加する。

        テキストが空文字の場合は何もせずNoneを返す。
        テキストを追加した際、初回追加時刻が未設定であれば現在の time.monotonic() を記録する。
        その後、以下のいずれかの条件を満たした場合、バッファ内容（前後の空白を除去したもの）を返して
        バッファと時刻をリセットする。
          - バッファの末尾が config.SENTENCE_END_CHARS に含まれる文字で終わっている場合
          - time.monotonic() - 初回追加時刻 が config.SENTENCE_MAX_WAIT_SEC を超えた場合

        条件を満たさない場合は None を返す（まだ文が完成していない）。

        Args:
            text (str): 音声認識等で得られたテキスト断片

        Returns:
            Optional[str]: 完成した文、または条件を満たさない場合はNone
        """
        if not text:
            return None

        cleaned_text = text.strip()
        if not cleaned_text:
            return None

        current_time = time.monotonic()

        # もし既にバッファに内容があり、初回追加からの経過時間がタイムアウトを超えている場合、
        # 新しいテキストを追加する前に、既存のバッファをフラッシュしてリセットする。
        if self._buffer and self._first_added_time is not None:
            if current_time - self._first_added_time >= self.config.SENTENCE_MAX_WAIT_SEC:
                flushed = self._buffer.strip()
                # バッファと時刻をリセットし、今回の新しいテキストを新しい初回として受け入れる
                self._buffer = cleaned_text
                self._first_added_time = current_time
                return flushed

        # 初回追加時刻の記録
        if self._first_added_time is None:
            self._first_added_time = current_time

        # バッファに既存内容があれば半角スペース区切りで追加、なければそのまま設定
        if self._buffer:
            self._buffer = f"{self._buffer} {cleaned_text}"
        else:
            self._buffer = cleaned_text

        # 判定：末尾が文末記号で終わっているか、またはタイムアウト時間を超えているか
        ends_with_punctuation = (
            len(self._buffer) > 0 and self._buffer[-1] in self.config.SENTENCE_END_CHARS
        )
        elapsed_time = current_time - self._first_added_time
        exceeds_timeout = elapsed_time >= self.config.SENTENCE_MAX_WAIT_SEC

        if ends_with_punctuation or exceeds_timeout:
            sentence = self._buffer.strip()
            # リセット
            self._buffer = ""
            self._first_added_time = None
            return sentence

        return None

    def flush(self) -> Optional[str]:
        """アプリケーション終了時などに、未完成の断片を強制的に出力するためのメソッド。

        バッファが空でなければ現在の内容（前後の空白を除去したもの）を返してリセットし、
        空ならNoneを返す。

        Returns:
            Optional[str]: バッファに残っていたテキスト断片、または空ならNone
        """
        if not self._buffer:
            return None

        sentence = self._buffer.strip()
        self._buffer = ""
        self._first_added_time = None
        return sentence if sentence else None

    def peek(self) -> Optional[str]:
        """文がまだ完成していない間の暫定表示用に、蓄積中のテキストを覗き見するためのメソッド。

        現在self._bufferに蓄積されている内容を、前後の空白を除去した上で返す。
        内部状態は一切変更せず、リセットもしない、副作用なしの読み取り専用メソッド。
        バッファが空文字列の場合はNoneを返す。

        Returns:
            Optional[str]: 蓄積中のテキスト断片（空白除去済み）、または空ならNone
        """
        if not self._buffer:
            return None
        sentence = self._buffer.strip()
        return sentence if sentence else None
