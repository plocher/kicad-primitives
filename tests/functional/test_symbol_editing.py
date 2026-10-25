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


class PropertyInsertDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Example.kicad_sym"

    def test_add_property_exact_delta_and_private(self) -> None:
        original = (
            "(kicad_symbol_lib (version 20251024)\r\n"
            '  (symbol "Café"\r\n'
            '    (property "Description" "old")\r\n'
            '    (symbol "Café_1_1"\r\n'
            "      (pin passive line (at 0 0 0) (length 1)\r\n"
            '        (name "P") (number "1"))\r\n'
            "    )\r\n"
            "  )\r\n"
            ")\r\n"
        ).encode()
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.add_property("Café", "Role", "DEVICE")
        expected = original.replace(
            b'(property "Description" "old")',
            b'(property "Description" "old")\r\n'
            b'    (property "Role" "DEVICE"\r\n'
            b"      (at 0 0 0)\r\n"
            b"    )",
            1,
        )
        self.assertEqual(library.to_bytes(), expected)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(library.symbol("Café").property("Role").value, "DEVICE")
        self.assertFalse(library.symbol("Café").property("Role").is_private)
        # Bodies and other symbols stay intact.
        self.assertEqual(library.symbol("Café").bodies[0].pins[0].number, "1")
        library.add_property("Café", "KLC_S3.3", "reason", private=True)
        self.assertTrue(library.symbol("Café").property("KLC_S3.3").is_private)
        self.assertEqual(library.symbol("Café").property("KLC_S3.3").value, "reason")
        library.save()
        reopened = SymbolLibrary.open(self.path)
        self.assertEqual(reopened.symbol("Café").property("Role").value, "DEVICE")
        self.assertTrue(reopened.symbol("Café").property("KLC_S3.3").is_private)

    def test_add_property_when_symbol_has_no_properties(self) -> None:
        original = b'(kicad_symbol_lib (version 20251024) (symbol "A" (extends "B")))'
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.add_property("A", "Note", "fresh")
        self.assertEqual(library.symbol("A").property("Note").value, "fresh")
        self.assertIn(b'(property "Note" "fresh"', library.to_bytes())
        self.assertIn(b'(extends "B")', library.to_bytes())

    def test_delete_property_exact_delta_preserves_siblings(self) -> None:
        original = (
            b"(kicad_symbol_lib (version 20251024)\n"
            b'  (symbol "Part"\n'
            b'    (property "Description" "keep")\n'
            b'    (property "Note" "drop")\n'
            b'    (property private "Secret" "stay")\n'
            b'    (symbol "Part_1_1"\n'
            b"      (pin passive line (at 0 0 0) (length 1)\n"
            b'        (name "P") (number "1"))\n'
            b"    )\n"
            b"  )\n"
            b")\n"
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.delete_property("Part", "Note")
        expected = original.replace(b'\n    (property "Note" "drop")', b"", 1)
        self.assertEqual(library.to_bytes(), expected)
        self.assertEqual(self.path.read_bytes(), original)
        props = [p.name for p in library.symbol("Part").properties]
        self.assertEqual(props, ["Description", "Secret"])
        self.assertEqual(library.symbol("Part").bodies[0].pins[0].name, "P")
        library.delete_property("Part", "Secret")
        self.assertEqual(
            [p.name for p in library.symbol("Part").properties], ["Description"]
        )
        library.save()
        self.assertEqual(
            [p.name for p in SymbolLibrary.open(self.path).symbol("Part").properties],
            ["Description"],
        )

    def test_child_add_does_not_touch_parent_and_enables_local_override(self) -> None:
        original = b"""(kicad_symbol_lib (version 20251024)
          (symbol "Child" (extends "Root") (property "Note" "child"))
          (symbol "Root" (property "Description" "parent") (property "Note" "base")))"""
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.add_property("Child", "Description", "local")
        self.assertEqual(library.symbol("Root").property("Description").value, "parent")
        self.assertEqual(
            library.resolve("Child").property("Description").origin_symbol, "Child"
        )
        self.assertEqual(
            library.resolve("Child").property("Description").value, "local"
        )

    def test_delete_declared_does_not_remove_inherited_effective_value(self) -> None:
        original = b"""(kicad_symbol_lib (version 20251024)
          (symbol "Child" (extends "Root")
            (property "Description" "local") (property "Note" "child"))
          (symbol "Root"
            (property "Description" "parent") (property "Note" "base")
            (symbol "Root_1_1"
              (pin input line (at 0 0 0) (length 1) (name "IN") (number "1")))))"""
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.delete_property("Child", "Description")
        with self.assertRaises(KeyError):
            library.symbol("Child").property("Description")
        resolved = library.resolve("Child")
        self.assertEqual(resolved.property("Description").value, "parent")
        self.assertEqual(resolved.property("Description").origin_symbol, "Root")
        self.assertEqual(library.symbol("Root").property("Description").value, "parent")

    def test_add_and_delete_bad_selection_leave_memory_and_disk_unchanged(self) -> None:
        cases = (
            (
                '(symbol "A" (property "Note" "one") (property "Note" "two"))',
                "A",
                "Note",
                AmbiguousPropertyError,
                "delete",
            ),
            (
                '(symbol "A" (property "Reference" "U") (property "reference" "J"))',
                "A",
                "Reference",
                AmbiguousPropertyError,
                "add",
            ),
            ('(symbol "A") (symbol "A")', "A", "Note", AmbiguousSymbolError, "add"),
            ('(symbol "A")', "Missing", "Note", KeyError, "add"),
            (
                '(symbol "A" (property "Note" "x"))',
                "A",
                "Note",
                UnsupportedOperationError,
                "add",
            ),
            ('(symbol "A")', "A", "Missing", KeyError, "delete"),
            (
                '(symbol "A" (property "Note" "x"))',
                "A",
                "Missing",
                KeyError,
                "delete",
            ),
        )
        for nodes, symbol, key, error, action in cases:
            with self.subTest(nodes=nodes, action=action):
                original = f"(kicad_symbol_lib (version 20251024) {nodes})".encode()
                self.path.write_bytes(original)
                library = SymbolLibrary.open(self.path)
                with self.assertRaises(error):
                    if action == "add":
                        library.add_property(symbol, key, "replacement")
                    else:
                        library.delete_property(symbol, key)
                self.assertEqual(library.to_bytes(), original)
                self.assertEqual(self.path.read_bytes(), original)

    def test_add_invalid_value_fails_before_mutation(self) -> None:
        original = b'(kicad_symbol_lib (version 20251024) (symbol "A"))'
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        for value in ("\x00", "\ud800", 123):
            with (
                self.subTest(value=repr(value)),
                self.assertRaises((ValueError, TypeError)),
            ):
                library.add_property("A", "Note", value)  # type: ignore[arg-type]
            self.assertEqual(library.to_bytes(), original)

    def test_add_delete_reject_readonly_format(self) -> None:
        original = (
            b'(kicad_symbol_lib (version 20231618) (symbol "A" (property "Note" "x")))'
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        with self.assertRaises(UnsupportedOperationError):
            library.add_property("A", "Role", "X")
        with self.assertRaises(UnsupportedOperationError):
            library.delete_property("A", "Note")
        self.assertEqual(library.to_bytes(), original)
