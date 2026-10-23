"""Protect the private edit mechanism's independent postconditions."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lossless_sexpr import parse

from kicad_primitives import _symbol_parse, _symbol_persist
from kicad_primitives.symbols import FileConflictError, InvalidLibraryError

ORIGINAL = b'(kicad_symbol_lib (version 20251024) (symbol "A" (property "Note" "old")))'


class EditPostconditionTests(unittest.TestCase):
    def test_apply_cannot_silently_omit_the_required_edit_or_change_other_bytes(
        self,
    ) -> None:
        source = _symbol_parse.read_source(ORIGINAL)
        for broken_output in (
            ORIGINAL.decode(),
            ORIGINAL.decode().replace("20251024", "20250101"),
        ):
            with (
                self.subTest(output=broken_output),
                patch(
                    "kicad_primitives._symbol_parse.apply_edits",
                    return_value=broken_output,
                ),
                self.assertRaises(InvalidLibraryError),
            ):
                _symbol_parse.replace_property(source, "A", "Note", "new")
            self.assertEqual(source.document.source.encode(), ORIGINAL)

    def test_wrong_quote_value_fails_semantic_postcondition(self) -> None:
        source = _symbol_parse.read_source(ORIGINAL)
        with (
            patch("kicad_primitives._symbol_parse.quote", return_value='"wrong"'),
            self.assertRaises(InvalidLibraryError),
        ):
            _symbol_parse.replace_property(source, "A", "Note", "new")
        self.assertEqual(source.document.source.encode(), ORIGINAL)

    def test_nonfinite_numbers_and_bad_flags_are_not_silently_defaulted(self) -> None:
        for value in ("nan", "inf", "not_numeric"):
            node = parse(f"(at {value} 0 0)").roots()[0]
            with self.subTest(value=value), self.assertRaises(InvalidLibraryError):
                _symbol_parse.number(node, 1)
        node = parse("(pin (hide maybe))").roots()[0]
        with self.assertRaises(InvalidLibraryError):
            _symbol_parse.flag(node, "hide")

    def test_empty_filter_list_inherits_but_nonempty_whitespace_keywords_override(
        self,
    ) -> None:
        source = _symbol_parse.read_source(b"""(kicad_symbol_lib (version 20251024)
          (symbol "Root" (property "ki_fp_filters" "Device:*") (property "ki_keywords" "base"))
          (symbol "Child" (extends "Root")
            (property "ki_fp_filters" " \\t ") (property "ki_keywords" " ")))""")
        child = _symbol_parse.resolve(source, "Child")
        self.assertEqual(child.property("ki_fp_filters").value, "Device:*")
        self.assertEqual(child.property("ki_keywords").value, " ")


class PersistenceMechanismTests(unittest.TestCase):
    def test_change_while_temp_output_is_written_fails_final_check(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "Example.kicad_sym"
            path.write_bytes(ORIGINAL)
            foreign = ORIGINAL.replace(b'"old"', b'"foreign"')
            with (
                patch(
                    "kicad_primitives._symbol_persist.os.fsync",
                    side_effect=lambda fd: path.write_bytes(foreign),
                ),
                self.assertRaises(FileConflictError),
            ):
                _symbol_persist.save_source(
                    path, ORIGINAL, ORIGINAL.replace(b'"old"', b'"new"')
                )
            self.assertEqual(path.read_bytes(), foreign)
            self.assertEqual(list(path.parent.iterdir()), [path])
