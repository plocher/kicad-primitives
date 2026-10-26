"""Live symbol nouns keep identity while their declared source changes."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.symbols import SymbolLibrary


class LiveSymbolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Parts.kicad_sym"
        self.original = (
            b"(kicad_symbol_lib (version 20251024)"
            b' (symbol "Root" (property "Description" "parent"))'
            b' (symbol "Child" (extends "Root") (property "Note" "old")))'
        )
        self.path.write_bytes(self.original)

    def test_live_declared_upsert_updates_same_handle_without_parent_write(
        self,
    ) -> None:
        library = SymbolLibrary.open(self.path)
        child = library.symbol("Child")
        before = child.attribute("Note")
        child.set_attribute("Note", "new")
        self.assertIs(library.symbol("Child"), child)
        self.assertEqual(child.attribute("Note").value, "new")
        self.assertEqual(before.value, "old")
        changed = library.to_bytes()
        child.set_attribute("Note", "new")
        self.assertEqual(library.to_bytes(), changed)
        child.set_attribute("Description", "local")
        self.assertEqual(child.attribute("Description").origin_symbol, "Child")
        self.assertEqual(
            library.symbol("Root").attribute("Description").value, "parent"
        )
        self.assertEqual(
            library.resolve("Child").attribute("Description").value, "local"
        )
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_rename_preserves_identity_but_delete_recreate_does_not_rebind(
        self,
    ) -> None:
        library = SymbolLibrary.open(self.path)
        child = library.symbol("Child")
        library.rename_symbol("Child", "Renamed")
        self.assertIs(library.symbol("Renamed"), child)
        self.assertEqual(child.name, "Renamed")
        child.set_attribute("Note", "renamed")
        library.delete_symbol("Renamed")
        library.create_symbol("Renamed")
        self.assertIsNot(library.symbol("Renamed"), child)
        with self.assertRaises(RuntimeError):
            child.set_attribute("Note", "stale")
        with self.assertRaises(KeyError):
            library.symbol("Renamed").attribute("Note")

    def test_body_and_pin_handles_survive_edits_and_symbol_rename(self) -> None:
        library = SymbolLibrary.open(self.path)
        child = library.symbol("Child")
        body = child.ensure_body(1, 2)
        pin = body.add_pin("1", "IN", "input", x=0, y=1)
        body.add_rectangle(start=(-1, 1), end=(1, -1))
        body.add_text("label", x=0, y=2)
        pin.set(name="OUT", electrical_type="output", x=3)
        self.assertIs(child.body(1, 2), body)
        self.assertIs(body.pin("1"), pin)
        self.assertEqual((pin.name, pin.x), ("OUT", 3))
        self.assertEqual(body.texts[0].text, "label")
        self.assertEqual(body.rectangles[0].start_x, -1)
        library.rename_symbol("Child", "Changed")
        self.assertIs(library.symbol("Changed").body(1, 2), body)
        self.assertEqual(body.name, "Changed_1_2")
        pin.set(y=4)
        self.assertEqual(pin.y, 4)
        pin.delete()
        replacement = body.add_pin("1", "NEW", "passive", x=0, y=0)
        self.assertIsNot(replacement, pin)
        with self.assertRaises(RuntimeError):
            pin.set(name="stale")
        library.delete_symbol("Changed")
        with self.assertRaises(RuntimeError):
            body.add_text("stale", x=0, y=0)
        with self.assertRaises(RuntimeError):
            replacement.set(name="stale")
        self.assertEqual(self.path.read_bytes(), self.original)
