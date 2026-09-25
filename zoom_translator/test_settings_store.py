import os
import unittest
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import Config
from settings_store import save_settings, load_settings, SETTINGS_FILE_PATH


class TestSettingsStore(unittest.TestCase):

    def setUp(self):
        # テストごとに設定ファイルを削除
        if os.path.exists(SETTINGS_FILE_PATH):
            os.remove(SETTINGS_FILE_PATH)

    def tearDown(self):
        if os.path.exists(SETTINGS_FILE_PATH):
            os.remove(SETTINGS_FILE_PATH)

    def test_save_and_load(self):
        config = Config(
            SOURCE_LANG="en",
            TARGET_LANG="ja",
            SPEAKER_DEVICE_NAME="Virtual Audio Cable",
        )
        save_settings(config)

        self.assertTrue(os.path.exists(SETTINGS_FILE_PATH))

        loaded_config = Config()
        load_settings(loaded_config)

        self.assertEqual(loaded_config.SOURCE_LANG, "en")
        self.assertEqual(loaded_config.TARGET_LANG, "ja")
        self.assertEqual(loaded_config.SPEAKER_DEVICE_NAME, "Virtual Audio Cable")

    def test_load_nonexistent(self):
        # ファイルが存在しない場合の挙動確認（例外を投げないこと）
        config = Config()
        load_settings(config)
        # デフォルト値が維持されること
        self.assertEqual(config.SOURCE_LANG, "ja")


if __name__ == "__main__":
    unittest.main()
