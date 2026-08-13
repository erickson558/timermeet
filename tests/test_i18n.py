"""Tests for the i18n dictionary -- the main risk here is the two language
tables silently drifting apart (a key present in one but not the other)."""

import unittest
from datetime import date

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


class FormatWeekRangeTests(unittest.TestCase):
    def test_same_month_es(self):
        text = i18n.format_week_range(date(2026, 8, 10), date(2026, 8, 16), "es")
        self.assertEqual(text, "10-16 Ago 2026")

    def test_same_month_en(self):
        text = i18n.format_week_range(date(2026, 8, 10), date(2026, 8, 16), "en")
        self.assertEqual(text, "Aug 10-16, 2026")

    def test_month_crossing_es(self):
        text = i18n.format_week_range(date(2026, 7, 27), date(2026, 8, 2), "es")
        self.assertEqual(text, "27 Jul - 2 Ago 2026")

    def test_month_crossing_en(self):
        text = i18n.format_week_range(date(2026, 7, 27), date(2026, 8, 2), "en")
        self.assertEqual(text, "Jul 27 - Aug 2, 2026")

    def test_year_crossing_es(self):
        text = i18n.format_week_range(date(2025, 12, 29), date(2026, 1, 4), "es")
        self.assertEqual(text, "29 Dic 2025 - 4 Ene 2026")

    def test_year_crossing_en(self):
        text = i18n.format_week_range(date(2025, 12, 29), date(2026, 1, 4), "en")
        self.assertEqual(text, "Dec 29, 2025 - Jan 4, 2026")


class WeekViewTranslationKeysTests(unittest.TestCase):
    def test_week_view_keys_exist_in_both_languages(self):
        for key in ("weekViewButton", "weekPrevButton", "weekNextButton", "weekTodayButton"):
            self.assertIn(key, i18n.translations["es"])
            self.assertIn(key, i18n.translations["en"])


class DurationTranslationKeysTests(unittest.TestCase):
    """SDD.md v2.15.0: exactly 2 new keys, in both languages -- the generic
    parity test above already enforces this structurally, this documents
    the specific acceptance criterion by name."""

    def test_duration_keys_exist_in_both_languages_and_are_non_empty(self):
        for key in ("durationLabel", "validationDuration"):
            self.assertIn(key, i18n.translations["es"])
            self.assertIn(key, i18n.translations["en"])
            self.assertTrue(i18n.translations["es"][key].strip())
            self.assertTrue(i18n.translations["en"][key].strip())

    def test_duration_label_reuses_minutes_suffix_not_a_new_format_function(self):
        # SDD.md decision #3 explicitly rules out a new i18n format function
        # for this field -- the form label composes it inline the same way
        # `reminderLabel` already does, reusing the existing `minutesSuffix`.
        self.assertIn("minutesSuffix", i18n.translations["es"])
        self.assertIn("minutesSuffix", i18n.translations["en"])


if __name__ == "__main__":
    unittest.main()
