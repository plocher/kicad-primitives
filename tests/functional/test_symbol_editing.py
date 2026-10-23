"""Public edit contracts: required deltas, no implicit writes, current spans."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.symbols import (
    AmbiguousPropertyError,
    AmbiguousSymbolError,
    SymbolLibrary,
    UnsupportedOperationError,
)


class PropertyEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Example.kicad_sym"

    def test_exact_delta_crlf_unicode_and_successive_edits(self) -> None:
        original = (
            "(kicad_symbol_lib (version 20251024)\r\n"
            '  (future_node "(opaque)" 001.00)\r\n'
            '  (symbol "Café"\r\n'
            '    (property "Description" "old")\r\n'
            '    (property private "Note" "untouched" (at 1.00 -0 90) (hide yes))\r\n'
            '    (property "Quoted" "a \\"quote\\" and \\\\slash")\r\n'
            "  ))\r\n"
        ).encode()
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        snapshot = library.symbol("Café")
        value = 'Résumé "quoted" \\ path\nnext\tline'
        library.set_property("Café", "Description", value)
        expected = original.replace(
            b'"old"', '"Résumé \\"quoted\\" \\\\ path\\nnext\\tline"'.encode(), 1
        )
        self.assertEqual(library.to_bytes(), expected)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(snapshot.property("Description").value, "old")
        self.assertEqual(library.symbol("Café").property("Description").value, value)
        library.set_property("Café", "Note", "new")
        expected = expected.replace(b'"untouched"', b'"new"', 1)
        self.assertEqual(library.to_bytes(), expected)
        self.assertTrue(library.symbol("Café").property("Note").is_private)
        library.save()
        self.assertEqual(self.path.read_bytes(), expected)
        library.set_property("Café", "Note", "third")
        library.save()
        self.assertEqual(
            self.path.read_bytes(), expected.replace(b'"new"', b'"third"', 1)
        )
        self.assertEqual(
            SymbolLibrary.open(self.path).symbol("Café").property("Note").value, "third"
        )

    def test_equal_value_is_a_lexical_and_filesystem_no_op(self) -> None:
        original = b'(kicad_symbol_lib (version 20251024) (symbol "A" (property "Note" "a\\q")))'
        self.path.write_bytes(original)
        before = self.path.stat()
        library = SymbolLibrary.open(self.path)
        library.set_property("A", "Note", "aq")
        library.save()
        self.assertEqual(library.to_bytes(), original)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.stat().st_ino, before.st_ino)
        self.assertEqual(self.path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_declared_child_edit_never_changes_parent_or_adds_fields(self) -> None:
        original = b"""(kicad_symbol_lib (version 20251024)
          (symbol "Child" (extends "Root") (property "Note" "child"))
          (symbol "Root" (property "Description" "parent") (property "Note" "base")))"""
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        with self.assertRaises(UnsupportedOperationError):
            library.set_property("Child", "Description", "not declared")
        self.assertEqual(library.to_bytes(), original)
        library.set_property("Child", "Note", "local")
        self.assertEqual(
            library.to_bytes(), original.replace(b'"child"', b'"local"', 1)
        )
        self.assertEqual(library.symbol("Root").property("Note").value, "base")
        self.assertEqual(
            library.resolve("Child").property("Note").origin_symbol, "Child"
        )

    def test_bad_selection_leaves_memory_and_disk_unchanged(self) -> None:
        for nodes, symbol, key, error in (
            (
                '(symbol "A" (property "Note" "one") (property "Note" "two"))',
                "A",
                "Note",
                AmbiguousPropertyError,
            ),
            (
                '(symbol "A" (property "Reference" "U") (property "reference" "J"))',
                "A",
                "Reference",
                AmbiguousPropertyError,
            ),
            ('(symbol "A") (symbol "A")', "A", "Note", AmbiguousSymbolError),
            ('(symbol "A")', "Missing", "Note", KeyError),
            ('(symbol "A")', "A", "New", UnsupportedOperationError),
        ):
            with self.subTest(nodes=nodes):
                original = f"(kicad_symbol_lib (version 20251024) {nodes})".encode()
                self.path.write_bytes(original)
                library = SymbolLibrary.open(self.path)
                with self.assertRaises(error):
                    library.set_property(symbol, key, "replacement")
                self.assertEqual(library.to_bytes(), original)
                self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_value_fails_before_mutation(self) -> None:
        original = b'(kicad_symbol_lib (version 20251024) (symbol "A" (property "Note" "old")))'
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        for value in ("\x00", "\ud800", 123):
            with (
                self.subTest(value=repr(value)),
                self.assertRaises((ValueError, TypeError)),
            ):
                library.set_property("A", "Note", value)  # type: ignore[arg-type]
            self.assertEqual(library.to_bytes(), original)
            self.assertEqual(self.path.read_bytes(), original)
