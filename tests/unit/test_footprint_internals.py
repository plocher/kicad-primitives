"""Unit checks on footprint internals: fingerprint, pad counting, filters, format gate."""

import unittest

from kicad_primitives import _footprint_parse
from kicad_primitives._footprint_types import (
    Pad,
    UnsupportedOperationError,
    matches_filters,
    unique_pad_count,
)
from kicad_primitives._symbol_persist import Fingerprint


def _pad(
    number: str, pad_type: str = "smd", layers: tuple[str, ...] = ("F.Cu",)
) -> Pad:
    return Pad(number, pad_type, "rect", 0.0, 0.0, 0.0, 1.0, 1.0, layers)


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_matches_only_identical_content(self) -> None:
        raw = b'(footprint "A")'
        fingerprint = Fingerprint.of(raw)
        self.assertTrue(fingerprint.matches(raw))
        self.assertFalse(fingerprint.matches(raw + b" "))
        self.assertFalse(fingerprint.matches(b'(footprint "B")'))
        self.assertEqual(fingerprint, Fingerprint.of(bytes(raw)))


class UniquePadCountTests(unittest.TestCase):
    def test_kicad_10_0_1_rule(self) -> None:
        pads = (
            _pad("1"),
            _pad("1"),  # repeated number: one
            _pad("2", layers=("*.Cu", "*.Mask")),
            _pad("In", layers=("In1.Cu",)),
            _pad("", pad_type="np_thru_hole", layers=("*.Cu",)),  # unnamed
            _pad("9", pad_type="np_thru_hole", layers=("*.Cu",)),  # NPTH excluded
            _pad("3", layers=("F.Paste",)),  # no copper
            _pad("MP"),
            _pad("A1_B12"),
            _pad("A1_B12"),
        )
        self.assertEqual(unique_pad_count(pads), 5)  # 1, 2, In, MP, A1_B12
        self.assertEqual(unique_pad_count(()), 0)


class FilterTests(unittest.TestCase):
    def test_wildcards_are_anchored_and_case_insensitive(self) -> None:
        self.assertTrue(matches_filters("SOIC-8_3.9x4.9mm", ["soic-8*"]))
        self.assertFalse(matches_filters("SOIC-8_3.9x4.9mm", ["soic-8"]))
        self.assertTrue(matches_filters("SOIC-8", ["SOIC-?"]))
        self.assertFalse(matches_filters("SOIC-8", ["SOIC-??"]))
        self.assertTrue(matches_filters("A.B", ["A.B"]))
        self.assertFalse(matches_filters("AxB", ["A.B"]))  # '.' is literal
        self.assertTrue(matches_filters("x", []))
        self.assertTrue(matches_filters("x", ["", "x"]))

    def test_nickname_is_used_only_for_patterns_with_a_colon(self) -> None:
        self.assertTrue(matches_filters("R_0603", ["lib:r_*"], nickname="Lib"))
        self.assertFalse(matches_filters("R_0603", ["lib:r_*"], nickname="Other"))
        self.assertTrue(matches_filters("R_0603", ["r_*"], nickname="Other"))
        self.assertFalse(matches_filters("R_0603", ["lib:r_*"]))


class FormatGateTests(unittest.TestCase):
    def test_write_format_is_20260206_only(self) -> None:
        self.assertEqual(_footprint_parse.WRITE_VERSION, 20260206)
        _footprint_parse.require_writeable(20260206)
        for version in (0, 20240108, 20251024):
            with (
                self.subTest(version=version),
                self.assertRaises(UnsupportedOperationError),
            ):
                _footprint_parse.require_writeable(version)
        with self.assertRaises(UnsupportedOperationError):
            _footprint_parse.read_source(b'(footprint "F" (version 20270101))')
        legacy = _footprint_parse.read_source(
            b'(module "M" (layer F.Cu) (pad 1 smd rect (at 0 0) (size 1 1) (layers F.Cu)))'
        )
        self.assertEqual(legacy.version, 0)
        self.assertEqual(legacy.pads[0].number, "1")


if __name__ == "__main__":
    unittest.main()
