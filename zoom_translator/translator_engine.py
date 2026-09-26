import numpy as np
import logging
from typing import Tuple, Optional, Any
from config import Config, default_config

logger = logging.getLogger(__name__)

# モジュールレベルに、ISO 639-1相当の2文字言語コードからNLLB-200が使用するFLORES-200言語コードへのマッピング辞書を定義
_ISO_TO_FLORES = {
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "en": "eng_Latn",
    "zh": "zho_Hans",
}

class TranslatorEngine:
    """
    faster-whisperによる音声認識と、NLLB-200(ctranslate2)またはargos-translateによる翻訳を行うエンジンクラス。
    モデルや言語パッケージのロードは初回利用時に遅延初期化（Lazy Initialization）されます。
    """
    def __init__(self, config: Config = default_config):
        self.config = config
        self._whisper_model: Optional[Any] = None
        self._argos_initialized: bool = False
        self._nllb_translator: Optional[Any] = None
        self._nllb_tokenizer: Optional[Any] = None
        self._nllb_load_failed: bool = False

    def _load_whisper(self) -> None:
        """初回利用時にfaster-whisperのWhisperModelを遅延ロードする"""
        if self._whisper_model is None:
            from faster_whisper import WhisperModel
            self._whisper_model = WhisperModel(
                self.config.WHISPER_MODEL_SIZE,
                compute_type=self.config.WHISPER_COMPUTE_TYPE
            )

    def _load_nllb(self) -> None:
        """
        NLLB-200モデルおよびトークナイザーを遅延ロードする。
        self._nllb_translator is None かつ self._nllb_load_failed が False の場合のみロードを試みる。
        一度失敗した場合は _nllb_load_failed = True を設定し、以降のリトライを防ぐとともに
        argos-translate へのフォールバック経路へ安全に移行する。
        """
        if self._nllb_translator is None and not self._nllb_load_failed:
            try:
                from transformers import AutoTokenizer
                from hf_hub_ctranslate2 import TranslatorCT2fromHfHub

                logger.info("Loading NLLB-200 tokenizer from %s", self.config.NLLB_TOKENIZER_REPO)
                self._nllb_tokenizer = AutoTokenizer.from_pretrained(self.config.NLLB_TOKENIZER_REPO)

                logger.info("Loading NLLB-200 translator from %s (compute_type=%s)", 
                            self.config.NLLB_MODEL_REPO, self.config.NLLB_COMPUTE_TYPE)
                self._nllb_translator = TranslatorCT2fromHfHub(
                    model_name_or_path=self.config.NLLB_MODEL_REPO,
                    device="cpu",
                    compute_type=self.config.NLLB_COMPUTE_TYPE,
                    tokenizer=self._nllb_tokenizer
                )
            except Exception as e:
                self._nllb_load_failed = True
                logger.warning("Failed to load NLLB-200 model/tokenizer: %s. Falling back to argos-translate.", e)
                raise

    def _ensure_argos_package(self) -> None:
        """初回利用時にargos-translateの翻訳パッケージを確認し、必要に応じてインストールする"""
        if not self._argos_initialized:
            import argostranslate.package
            import argostranslate.translate

            source_lang = self.config.SOURCE_LANG
            target_lang = self.config.TARGET_LANG

            # ステップ1: 直接の言語ペアパッケージ（例: source_lang -> target_lang）がインストール済みか確認し、なければインストールする
            try:
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
            except Exception:
                pass

            # ステップ2: 英語経由のピボット翻訳確認・インストール
            if source_lang != "en" or target_lang != "en":
                if source_lang != "en":
                    try:
                        installed_packages = argostranslate.package.get_installed_packages()
                        src_en_found = any(
                            p.from_code == source_lang and p.to_code == "en"
                            for p in installed_packages
                        )
                        if not src_en_found:
                            available_packages = argostranslate.package.get_available_packages()
                            src_en_pkg = next(
                                (p for p in available_packages if p.from_code == source_lang and p.to_code == "en"),
                                None
                            )
                            if src_en_pkg:
                                download_path = src_en_pkg.download()
                                argostranslate.package.install_from_path(download_path)
                    except Exception:
                        pass

                if target_lang != "en":
                    try:
                        installed_packages = argostranslate.package.get_installed_packages()
                        en_tgt_found = any(
                            p.from_code == "en" and p.to_code == target_lang
                            for p in installed_packages
                        )
                        if not en_tgt_found:
                            available_packages = argostranslate.package.get_available_packages()
                            en_tgt_pkg = next(
                                (p for p in available_packages if p.from_code == "en" and p.to_code == target_lang),
                                None
                            )
                            if en_tgt_pkg:
                                download_path = en_tgt_pkg.download()
                                argostranslate.package.install_from_path(download_path)
                    except Exception:
                        pass

            self._argos_initialized = True

    def transcribe(self, audio_np: np.ndarray) -> str:
        """
        numpy配列の音声データを入力として受け取り、
        faster-whisperで音声認識（文字起こし）を行い、認識結果テキストを返す。
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

    def _translate_via_nllb(self, text: str) -> str:
        """
        NLLB-200を使用してテキストを翻訳する。
        _load_nllb()を呼び出し、ISOコードをFLORES-200コードに変換して翻訳を実行する。
        """
        self._load_nllb()
        if self._nllb_translator is None:
            raise RuntimeError("NLLB-200 translator is not initialized.")

        src_lang = self.config.SOURCE_LANG
        tgt_lang = self.config.TARGET_LANG

        if src_lang not in _ISO_TO_FLORES:
            raise ValueError(f"Source language '{src_lang}' is not supported in _ISO_TO_FLORES.")
        if tgt_lang not in _ISO_TO_FLORES:
            raise ValueError(f"Target language '{tgt_lang}' is not supported in _ISO_TO_FLORES.")

        flores_src = _ISO_TO_FLORES[src_lang]
        flores_tgt = _ISO_TO_FLORES[tgt_lang]

        output = self._nllb_translator.generate(
            text=[text],
            src_lang=[flores_src],
            tgt_lang=[flores_tgt]
        )

        # 戻り値の構造（リストや文字列など）に対して防御的に処理して文字列を取り出す
        if isinstance(output, list):
            if len(output) > 0:
                item = output[0]
                if isinstance(item, list) and len(item) > 0:
                    return str(item[0])
                elif isinstance(item, str):
                    return str(item)
                else:
                    return str(item)
            return ""
        elif isinstance(output, str):
            return output
        else:
            return str(output)

    def _translate_via_argos(self, text: str) -> str:
        """
        既存のargos-translateによる翻訳ロジック（温存されたフォールバック経路）。
        """
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

    def translate(self, text: str) -> str:
        """
        テキストを翻訳する。
        TRANSLATION_ENGINE が "nllb" の場合はまず _translate_via_nllb(text) を試み、
        例外が発生した場合はログに warning を出力して _translate_via_argos(text) にフォールバックする。
        TRANSLATION_ENGINE が "nllb" 以外の場合は従来通り _translate_via_argos(text) を直接呼ぶ。
        """
        if not text:
            return ""

        engine = getattr(self.config, "TRANSLATION_ENGINE", "argos")

        if engine == "nllb":
            try:
                return self._translate_via_nllb(text)
            except Exception as e:
                logger.warning("NLLB translation failed (%s). Safely falling back to argos-translate.", e)
                return self._translate_via_argos(text)
        else:
            return self._translate_via_argos(text)
