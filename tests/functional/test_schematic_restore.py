"""EmbeddedSymbol.update_from_library through artifact objects, never a batch API."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import Project
from kicad_primitives.schematics import (
    AmbiguousEmbeddedSymbolError,
    InvalidSchematicError,
    UnsupportedSchematicOperationError,
)
from kicad_primitives.symbols import AmbiguousSymbolError, SymbolLibrary

CACHE = """(symbol "Test:Part"
    (property "Value" "old default")
    (opaque "unchanged")
    (symbol "Part_1_1"
      (text "old graphics" (at 0 0 0))
      (pin output line (at 0 5.08 270) (length 2.54)
        (name "A") (number "1"))
      (pin input line (at 0 -5.08 90) (length 2.54)
        (name "B") (number "2"))
    )
  )"""
PARENT = """(symbol "Parent"
    (property "Value" "new default")
    (opaque "unchanged")
    (symbol "Parent_1_1"
      (text "new graphics" (at 0 0 0))
      (pin passive line (at 0 5.08 270) (length 2.54)
        (name "A") (number "1"))
      (pin passive line (at 0 -5.08 90) (length 2.54)
        (name "B") (number "2"))
    )
  )"""
EXPECTED = """(symbol "Test:Part"
    (property "Value" "new default")
    (opaque "unchanged")
    (symbol "Part_1_1"
      (text "new graphics" (at 0 0 0))
      (pin passive line (at 0 5.08 270) (length 2.54)
        (name "A") (number "1"))
      (pin passive line (at 0 -5.08 90) (length 2.54)
        (name "B") (number "2"))
    )
  )"""
OTHER = CACHE.replace("Test:Part", "Test:Other").replace("Part_1_1", "Other_1_1")
SOURCE = f"""(kicad_sch (version 20260306)
  (lib_symbols {CACHE} {OTHER})
  (symbol (lib_id "Test:Part") (at 50 50 0) (unit 1) (uuid "first")
    (property "Reference" "R1") (property "Value" "placed")
    (instances (project "board" (path "/" (reference "R1") (unit 1)))))
  (symbol (lib_id "Test:Part") (at 70 50 0) (unit 1) (uuid "second")
    (property "Reference" "R2") (property "Value" "placed"))
  (symbol (lib_id "Test:Other") (at 90 50 0) (unit 1) (uuid "unrelated")
    (property "Reference" "C1") (property "Value" "unrelated"))
)
"""


class EmbeddedRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "board.kicad_pro").write_text("{}", encoding="utf-8")
        self.path = self.directory / "board.kicad_sch"
        self.path.write_bytes(SOURCE.encode())
        self.parent_path = self.directory / "parent.kicad_sym"
        self.parent_path.write_text(
            f"(kicad_symbol_lib (version 20251024) {PARENT})", encoding="utf-8"
        )
        self.parent = SymbolLibrary.open(self.parent_path)
        self.project = Project.open(self.directory)
        self.schematic = self.project.schematic().files[0]

    def reopen_parent(self) -> SymbolLibrary:
        """Exit the registered parent and read the file on disk again."""
        self.parent.discard()
        self.parent = SymbolLibrary.open(self.parent_path)
        return self.parent

    def test_selected_restore_is_exact_and_preserves_stable_placed_objects(
        self,
    ) -> None:
        placed = self.schematic.symbol("R1")
        embedded = self.schematic.embedded_symbol("Test:Part")
        self.assertEqual(
            [s.lib_id for s in self.schematic.embedded_symbols],
            ["Test:Part", "Test:Other"],
        )
        embedded.update_from_library(self.parent, "Parent")
        self.assertEqual(
            self.schematic.to_bytes(), SOURCE.replace(CACHE, EXPECTED, 1).encode()
        )
        self.assertIs(self.schematic.symbol("R1"), placed)
        self.assertEqual(placed.value, "placed")
        self.assertIs(self.schematic.embedded_symbol("Test:Part"), embedded)
        self.assertEqual(self.path.read_bytes(), SOURCE.encode())
        self.assertTrue(self.project.is_modified)
        self.parent.symbol("Parent").set_attribute("Value", "later")
        self.assertEqual(
            self.schematic.to_bytes(), SOURCE.replace(CACHE, EXPECTED, 1).encode()
        )
        embedded.update_from_library(self.reopen_parent(), "Parent")
        first = self.schematic.to_bytes()
        embedded.update_from_library(self.reopen_parent(), "Parent")
        self.assertEqual(self.schematic.to_bytes(), first)

    def test_handles_remain_live_across_attributes_other_cache_and_revert(self) -> None:
        embedded = self.schematic.embedded_symbol("Test:Part")
        other = self.schematic.embedded_symbol("Test:Other")
        placed = self.schematic.symbol("R1")
        placed.set_attribute("MPN", "é" * 50)
        embedded.update_from_library(self.parent, "Parent")
        placed.set_attribute("Value", "new placed value")
        second_parent = PARENT.replace("Parent", "Second").replace(
            "pin passive", "pin output", 1
        )
        second_parent = second_parent.replace("pin passive", "pin input", 1)
        self.parent_path.write_text(
            f"(kicad_symbol_lib (version 20251024) {second_parent})", encoding="utf-8"
        )
        other.update_from_library(self.reopen_parent(), "Second")
        self.assertIs(self.schematic.embedded_symbol("Test:Part"), embedded)
        self.assertIs(self.schematic.embedded_symbol("Test:Other"), other)
        self.assertIs(self.schematic.symbol("R1"), placed)
        self.assertEqual(placed.attribute("MPN").value, "é" * 50)
        self.assertEqual(placed.value, "new placed value")
        old_parent = CACHE.replace("Test:Part", "Parent").replace(
            "Part_1_1", "Parent_1_1"
        )
        self.parent_path.write_text(
            f"(kicad_symbol_lib (version 20251024) {old_parent})", encoding="utf-8"
        )
        embedded.update_from_library(self.reopen_parent(), "Parent")
        self.assertIn(CACHE.encode(), self.schematic.to_bytes())
        self.assertTrue(
            self.project.is_modified
        )  # other cache/placed attrs still pending

    def test_crlf_quoted_multiline_and_unknown_payload_are_not_reindented(self) -> None:
        source = SOURCE.replace("\n", "\r\n")
        self.path.write_bytes(source.encode())
        schematic = Project.open(self.directory).schematic().files[0]
        parent = PARENT.replace(
            "new graphics", 'new \\"quoted\\" graphics\nliteral second line'
        ).replace("\n", "\r\n")
        self.parent_path.write_bytes(
            f"(kicad_symbol_lib (version 20251024) {parent})".encode()
        )
        schematic.embedded_symbol("Test:Part").update_from_library(
            self.reopen_parent(), "Parent"
        )
        expected = EXPECTED.replace(
            "new graphics", 'new \\"quoted\\" graphics\nliteral second line'
        ).replace("\n", "\r\n")
        self.assertEqual(
            schematic.to_bytes(),
            source.replace(CACHE.replace("\n", "\r\n"), expected, 1).encode(),
        )
        self.assertEqual(self.path.read_bytes(), source.encode())

    def test_unsupported_parent_delta_fails_before_memory_or_disk_changes(self) -> None:
        for parent in (
            PARENT.replace('(name "A")', '(name "RENAMED")'),
            PARENT.replace('(number "1")', '(number "9")'),
            PARENT.replace("(at 0 5.08 270)", "(at 1 5.08 270)"),
            PARENT.replace('(name "A")', '(hide yes) (name "A")'),
            PARENT.replace('(opaque "unchanged")', '(opaque "different")'),
            PARENT.replace('(symbol "Parent"', '(symbol "Parent" (extends "Base")', 1),
        ):
            with self.subTest(parent=parent):
                self.parent_path.write_text(
                    f"(kicad_symbol_lib (version 20251024) {parent})", encoding="utf-8"
                )
                with self.assertRaises(UnsupportedSchematicOperationError):
                    self.schematic.embedded_symbol("Test:Part").update_from_library(
                        self.reopen_parent(), "Parent"
                    )
                self.assertEqual(self.schematic.to_bytes(), SOURCE.encode())
                self.assertEqual(self.path.read_bytes(), SOURCE.encode())

    def test_missing_duplicate_and_malformed_cache_identity_fail_explicitly(
        self,
    ) -> None:
        for source, error in (
            (SOURCE.replace("(lib_symbols", "(not_cache", 1), InvalidSchematicError),
            (
                SOURCE.replace("(lib_symbols", "(lib_symbols) (lib_symbols", 1),
                AmbiguousEmbeddedSymbolError,
            ),
            (SOURCE.replace(OTHER, CACHE), AmbiguousEmbeddedSymbolError),
            (
                SOURCE.replace("Part_1_1", "Wrong_1_1", 1),
                UnsupportedSchematicOperationError,
            ),
        ):
            with self.subTest(source=source):
                self.path.write_bytes(source.encode())
                schematic = Project.open(self.directory).schematic().files[0]
                with self.assertRaises(error):
                    schematic.embedded_symbol("Test:Part").update_from_library(
                        self.parent, "Parent"
                    )
                self.assertEqual(schematic.to_bytes(), source.encode())

    def test_closed_parent_restore_fails_before_pending_or_disk_changes(self) -> None:
        for decision in ("discard", "close"):
            with self.subTest(decision=decision):
                parent = self.reopen_parent()
                if decision == "close":
                    parent.save()
                    parent.close()
                else:
                    parent.discard()
                with self.assertRaises(RuntimeError):
                    self.schematic.embedded_symbol("Test:Part").update_from_library(
                        parent, "Parent"
                    )
                self.assertEqual(self.schematic.to_bytes(), SOURCE.encode())
                self.assertEqual(self.path.read_bytes(), SOURCE.encode())
                self.assertFalse(self.project.is_modified)

    def test_captured_restore_intent_survives_parent_terminal_exit(self) -> None:
        self.schematic.embedded_symbol("Test:Part").update_from_library(
            self.parent, "Parent"
        )
        expected = self.schematic.to_bytes()
        self.parent.discard()
        self.project.save()
        self.assertEqual(self.path.read_bytes(), expected)
        self.assertFalse(self.project.is_modified)

    def test_unsupported_formats_and_parent_pin_add_remove_are_nonmutating(
        self,
    ) -> None:
        self.parent.symbol("Parent").body(1, 1).add_pin("3", "C", "passive", x=5, y=0)
        with self.assertRaises(UnsupportedSchematicOperationError):
            self.schematic.embedded_symbol("Test:Part").update_from_library(
                self.parent, "Parent"
            )
        self.reopen_parent()
        self.parent.symbol("Parent").body(1, 1).pin("2").delete()
        with self.assertRaises(UnsupportedSchematicOperationError):
            self.schematic.embedded_symbol("Test:Part").update_from_library(
                self.parent, "Parent"
            )
        self.parent_path.write_text(
            f"(kicad_symbol_lib (version 20250114) {PARENT})", encoding="utf-8"
        )
        with self.assertRaises(UnsupportedSchematicOperationError):
            self.schematic.embedded_symbol("Test:Part").update_from_library(
                self.reopen_parent(), "Parent"
            )
        self.path.write_bytes(SOURCE.replace("20260306", "20250114").encode())
        old = Project.open(self.directory).schematic().files[0]
        with self.assertRaises(UnsupportedSchematicOperationError):
            old.embedded_symbol("Test:Part").update_from_library(self.parent, "Parent")
        self.assertEqual(self.schematic.to_bytes(), SOURCE.encode())

    def test_missing_embedded_or_library_names_raise_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.schematic.embedded_symbol("Missing:Part")
        with self.assertRaises(KeyError):
            self.schematic.embedded_symbol("Test:Part").update_from_library(
                self.parent, "Missing"
            )

    def test_duplicate_parent_identity_does_not_select_first_source(self) -> None:
        self.parent_path.write_text(
            f"(kicad_symbol_lib (version 20251024) {PARENT} {PARENT})", encoding="utf-8"
        )
        with self.assertRaises(AmbiguousSymbolError):
            self.schematic.embedded_symbol("Test:Part").update_from_library(
                self.reopen_parent(), "Parent"
            )
        self.assertEqual(self.schematic.to_bytes(), SOURCE.encode())

    def test_native_materialization_recovers_independent_original_source(self) -> None:
        import shutil

        fixtures = Path(__file__).resolve().parents[1] / "fixtures/schematics"
        self.parent.discard()
        native = self.directory / "native"
        native.mkdir()
        for path in (fixtures / "embedded-restore").glob("*.kicad_*"):
            shutil.copyfile(path, native / path.name)
        project = Project.open(native / "cpNode-IOX.kicad_pro")
        schematic = project.schematic().files[0]
        parent = SymbolLibrary.open(native / "parent.kicad_sym")
        schematic.embedded_symbol("SPCoast:R").update_from_library(parent, "R")
        self.assertEqual(
            schematic.to_bytes(),
            (fixtures / "attribute-edit/cpNode-IOX.kicad_sch").read_bytes(),
        )
        self.assertIn(b'(symbol "R_1_0"', schematic.to_bytes())
        self.assertNotIn(b'(symbol "SPCoast:R_1_0"', schematic.to_bytes())

    def test_type_corrections_apply_to_any_placement_without_a_check(self) -> None:
        """Pin-type corrections are plain in-memory edits; no prediction, no proof."""
        for source in (
            SOURCE.replace("Test:Part", "Part"),
            SOURCE.replace('(unit 1) (uuid "first")', '(dnp yes) (uuid "first")', 1),
            SOURCE.replace('(unit 1) (uuid "first")', '(convert 2) (uuid "first")', 1),
        ):
            with self.subTest(source=source):
                self.path.write_bytes(source.encode())
                project = Project.open(self.directory)
                schematic = project.schematic().files[0]
                lib_id = "Part" if '"Part"' in source else "Test:Part"
                schematic.embedded_symbol(lib_id).update_from_library(
                    self.parent, "Parent"
                )
                self.assertIn(b"pin passive", schematic.to_bytes())
                self.assertTrue(project.is_modified)
                self.assertEqual(self.path.read_bytes(), source.encode())
                project.discard()


if __name__ == "__main__":
    unittest.main()
