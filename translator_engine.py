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

    def transcribe_and_translate(self, audio_np: np.ndarray) -> Tuple[str, str]:
        """
        numpy配列の音声データを入力として受け取り、
        faster-whisperで音声認識（文字起こし）を行い、
        argos-translateでターゲット言語へ翻訳して (認識テキスト, 翻訳テキスト) を返す。

        Args:
            audio_np (np.ndarray): float32型、config.SAMPLE_RATEのモノラル音声配列

        Returns:
            Tuple[str, str]: (認識結果テキスト, 翻訳結果テキスト)
        """
        if audio_np is None or audio_np.size == 0:
            return ("", "")

        if not np.any(audio_np):
            return ("", "")

        self._load_whisper()

        try:
            self._ensure_argos_package()
        except Exception:
            pass

        segments, info = self._whisper_model.transcribe(
            audio_np,
            language=self.config.SOURCE_LANG,
            beam_size=5
        )

        transcript_text = " ".join([segment.text.strip() for segment in segments]).strip()

        if not transcript_text:
            return ("", "")

        translated_text = transcript_text
        try:
            import argostranslate.translate
            translated_text = argostranslate.translate.translate(
                transcript_text,
                self.config.SOURCE_LANG,
                self.config.TARGET_LANG
            )
        except Exception:
            translated_text = transcript_text

        return (transcript_text, translated_text)
