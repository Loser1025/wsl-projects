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
        # (source_lang, target_lang)のペアごとにargosパッケージ準備済みかを追跡する。
        # マイク用(ja->ko)・スピーカー用(ko->ja)など複数方向を1つのTranslatorEngineで
        # 共有(Whisper/NLLBを2重ロードしないため)扱えるようにするため、単一boolではなくsetにする。
        self._argos_initialized_pairs: set = set()
        self._nllb_translator: Optional[Any] = None
        self._nllb_tokenizer: Optional[Any] = None
        self._nllb_load_failed: bool = False

    def warmup(self) -> None:
        """
        アプリ起動時にまとめて呼び出し、Whisper・NLLB-200・argos-translate(フォールバック用)を
        すべて事前にロードしておくためのメソッド。これにより、実際の音声処理中に初回ロードの
        待ち時間(数秒〜数十秒)が発生してキュー詰まりを起こすのを防ぐ。
        各ロードは個別にtry/exceptで保護し、一部が失敗しても他の準備を続行する。
        """
        try:
            self._load_whisper()
            logger.info("Whisperモデルの事前ロードが完了しました。")
        except Exception as e:
            logger.error(f"Whisperモデルの事前ロードに失敗しました: {e}")

        if getattr(self.config, "TRANSLATION_ENGINE", "argos") == "nllb":
            try:
                self._load_nllb()
                logger.info("NLLB-200モデルの事前ロードが完了しました。")
            except Exception as e:
                logger.warning(f"NLLB-200モデルの事前ロードに失敗しました(argos-translateへフォールバックします): {e}")

        # NLLBが失敗した場合の実行時フォールバック用に、argos-translateも事前に準備しておく。
        # マイク用(例: ja->ko)・スピーカー用(例: ko->ja)の両方向を、設定にあれば両方とも準備する
        # (どちらか一方しか使わない場合でも重複ペアはsetで自然にまとめられる)。
        mic_src = getattr(self.config, "MIC_SOURCE_LANG", self.config.SOURCE_LANG)
        mic_tgt = getattr(self.config, "MIC_TARGET_LANG", self.config.TARGET_LANG)
        speaker_src = getattr(self.config, "SPEAKER_SOURCE_LANG", self.config.SOURCE_LANG)
        speaker_tgt = getattr(self.config, "SPEAKER_TARGET_LANG", self.config.TARGET_LANG)
        for src, tgt in {(mic_src, mic_tgt), (speaker_src, speaker_tgt)}:
            try:
                self._ensure_argos_package(src, tgt)
                logger.info(f"argos-translateパッケージの事前準備が完了しました({src}->{tgt})。")
            except Exception as e:
                logger.warning(f"argos-translateパッケージの事前準備に失敗しました({src}->{tgt}): {e}")

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
                import ctranslate2
                from transformers import AutoTokenizer
                from huggingface_hub import snapshot_download

                # ctranslate2形式のモデルディレクトリをHuggingFace Hubからダウンロード(2回目以降はキャッシュ利用)
                logger.info("Downloading/locating NLLB-200 ctranslate2 model: %s", self.config.NLLB_MODEL_REPO)
                model_dir = snapshot_download(self.config.NLLB_MODEL_REPO)

                logger.info("Loading NLLB-200 ctranslate2 translator (compute_type=%s)", self.config.NLLB_COMPUTE_TYPE)
                self._nllb_translator = ctranslate2.Translator(
                    model_dir, device="cpu", compute_type=self.config.NLLB_COMPUTE_TYPE
                )

                logger.info("Loading NLLB-200 tokenizer from %s", self.config.NLLB_TOKENIZER_REPO)
                self._nllb_tokenizer = AutoTokenizer.from_pretrained(self.config.NLLB_TOKENIZER_REPO)
            except Exception as e:
                self._nllb_load_failed = True
                logger.warning("Failed to load NLLB-200 model/tokenizer: %s. Falling back to argos-translate.", e)
                raise

    def _ensure_argos_package(self, source_lang: Optional[str] = None, target_lang: Optional[str] = None) -> None:
        """
        指定された言語ペア(省略時はself.config.SOURCE_LANG/TARGET_LANG)について、
        argos-translateの翻訳パッケージを確認し、必要に応じてインストールする。
        ペアごとに準備済みかを_argos_initialized_pairsで管理し、二重処理を避ける。
        """
        source_lang = source_lang or self.config.SOURCE_LANG
        target_lang = target_lang or self.config.TARGET_LANG
        pair = (source_lang, target_lang)

        if pair not in self._argos_initialized_pairs:
            import argostranslate.package
            import argostranslate.translate

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

            self._argos_initialized_pairs.add(pair)

    def transcribe(self, audio_np: np.ndarray, language: Optional[str] = None) -> str:
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
            language=language or self.config.SOURCE_LANG,
            beam_size=self.config.BEAM_SIZE,
            condition_on_previous_text=self.config.WHISPER_CONDITION_ON_PREVIOUS_TEXT,
            vad_filter=self.config.WHISPER_VAD_FILTER
        )

        transcript_text = " ".join([segment.text.strip() for segment in segments]).strip()
        return transcript_text

    def _translate_via_nllb(self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None) -> str:
        """
        NLLB-200を使用してテキストを翻訳する。
        _load_nllb()を呼び出し、ISOコードをFLORES-200コードに変換して翻訳を実行する。
        source_lang/target_langを指定すればself.config.SOURCE_LANG/TARGET_LANGを上書きできる
        (1つのTranslatorEngineでマイク用/スピーカー用など複数方向を共有するため)。
        """
        self._load_nllb()
        if self._nllb_translator is None:
            raise RuntimeError("NLLB-200 translator is not initialized.")

        src_lang = source_lang or self.config.SOURCE_LANG
        tgt_lang = target_lang or self.config.TARGET_LANG

        if src_lang not in _ISO_TO_FLORES:
            raise ValueError(f"Source language '{src_lang}' is not supported in _ISO_TO_FLORES.")
        if tgt_lang not in _ISO_TO_FLORES:
            raise ValueError(f"Target language '{tgt_lang}' is not supported in _ISO_TO_FLORES.")

        flores_src = _ISO_TO_FLORES[src_lang]
        flores_tgt = _ISO_TO_FLORES[tgt_lang]

        # NLLBのトークナイザーはsrc_langをエンコード前に設定する必要がある
        # (言語切り替えUIで実行時にSOURCE_LANGが変わるケースに対応するため毎回設定し直す)
        self._nllb_tokenizer.src_lang = flores_src

        source_tokens = self._nllb_tokenizer.convert_ids_to_tokens(self._nllb_tokenizer.encode(text))
        results = self._nllb_translator.translate_batch(
            [source_tokens], target_prefix=[[flores_tgt]]
        )
        # 出力の先頭トークンはtarget_prefixで指定した言語トークンなので除いてデコードする
        target_tokens = results[0].hypotheses[0][1:]
        translated_text = self._nllb_tokenizer.decode(
            self._nllb_tokenizer.convert_tokens_to_ids(target_tokens)
        )
        return translated_text.strip()

    def _translate_via_argos(self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None) -> str:
        """
        既存のargos-translateによる翻訳ロジック（温存されたフォールバック経路）。
        source_lang/target_langを指定すればself.config.SOURCE_LANG/TARGET_LANGを上書きできる。
        """
        source_lang = source_lang or self.config.SOURCE_LANG
        target_lang = target_lang or self.config.TARGET_LANG

        try:
            self._ensure_argos_package(source_lang, target_lang)
        except Exception:
            pass

        try:
            import argostranslate.translate
            translated_text = argostranslate.translate.translate(
                text,
                source_lang,
                target_lang
            )
            return translated_text
        except Exception:
            return text

    def translate(self, text: str, source_lang: Optional[str] = None, target_lang: Optional[str] = None) -> str:
        """
        テキストを翻訳する。source_lang/target_langを指定すればself.config.SOURCE_LANG/TARGET_LANGを
        上書きできる(1つのTranslatorEngineでマイク用/スピーカー用など複数方向を共有するため)。
        TRANSLATION_ENGINE が "nllb" の場合はまず _translate_via_nllb(text) を試み、
        例外が発生した場合はログに warning を出力して _translate_via_argos(text) にフォールバックする。
        TRANSLATION_ENGINE が "nllb" 以外の場合は従来通り _translate_via_argos(text) を直接呼ぶ。
        """
        if not text:
            return ""

        engine = getattr(self.config, "TRANSLATION_ENGINE", "argos")

        if engine == "nllb":
            try:
                return self._translate_via_nllb(text, source_lang, target_lang)
            except Exception as e:
                logger.warning("NLLB translation failed (%s). Safely falling back to argos-translate.", e)
                return self._translate_via_argos(text, source_lang, target_lang)
        else:
            return self._translate_via_argos(text, source_lang, target_lang)
