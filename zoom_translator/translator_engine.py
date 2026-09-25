import numpy as np
from typing import Tuple, Optional, Any
from config import Config, default_config

class TranslatorEngine:
    """
    faster-whisperによる音声認識とargos-translateによる翻訳を行うエンジンクラス。
    モデルや言語パッケージのロードは初回利用時に遅延初期化（Lazy Initialization）されます。
    """
    def __init__(self, config: Config = default_config):
        self.config = config
        self._whisper_model: Optional[Any] = None
        self._argos_initialized: bool = False

    def _load_whisper(self) -> None:
        """初回利用時にfaster-whisperのWhisperModelを遅延ロードする"""
        if self._whisper_model is None:
            from faster_whisper import WhisperModel
            self._whisper_model = WhisperModel(
                self.config.WHISPER_MODEL_SIZE,
                compute_type=self.config.WHISPER_COMPUTE_TYPE
            )

    def _ensure_argos_package(self) -> None:
        """初回利用時にargos-translateの翻訳パッケージを確認し、必要に応じてインストールする"""
        if not self._argos_initialized:
            import argostranslate.package
            import argostranslate.translate

            source_lang = self.config.SOURCE_LANG
            target_lang = self.config.TARGET_LANG

            installed_packages = argostranslate.package.get_installed_packages()
            package_found = any(
                p.from_code == source_lang and p.to_code == target_lang
                for p in installed_packages
            )

            if not package_found:
                argostranslate.package.update_package_index()
                available_packages = argostranslate.package.get_available_packages()
                target_package = next(
                    (p for p in available_packages if p.from_code == source_lang and p.to_code == target_lang),
                    None
                )
                if target_package:
                    download_path = target_package.download()
                    argostranslate.package.install_from_path(download_path)

            self._argos_initialized = True

    def transcribe(self, audio_np: np.ndarray) -> str:
        """
        numpy配列の音声データを入力として受け取り、
        faster-whisperで音声認識（文字起こし）を行い、認識結果テキストを返す。
        空または無音の場合は空文字を返す。

        Args:
            audio_np (np.ndarray): float32型、config.SAMPLE_RATEのモノラル音声配列

        Returns:
            str: 認識されたテキスト（無音・空の場合は空文字）
        """
        if audio_np is None or audio_np.size == 0:
            return ""

        if not np.any(audio_np):
            return ""

        self._load_whisper()

        segments, info = self._whisper_model.transcribe(
            audio_np,
            language=self.config.SOURCE_LANG,
            beam_size=self.config.BEAM_SIZE,
            condition_on_previous_text=self.config.WHISPER_CONDITION_ON_PREVIOUS_TEXT,
            vad_filter=self.config.WHISPER_VAD_FILTER
        )

        transcript_text = " ".join([segment.text.strip() for segment in segments]).strip()
        return transcript_text

    def translate(self, text: str) -> str:
        """
        与えられたテキストを config.SOURCE_LANG から config.TARGET_LANG へ
        argos-translate で翻訳して返す。
        空文字入力なら空文字を返す。翻訳失敗時は元のテキストをそのまま返す。

        Args:
            text (str): 翻訳対象のテキスト

        Returns:
            str: 翻訳されたテキスト（失敗時または空文字の場合はそのまま）
        """
        if not text:
            return ""

        try:
            self._ensure_argos_package()
        except Exception:
            pass

        try:
            import argostranslate.translate
            translated_text = argostranslate.translate.translate(
                text,
                self.config.SOURCE_LANG,
                self.config.TARGET_LANG
            )
            return translated_text
        except Exception:
            return text
