"""Tests for the persisted company list backing the work-field combobox
(storage.load_companies/save_companies) -- and the settings-merge fix that
save_companies depends on (must not clobber sibling keys like "language")."""

import unittest
from unittest.mock import patch

from timermeet_app import storage


class LoadCompaniesTests(unittest.TestCase):
    def test_missing_key_returns_empty_list(self):
        with patch.object(storage, "load_settings", return_value={}):
            self.assertEqual(storage.load_companies(), [])

    def test_non_list_value_returns_empty_list(self):
        with patch.object(storage, "load_settings", return_value={"companies": "not-a-list"}):
            self.assertEqual(storage.load_companies(), [])

    def test_trims_whitespace_and_drops_blank_or_non_string_entries(self):
        raw = {"companies": ["  Acme  ", "", "   ", 42, None, "Beta"]}
        with patch.object(storage, "load_settings", return_value=raw):
            self.assertEqual(storage.load_companies(), ["Acme", "Beta"])

    def test_dedupes_case_insensitively_keeping_the_first_spelling_seen(self):
        raw = {"companies": ["Acme", "ACME", "acme", "Beta"]}
        with patch.object(storage, "load_settings", return_value=raw):
            self.assertEqual(storage.load_companies(), ["Acme", "Beta"])


class SaveCompaniesTests(unittest.TestCase):
    def test_merges_into_existing_settings_without_dropping_other_keys(self):
        existing = {"language": "en"}
        with patch.object(storage, "load_settings", return_value=existing):
            with patch.object(storage, "save_settings") as mock_save:
                storage.save_companies(["Acme", "Beta"])
                mock_save.assert_called_once_with({"language": "en", "companies": ["Acme", "Beta"]})

    def test_overwrites_a_previous_companies_list(self):
        existing = {"companies": ["Old"]}
        with patch.object(storage, "load_settings", return_value=existing):
            with patch.object(storage, "save_settings") as mock_save:
                storage.save_companies(["New"])
                mock_save.assert_called_once_with({"companies": ["New"]})


if __name__ == "__main__":
    unittest.main()
