"""Tests for small pure-function helpers in app.py that don't need a live
Tkinter root -- currently just the gadget-position settings coercion (a real
crash-on-corrupted-settings.json bug found during review of the gadget/skin
mode feature, see SDD.md)."""

import unittest

from timermeet_app.app import _coerce_gadget_coordinate


class CoerceGadgetCoordinateTests(unittest.TestCase):
    def test_accepts_int(self):
        self.assertEqual(_coerce_gadget_coordinate(150), 150)

    def test_accepts_float_and_truncates(self):
        self.assertEqual(_coerce_gadget_coordinate(150.9), 150)

    def test_rejects_non_numeric_string(self):
        self.assertIsNone(_coerce_gadget_coordinate("unknown"))

    def test_rejects_bool(self):
        # bool is a subclass of int in Python; a stray True/False is not a
        # sensible screen coordinate and must not be coerced to 1/0.
        self.assertIsNone(_coerce_gadget_coordinate(True))
        self.assertIsNone(_coerce_gadget_coordinate(False))

    def test_rejects_none(self):
        self.assertIsNone(_coerce_gadget_coordinate(None))

    def test_rejects_list(self):
        self.assertIsNone(_coerce_gadget_coordinate([1, 2]))


if __name__ == "__main__":
    unittest.main()
