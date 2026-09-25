import time
import pytest
from config import Config
from sentence_buffer import SentenceBuffer


def test_sentence_buffer_basic():
    config = Config(SENTENCE_END_CHARS=".?!", SENTENCE_MAX_WAIT_SEC=1.0)
    buf = SentenceBuffer(config)

    # 1. 空文字の追加 -> None
    assert buf.add_fragment("") is None
    assert buf.add_fragment("   ") is None

    # 2. 途中経過（文末記号なし、タイムアウト前） -> None
    assert buf.add_fragment("Hello") is None
    assert buf.add_fragment("world") is None

    # 3. 文末記号付きの追加 -> 完成した文を返す
    res = buf.add_fragment("today.")
    assert res == "Hello world today."
    assert buf._buffer == ""
    assert buf._first_added_time is None


def test_sentence_buffer_timeout():
    config = Config(SENTENCE_END_CHARS=".?!", SENTENCE_MAX_WAIT_SEC=0.1)
    buf = SentenceBuffer(config)

    assert buf.add_fragment("Hello") is None
    # タイムアウト待ち
    time.sleep(0.15)

    # 次の追加時にタイムアウト超過のため、前回分("Hello")がフラッシュされ、
    # 今回の分("world")が新しくバッファに保持される
    res = buf.add_fragment("world")
    assert res == "Hello"
    assert buf._buffer == "world"

    # クリーンアップ
    buf.flush()


def test_flush():
    config = Config()
    buf = SentenceBuffer(config)

    assert buf.flush() is None

    buf.add_fragment("Incomplete sentence")
    assert buf.flush() == "Incomplete sentence"
    assert buf.flush() is None
