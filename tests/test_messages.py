"""ユーザ向けメッセージテンプレートの退行テスト。"""

import unittest

import messages


class MessageCatalogTests(unittest.TestCase):
    """英語既定・日本語差し替えのメッセージ規則を確認する。"""

    def test_japanese_catalog_has_all_default_keys(self):
        """英語既定辞書にあるキーは日本語辞書にも用意する。"""
        self.assertEqual(messages.missing_translation_keys("ja"), [])

    def test_unknown_locale_falls_back_to_english(self):
        """未対応localeは英語メッセージへフォールバックする。"""
        text = messages.message_text("video_required", "fr")
        self.assertEqual(text, messages.MESSAGES["en"]["video_required"])

    def test_japanese_locale_variants_are_supported(self):
        """ja_JPやja-JP指定でも日本語テンプレートを選ぶ。"""
        text = messages.message_text("video_required", "ja_JP")
        self.assertEqual(text, messages.MESSAGES["ja"]["video_required"])

    def test_template_parameters_are_formatted(self):
        """テンプレート変数が指定された場合はformatされる。"""
        text = messages.message_text("calibration_fov_set", "en", fov=90.0)
        self.assertIn("90.0", text)

    def test_missing_template_parameter_does_not_crash(self):
        """テンプレート変数不足でUI表示自体を壊さない。"""
        text = messages.message_text("calibration_fov_set", "en")
        self.assertIn("{fov}", text)

    def test_unknown_key_returns_key_name(self):
        """未知キーはキー名を返し、呼び出し側の例外にしない。"""
        self.assertEqual(messages.message_text("unknown_message_key", "en"), "unknown_message_key")


if __name__ == "__main__":
    unittest.main()
