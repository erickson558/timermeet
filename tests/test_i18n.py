"""Tests for the i18n dictionary -- the main risk here is the two language
tables silently drifting apart (a key present in one but not the other)."""

import unittest

from timermeet_app import i18n


class TranslationParityTests(unittest.TestCase):
    def test_es_and_en_define_exactly_the_same_keys(self):
        self.assertEqual(set(i18n.translations["es"].keys()), set(i18n.translations["en"].keys()))

    def test_no_empty_translation_values(self):
        for language, table in i18n.translations.items():
            for key, value in table.items():
                self.assertTrue(value.strip(), f"{language}.{key} is empty")

    def test_t_falls_back_to_default_language_then_to_the_key_itself(self):
        self.assertEqual(i18n.t("appTitle", "xx"), i18n.translations[i18n.DEFAULT_LANGUAGE]["appTitle"])
        self.assertEqual(i18n.t("this-key-does-not-exist", "es"), "this-key-does-not-exist")

    def test_format_text_substitutes_named_placeholders(self):
        text = i18n.format_text("repeatOccurrenceLabel", "en", index=2, total=5)
        self.assertEqual(text, "Event 2 of 5")


if __name__ == "__main__":
    unittest.main()
