import os
import json
from config import Config

# 設定ファイルを保存するパス（実行ディレクトリ基準の settings.json）
SETTINGS_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


def save_settings(config: Config) -> None:
    """Configオブジェクトから SOURCE_LANG, TARGET_LANG, SPEAKER_DEVICE_NAME の3つの値を

    抽出し、SETTINGS_FILE_PATH に JSON形式で保存する。
    書き込みに失敗した場合は例外を握りつぶし、ログ出力のみ行って呼び出し元をクラッシュさせない。
    """
    try:
        data = {
            "source_lang": config.SOURCE_LANG,
            "target_lang": config.TARGET_LANG,
            "speaker_device_name": config.SPEAKER_DEVICE_NAME,
        }
        with open(SETTINGS_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Warning] 設定ファイルの保存に失敗しました: {e}")


def load_settings(config: Config) -> None:
    """SETTINGS_FILE_PATH が存在する場合にJSONを読み込み、

    含まれるキー (source_lang, target_lang, speaker_device_name) があれば
    渡された config インスタンスのフィールド (SOURCE_LANG, TARGET_LANG, SPEAKER_DEVICE_NAME) に直接代入する。
    ファイルが存在しない場合や読み込み・パースに失敗した場合は何もせず静かに終了する。
    """
    try:
        if not os.path.exists(SETTINGS_FILE_PATH):
            return

        with open(SETTINGS_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return

        if "source_lang" in data:
            config.SOURCE_LANG = data["source_lang"]
        if "target_lang" in data:
            config.TARGET_LANG = data["target_lang"]
        if "speaker_device_name" in data:
            config.SPEAKER_DEVICE_NAME = data["speaker_device_name"]

    except Exception as e:
        print(f"[Warning] 設定ファイルの読み込みに失敗しました: {e}")
