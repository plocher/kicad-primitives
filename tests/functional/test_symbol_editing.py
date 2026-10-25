"""Public edit contracts: required deltas, no implicit writes, current spans."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.symbols import (
    AmbiguousPinError,
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


class PinEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Example.kicad_sym"

    def test_add_pin_exact_delta_and_body_style_identity(self) -> None:
        original = (
            b"(kicad_symbol_lib (version 20251024)\r\n"
            b'  (symbol "Part"\r\n'
            b'    (property "Description" "keep")\r\n'
            b'    (symbol "Part_1_1"\r\n'
            b"      (pin passive line (at 0 0 0) (length 1)\r\n"
            b'        (name "A") (number "1"))\r\n'
            b"    )\r\n"
            b'    (symbol "Part_1_2"\r\n'
            b"      (pin passive line (at 1 1 90) (length 1)\r\n"
            b'        (name "A") (number "1"))\r\n'
            b"    )\r\n"
            b"  )\r\n"
            b")\r\n"
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.add_pin(
            "Part",
            1,
            1,
            "2",
            "B",
            "input",
            x=5.08,
            y=0.0,
            rotation=180.0,
            length=2.54,
            shape="line",
        )
        expected = original.replace(
            b'(name "A") (number "1"))\r\n    )\r\n    (symbol "Part_1_2"',
            (
                b'(name "A") (number "1"))\r\n'
                b"      (pin input line\r\n"
                b"        (at 5.08 0 180)\r\n"
                b"        (length 2.54)\r\n"
                b'        (name "B")\r\n'
                b'        (number "2")\r\n'
                b"      )\r\n"
                b"    )\r\n"
                b'    (symbol "Part_1_2"'
            ),
            1,
        )
        self.assertEqual(library.to_bytes(), expected)
        self.assertEqual(self.path.read_bytes(), original)
        body11 = next(b for b in library.symbol("Part").bodies if b.body_style == 1)
        body12 = next(b for b in library.symbol("Part").bodies if b.body_style == 2)
        self.assertEqual([p.number for p in body11.pins], ["1", "2"])
        self.assertEqual(body11.pins[1].name, "B")
        self.assertEqual(body11.pins[1].electrical_type, "input")
        self.assertEqual(body11.pins[1].x, 5.08)
        self.assertEqual(body11.pins[1].rotation, 180.0)
        self.assertEqual(body11.pins[1].length, 2.54)
        # Alternate body style untouched.
        self.assertEqual([p.number for p in body12.pins], ["1"])
        self.assertEqual(body12.pins[0].name, "A")
        library.save()
        reopened = SymbolLibrary.open(self.path)
        body = next(b for b in reopened.symbol("Part").bodies if b.body_style == 1)
        self.assertEqual([p.number for p in body.pins], ["1", "2"])

    def test_set_pin_exact_delta_and_lexical_no_op(self) -> None:
        original = (
            b"(kicad_symbol_lib (version 20251024)\n"
            b'  (symbol "Part"\n'
            b'    (symbol "Part_1_1"\n'
            b"      (pin passive line (at 0 0 0) (length 1)\n"
            b'        (name "A") (number "1"))\n'
            b"    )\n"
            b"  )\n"
            b")\n"
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.set_pin(
            "Part",
            1,
            1,
            "1",
            name="IN",
            x=2.54,
            y=-1.27,
            rotation=90.0,
            length=2.54,
        )
        expected = (
            original.replace(b"(at 0 0 0)", b"(at 2.54 -1.27 90)", 1)
            .replace(b"(length 1)", b"(length 2.54)", 1)
            .replace(b'(name "A")', b'(name "IN")', 1)
        )
        self.assertEqual(library.to_bytes(), expected)
        pin = library.symbol("Part").bodies[0].pins[0]
        self.assertEqual(pin.name, "IN")
        self.assertEqual(
            (pin.x, pin.y, pin.rotation, pin.length), (2.54, -1.27, 90.0, 2.54)
        )
        # Lexical no-op when values already match.
        before = library.to_bytes()
        library.set_pin(
            "Part",
            1,
            1,
            "1",
            name="IN",
            x=2.54,
            y=-1.27,
            rotation=90.0,
            length=2.54,
        )
        self.assertEqual(library.to_bytes(), before)
        library.set_pin(
            "Part",
            1,
            1,
            "1",
            electrical_type="input",
            shape="inverted",
            hidden=True,
        )
        pin = library.symbol("Part").bodies[0].pins[0]
        self.assertEqual(pin.electrical_type, "input")
        self.assertEqual(pin.shape, "inverted")
        self.assertTrue(pin.hidden)

    def test_delete_pin_preserves_alternate_body_and_siblings(self) -> None:
        original = (
            b"(kicad_symbol_lib (version 20251024)\n"
            b'  (symbol "Part"\n'
            b'    (property "Description" "keep")\n'
            b'    (symbol "Part_1_1"\n'
            b"      (pin passive line (at 0 0 0) (length 1)\n"
            b'        (name "A") (number "1"))\n'
            b"      (pin input line (at 5 0 180) (length 2)\n"
            b'        (name "B") (number "2"))\n'
            b"    )\n"
            b'    (symbol "Part_1_2"\n'
            b"      (pin passive line (at 1 1 90) (length 1)\n"
            b'        (name "A") (number "1"))\n'
            b"    )\n"
            b"  )\n"
            b")\n"
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.delete_pin("Part", 1, 1, "1")
        expected = original.replace(
            b"      (pin passive line (at 0 0 0) (length 1)\n"
            b'        (name "A") (number "1"))\n',
            b"",
            1,
        )
        self.assertEqual(library.to_bytes(), expected)
        self.assertEqual(self.path.read_bytes(), original)
        body11 = next(b for b in library.symbol("Part").bodies if b.body_style == 1)
        body12 = next(b for b in library.symbol("Part").bodies if b.body_style == 2)
        self.assertEqual([p.number for p in body11.pins], ["2"])
        self.assertEqual([p.number for p in body12.pins], ["1"])
        self.assertEqual(library.symbol("Part").property("Description").value, "keep")

    def test_pin_ops_do_not_touch_parent_or_create_bodies(self) -> None:
        original = b"""(kicad_symbol_lib (version 20251024)
          (symbol "Child" (extends "Root") (property "Note" "child"))
          (symbol "Root" (property "Description" "parent")
            (symbol "Root_1_1"
              (pin input line (at 0 0 0) (length 1) (name "IN") (number "1")))))"""
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        with self.assertRaises(KeyError):
            library.add_pin("Child", 1, 1, "2", "OUT", "output", x=0.0, y=0.0)
        with self.assertRaises(KeyError):
            library.set_pin("Root", 9, 9, "1", name="X")
        with self.assertRaises(KeyError):
            library.delete_pin("Root", 1, 1, "99")
        self.assertEqual(library.to_bytes(), original)
        library.set_pin("Root", 1, 1, "1", name="IN1")
        self.assertEqual(library.symbol("Child").properties[0].value, "child")
        self.assertEqual(library.resolve("Child").bodies[0].pins[0].name, "IN1")

    def test_pin_ops_bad_selection_leave_memory_and_disk_unchanged(self) -> None:
        cases = (
            (
                (
                    '(symbol "A" (symbol "A_1_1"'
                    ' (pin passive line (at 0 0 0) (length 1) (name "A") (number "1"))'
                    ' (pin input line (at 1 1 0) (length 1) (name "B") (number "1"))))'
                ),
                "A",
                1,
                1,
                "1",
                AmbiguousPinError,
                "set",
            ),
            ('(symbol "A") (symbol "A")', "A", 1, 1, "1", AmbiguousSymbolError, "add"),
            ('(symbol "A")', "Missing", 1, 1, "1", KeyError, "add"),
            (
                (
                    '(symbol "A" (symbol "A_1_1"'
                    ' (pin passive line (at 0 0 0) (length 1) (name "A") (number "1"))))'
                ),
                "A",
                1,
                1,
                "1",
                UnsupportedOperationError,
                "add",
            ),
            (
                (
                    '(symbol "A" (symbol "A_1_1"'
                    ' (pin passive line (at 0 0 0) (length 1) (name "A") (number "1"))))'
                ),
                "A",
                1,
                1,
                "missing",
                KeyError,
                "delete",
            ),
        )
        for nodes, symbol, unit, style, number, error, action in cases:
            with self.subTest(nodes=nodes, action=action):
                original = f"(kicad_symbol_lib (version 20251024) {nodes})".encode()
                self.path.write_bytes(original)
                library = SymbolLibrary.open(self.path)
                with self.assertRaises(error):
                    if action == "add":
                        library.add_pin(
                            symbol, unit, style, number, "X", "passive", x=0.0, y=0.0
                        )
                    elif action == "set":
                        library.set_pin(symbol, unit, style, number, name="Z")
                    else:
                        library.delete_pin(symbol, unit, style, number)
                self.assertEqual(library.to_bytes(), original)
                self.assertEqual(self.path.read_bytes(), original)

    def test_pin_ops_reject_readonly_format_and_invalid_values(self) -> None:
        original = (
            b'(kicad_symbol_lib (version 20231618) (symbol "A"'
            b' (symbol "A_1_1"'
            b' (pin passive line (at 0 0 0) (length 1) (name "A") (number "1")))))'
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        with self.assertRaises(UnsupportedOperationError):
            library.add_pin("A", 1, 1, "2", "B", "passive", x=0.0, y=0.0)
        with self.assertRaises(UnsupportedOperationError):
            library.set_pin("A", 1, 1, "1", name="Z")
        with self.assertRaises(UnsupportedOperationError):
            library.delete_pin("A", 1, 1, "1")
        self.assertEqual(library.to_bytes(), original)

        current = (
            b'(kicad_symbol_lib (version 20251024) (symbol "A"'
            b' (symbol "A_1_1"'
            b' (pin passive line (at 0 0 0) (length 1) (name "A") (number "1")))))'
        )
        self.path.write_bytes(current)
        library = SymbolLibrary.open(self.path)
        with self.assertRaises(ValueError):
            library.add_pin("A", 1, 1, "", "B", "passive", x=0.0, y=0.0)
        with self.assertRaises(ValueError):
            library.add_pin("A", 1, 1, "2", "B", "not a type", x=0.0, y=0.0)
        with self.assertRaises(ValueError):
            library.add_pin("A", 1, 1, "2", "B", "passive", x=float("nan"), y=0.0)
        with self.assertRaises((ValueError, TypeError)):
            library.set_pin("A", 1, 1, "1", name="\x00")
        self.assertEqual(library.to_bytes(), current)


class GraphicsAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Example.kicad_sym"

    def test_unit0_shared_rectangle_and_text_not_copied_to_other_units(self) -> None:
        original = (
            b"(kicad_symbol_lib (version 20251024)\n"
            b'  (symbol "Part"\n'
            b'    (symbol "Part_1_1"\n'
            b"      (pin passive line (at 0 0 0) (length 1)\n"
            b'        (name "A") (number "1"))\n'
            b"    )\n"
            b"  )\n"
            b")\n"
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.ensure_body("Part", 0, 1)
        library.add_rectangle("Part", 0, 1, start=(-2.54, 2.54), end=(2.54, -2.54))
        library.add_body_text("Part", 0, 1, "SHARED", x=0.0, y=3.0)
        # Pin placement stays on the unit body (not copied into unit 0).
        library.add_pin("Part", 1, 1, "2", "B", "input", x=5.08, y=0.0, rotation=180.0)
        part = library.symbol("Part")
        unit0 = part.body(0, 1)
        unit1 = part.body(1, 1)
        self.assertEqual(len(unit0.rectangles), 1)
        self.assertEqual(unit0.rectangles[0].start_x, -2.54)
        self.assertEqual(unit0.texts[0].text, "SHARED")
        self.assertEqual(unit0.pins, ())
        self.assertEqual([p.number for p in unit1.pins], ["1", "2"])
        self.assertEqual(unit1.rectangles, ())
        self.assertEqual(unit1.texts, ())
        # Shared label lives only on the unit-0 body source span.
        rendered = library.to_bytes()
        self.assertIn(b'(text "SHARED"', rendered)
        self.assertEqual(rendered.count(b"SHARED"), 1)
        library.ensure_body("Part", 0, 1)  # no-op
        self.assertEqual(len(library.symbol("Part").bodies), 2)

    def test_ensure_body_and_graphics_reject_readonly(self) -> None:
        original = (
            b'(kicad_symbol_lib (version 20231618) (symbol "A" (symbol "A_1_1")))'
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        with self.assertRaises(UnsupportedOperationError):
            library.ensure_body("A", 0, 1)
        with self.assertRaises(UnsupportedOperationError):
            library.add_rectangle("A", 1, 1, start=(0.0, 0.0), end=(1.0, 1.0))
        with self.assertRaises(UnsupportedOperationError):
            library.add_body_text("A", 1, 1, "X", x=0.0, y=0.0)
        self.assertEqual(library.to_bytes(), original)

    def test_export_svgs_uses_in_memory_bytes_and_cli(self) -> None:
        from unittest.mock import patch

        from kicad_primitives.symbols import KicadCliNotFoundError

        original = (
            b'(kicad_symbol_lib (version 20251024) (symbol "A"'
            b' (symbol "A_1_1"'
            b" (pin passive line (at 0 0 0) (length 1)"
            b' (name "A") (number "1")))))'
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.ensure_body("A", 0, 1)
        library.add_rectangle("A", 0, 1, start=(0.0, 1.0), end=(1.0, 0.0))
        out = Path(self.temp.name) / "svg-out"
        fake_cli = Path(self.temp.name) / "fake-kicad-cli"
        fake_cli.write_text("#!/bin/sh\nexit 0\n")
        fake_cli.chmod(0o755)

        def fake_run(command, check, capture_output, text, timeout):  # type: ignore[no-untyped-def]
            self.assertEqual(command[0], str(fake_cli.resolve()))
            self.assertEqual(command[1:4], ["sym", "export", "svg"])
            # Temp library must include the unit-0 rectangle from memory.
            lib = Path(command[-1])
            self.assertTrue(lib.is_file())
            self.assertIn(b"(rectangle", lib.read_bytes())
            self.assertIn(b"A_0_1", lib.read_bytes())
            out.mkdir(parents=True, exist_ok=True)
            (out / "A_unit1.svg").write_text("<svg/>")
            return type("R", (), {"returncode": 0})()

        with patch("kicad_primitives.symbols.subprocess.run", side_effect=fake_run):
            result = library.export_svgs(out, kicad_cli=fake_cli)
        self.assertEqual(result, out)
        self.assertTrue((out / "A_unit1.svg").is_file())

        with self.assertRaises(KicadCliNotFoundError):
            library.export_svgs(out / "missing", kicad_cli=out / "no-such-cli")


class SymbolLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Example.kicad_sym"

    def test_create_rename_copy_delete_same_library(self) -> None:
        original = (
            b"(kicad_symbol_lib (version 20251024)\n"
            b'  (symbol "Root"\n'
            b'    (property "Description" "base")\n'
            b'    (symbol "Root_0_1"\n'
            b"      (rectangle (start -1 1) (end 1 -1))\n"
            b"    )\n"
            b'    (symbol "Root_1_1"\n'
            b"      (pin passive line (at 0 0 0) (length 1)\n"
            b'        (name "A") (number "1"))\n'
            b"    )\n"
            b"  )\n"
            b'  (symbol "Child" (extends "Root") (property "Note" "c"))\n'
            b")\n"
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        library.create_symbol("Empty")
        library.create_symbol("Derived", extends="Root")
        self.assertIsNone(library.symbol("Empty").extends)
        self.assertEqual(library.symbol("Derived").extends, "Root")

        library.copy_symbol("Root", "RootCopy")
        copy = library.symbol("RootCopy")
        self.assertEqual(copy.property("Description").value, "base")
        self.assertEqual(
            [(b.unit, b.body_style, b.name) for b in copy.bodies],
            [(0, 1, "RootCopy_0_1"), (1, 1, "RootCopy_1_1")],
        )
        self.assertEqual(library.symbol("Root").bodies[1].pins[0].number, "1")

        library.rename_symbol("Root", "Base")
        self.assertEqual(library.symbol("Child").extends, "Base")
        self.assertEqual(library.symbol("Derived").extends, "Base")
        base = library.symbol("Base")
        self.assertEqual(base.bodies[0].name, "Base_0_1")
        self.assertEqual(base.bodies[1].name, "Base_1_1")
        with self.assertRaises(KeyError):
            library.symbol("Root")

        with self.assertRaises(UnsupportedOperationError):
            library.delete_symbol("Base")  # still extended
        library.delete_symbol("Child")
        library.delete_symbol("Derived")
        library.delete_symbol("Empty")
        library.delete_symbol("RootCopy")
        library.delete_symbol("Base")
        self.assertEqual(library.symbols, ())
        self.assertEqual(self.path.read_bytes(), original)  # no save yet
        library.save()
        self.assertEqual(
            [s.name for s in SymbolLibrary.open(self.path).symbols],
            [],
        )

    def test_lifecycle_failures_leave_memory_and_disk_unchanged(self) -> None:
        original = (
            b"(kicad_symbol_lib (version 20251024)"
            b' (symbol "A" (symbol "A_1_1"))'
            b' (symbol "B" (extends "A")))'
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        cases = (
            lambda: library.create_symbol("A"),
            lambda: library.rename_symbol("A", "B"),
            lambda: library.copy_symbol("A", "B"),
            lambda: library.delete_symbol("A"),
            lambda: library.copy_symbol_from(library, "A", "A"),
            lambda: library.create_symbol("X", extends="Missing"),
        )
        for action in cases:
            with self.subTest(action=action):
                with self.assertRaises((UnsupportedOperationError, KeyError)):
                    action()
                self.assertEqual(library.to_bytes(), original)
                self.assertEqual(self.path.read_bytes(), original)

    def test_copy_symbol_from_cross_library(self) -> None:
        source_path = Path(self.temp.name) / "Source.kicad_sym"
        dest_path = Path(self.temp.name) / "Dest.kicad_sym"
        source_original = (
            b"(kicad_symbol_lib (version 20251024)\n"
            b'  (symbol "Root"\n'
            b'    (property "Description" "base")\n'
            b'    (symbol "Root_0_1"\n'
            b"      (rectangle (start -1 1) (end 1 -1))\n"
            b"    )\n"
            b'    (symbol "Root_1_1"\n'
            b"      (pin passive line (at 0 0 0) (length 1)\n"
            b'        (name "A") (number "1"))\n'
            b"    )\n"
            b"  )\n"
            b'  (symbol "Child" (extends "Root") (property "Note" "c"))\n'
            b")\n"
        )
        source_path.write_bytes(source_original)
        dest_original = (
            b"(kicad_symbol_lib (version 20251024)\n"
            b'  (symbol "Keep" (property "Description" "stay"))\n'
            b")\n"
        )
        dest_path.write_bytes(dest_original)
        source = SymbolLibrary.open(source_path)
        dest = SymbolLibrary.open(dest_path)

        dest.copy_symbol_from(source, "Root", "ImportedRoot")
        copied = dest.symbol("ImportedRoot")
        self.assertEqual(copied.property("Description").value, "base")
        self.assertEqual(
            [(b.unit, b.body_style, b.name) for b in copied.bodies],
            [(0, 1, "ImportedRoot_0_1"), (1, 1, "ImportedRoot_1_1")],
        )
        self.assertEqual(dest.symbol("Keep").property("Description").value, "stay")
        self.assertEqual([s.name for s in source.symbols], ["Root", "Child"])

        with self.assertRaises(UnsupportedOperationError):
            dest.copy_symbol_from(source, "Child", "Child")

        # Parent must exist under the extends name the child still carries.
        dest.copy_symbol_from(source, "Root", "Root")
        dest.copy_symbol_from(source, "Child", "Child")
        self.assertEqual(dest.symbol("Child").extends, "Root")
        self.assertEqual(dest.symbol("Child").property("Note").value, "c")

        with self.assertRaises(UnsupportedOperationError):
            dest.copy_symbol_from(source, "Root", "Root")
        self.assertEqual(source_path.read_bytes(), source_original)
        self.assertEqual(dest_path.read_bytes(), dest_original)
        dest.save()
        reopened = SymbolLibrary.open(dest_path)
        self.assertEqual(
            [s.name for s in reopened.symbols],
            ["Keep", "ImportedRoot", "Root", "Child"],
        )

    def test_copy_symbol_from_via_library_table_resolve(self) -> None:
        from kicad_primitives.tables import LibraryTables

        config_home = Path(self.temp.name) / "cfg"
        libs = Path(self.temp.name) / "libs"
        config_home.mkdir()
        libs.mkdir()
        source_path = libs / "Source.kicad_sym"
        dest_path = libs / "Dest.kicad_sym"
        source_path.write_bytes(
            b'(kicad_symbol_lib (version 20251024) (symbol "Part"'
            b' (property "Description" "from-table")'
            b' (symbol "Part_1_1")))'
        )
        dest_path.write_bytes(
            b'(kicad_symbol_lib (version 20251024) (symbol "Keep"'
            b' (property "Description" "dest")))'
        )
        (config_home / "sym-lib-table").write_text(
            "(sym_lib_table\n"
            f'  (lib (name "Src") (type "KiCad") (uri "{source_path}")'
            ' (options "") (descr ""))\n'
            f'  (lib (name "Dst") (type "KiCad") (uri "{dest_path}")'
            ' (options "") (descr ""))\n'
            ")\n",
            encoding="utf-8",
        )
        tables = LibraryTables.open(config_home=config_home)
        source = SymbolLibrary.open(
            tables.resolve("Src", library_type="symbol").resolved_path
        )
        dest = SymbolLibrary.open(
            tables.resolve("Dst", library_type="symbol").resolved_path
        )
        dest.copy_symbol_from(source, "Part", "Imported")
        self.assertEqual(
            dest.symbol("Imported").property("Description").value, "from-table"
        )
        self.assertEqual(dest.symbol("Keep").property("Description").value, "dest")
        self.assertEqual([s.name for s in source.symbols], ["Part"])

    def test_lifecycle_rejects_readonly_format(self) -> None:
        original = (
            b'(kicad_symbol_lib (version 20231618) (symbol "A" (symbol "A_1_1")))'
        )
        self.path.write_bytes(original)
        library = SymbolLibrary.open(self.path)
        with self.assertRaises(UnsupportedOperationError):
            library.create_symbol("B")
        with self.assertRaises(UnsupportedOperationError):
            library.rename_symbol("A", "B")
        with self.assertRaises(UnsupportedOperationError):
            library.copy_symbol("A", "B")
        with self.assertRaises(UnsupportedOperationError):
            library.delete_symbol("A")
        self.assertEqual(library.to_bytes(), original)
