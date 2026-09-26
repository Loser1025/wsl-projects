import pytest
from translator_engine import TranslatorEngine, _ISO_TO_FLORES
from config import Config

def test_iso_to_flores_mapping():
    assert _ISO_TO_FLORES["ja"] == "jpn_Jpan"
    assert _ISO_TO_FLORES["ko"] == "kor_Hang"
    assert _ISO_TO_FLORES["en"] == "eng_Latn"
    assert _ISO_TO_FLORES["zh"] == "zho_Hans"

def test_translator_engine_init():
    config = Config()
    engine = TranslatorEngine(config)
    assert engine._nllb_translator is None
    assert engine._nllb_tokenizer is None
    assert engine._nllb_load_failed is False

def test_translate_empty_string():
    config = Config()
    engine = TranslatorEngine(config)
    assert engine.translate("") == ""

def test_nllb_fallback_to_argos_on_load_failure(monkeypatch):
    config = Config()
    config.TRANSLATION_ENGINE = "nllb"
    engine = TranslatorEngine(config)

    # _load_nllbをモックして例外を発生させる（モデルロード失敗を模擬）
    def mock_load_nllb(self):
        self._nllb_load_failed = True
        raise RuntimeError("Mock load failure")

    monkeypatch.setattr(TranslatorEngine, "_load_nllb", mock_load_nllb)

    # _translate_via_argosをモックして成功を返すようにする
    called_argos = []
    def mock_translate_via_argos(self, text):
        called_argos.append(text)
        return "argos_translated_" + text

    monkeypatch.setattr(TranslatorEngine, "_translate_via_argos", mock_translate_via_argos)

    result = engine.translate("こんにちは")
    assert result == "argos_translated_こんにちは"
    assert engine._nllb_load_failed is True
    assert "こんにちは" in called_argos
