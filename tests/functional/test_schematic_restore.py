"""Selected concrete cache restore through artifact objects, never a batch API."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.projects import Project, ProjectLifecycleError
from kicad_primitives.schematics import (
    AmbiguousEmbeddedSymbolError,
    InvalidSchematicError,
    SchematicVerificationError,
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
        embedded.restore_from(self.parent, "Parent")
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
        embedded.restore_from(self.reopen_parent(), "Parent")
        first = self.schematic.to_bytes()
        embedded.restore_from(self.reopen_parent(), "Parent")
        self.assertEqual(self.schematic.to_bytes(), first)

    def test_handles_remain_live_across_attributes_other_cache_and_revert(self) -> None:
        embedded = self.schematic.embedded_symbol("Test:Part")
        other = self.schematic.embedded_symbol("Test:Other")
        placed = self.schematic.symbol("R1")
        placed.set_attribute("MPN", "é" * 50)
        embedded.restore_from(self.parent, "Parent")
        placed.set_attribute("Value", "new placed value")
        second_parent = PARENT.replace("Parent", "Second").replace(
            "pin passive", "pin output", 1
        )
        second_parent = second_parent.replace("pin passive", "pin input", 1)
        self.parent_path.write_text(
            f"(kicad_symbol_lib (version 20251024) {second_parent})", encoding="utf-8"
        )
        other.restore_from(self.reopen_parent(), "Second")
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
        embedded.restore_from(self.reopen_parent(), "Parent")
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
        schematic.embedded_symbol("Test:Part").restore_from(
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
            PARENT.replace("pin passive", "pin power_in", 1),
            PARENT.replace('(opaque "unchanged")', '(opaque "different")'),
            PARENT.replace('(symbol "Parent"', '(symbol "Parent" (extends "Base")', 1),
        ):
            with self.subTest(parent=parent):
                self.parent_path.write_text(
                    f"(kicad_symbol_lib (version 20251024) {parent})", encoding="utf-8"
                )
                with self.assertRaises(UnsupportedSchematicOperationError):
                    self.schematic.embedded_symbol("Test:Part").restore_from(
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
                    schematic.embedded_symbol("Test:Part").restore_from(
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
                    self.schematic.embedded_symbol("Test:Part").restore_from(
                        parent, "Parent"
                    )
                self.assertEqual(self.schematic.to_bytes(), SOURCE.encode())
                self.assertEqual(self.path.read_bytes(), SOURCE.encode())
                self.assertFalse(self.project.is_modified)

    def test_captured_restore_intent_survives_parent_terminal_exit(self) -> None:
        self.schematic.embedded_symbol("Test:Part").restore_from(self.parent, "Parent")
        expected = self.schematic.to_bytes()
        self.parent.discard()
        self.project.save(kicad_cli=self.verifier())
        self.assertEqual(self.path.read_bytes(), expected)
        self.assertFalse(self.project.is_modified)

    def test_document_save_excludes_other_pending_restore_and_rejects_cache_variants(
        self,
    ) -> None:
        source = SOURCE.replace(
            "(version 20260306)",
            '(version 20260306) (sheet (at 0 0) (size 10 10) (property "Sheetfile" "child.kicad_sch"))',
            1,
        )
        self.path.write_bytes(source.encode())
        child_path = self.directory / "child.kicad_sch"
        child_source = (
            SOURCE.replace('"R1"', '"X1"')
            .replace('"R2"', '"X2"')
            .replace('"C1"', '"X3"')
        )
        child_path.write_bytes(child_source.encode())
        project = Project.open(self.directory)
        root, child = project.schematic().files
        root.symbol("R1").set_attribute("MPN", "root-only")
        child.embedded_symbol("Test:Part").restore_from(self.parent, "Parent")
        root.save(kicad_cli=self.verifier())
        self.assertFalse(root.is_modified)
        self.assertTrue(child.is_modified)
        self.assertEqual(child_path.read_bytes(), child_source.encode())
        with self.assertRaises(UnsupportedSchematicOperationError):
            project.save(kicad_cli=self.verifier())
        self.assertEqual(child_path.read_bytes(), child_source.encode())

    def test_unsupported_formats_and_parent_pin_add_remove_are_nonmutating(
        self,
    ) -> None:
        self.parent.symbol("Parent").body(1, 1).add_pin("3", "C", "passive", x=5, y=0)
        with self.assertRaises(UnsupportedSchematicOperationError):
            self.schematic.embedded_symbol("Test:Part").restore_from(
                self.parent, "Parent"
            )
        self.reopen_parent()
        self.parent.symbol("Parent").body(1, 1).pin("2").delete()
        with self.assertRaises(UnsupportedSchematicOperationError):
            self.schematic.embedded_symbol("Test:Part").restore_from(
                self.parent, "Parent"
            )
        self.parent_path.write_text(
            f"(kicad_symbol_lib (version 20250114) {PARENT})", encoding="utf-8"
        )
        with self.assertRaises(UnsupportedSchematicOperationError):
            self.schematic.embedded_symbol("Test:Part").restore_from(
                self.reopen_parent(), "Parent"
            )
        self.path.write_bytes(SOURCE.replace("20260306", "20250114").encode())
        old = Project.open(self.directory).schematic().files[0]
        with self.assertRaises(UnsupportedSchematicOperationError):
            old.embedded_symbol("Test:Part").restore_from(self.parent, "Parent")
        self.assertEqual(self.schematic.to_bytes(), SOURCE.encode())

    def test_cross_cache_placement_identity_ambiguity_is_nonmutating(self) -> None:
        for old, ambiguous in (
            ('"Reference" "C1"', '"Reference" "R1"'),
            ('(uuid "unrelated")', '(uuid "first")'),
        ):
            with self.subTest(identity=ambiguous):
                source = SOURCE.replace(old, ambiguous, 1).encode()
                self.path.write_bytes(source)
                project = Project.open(self.directory)
                schematic = project.schematic().files[0]
                with self.assertRaises(UnsupportedSchematicOperationError):
                    schematic.embedded_symbol("Test:Part").restore_from(
                        self.parent, "Parent"
                    )
                self.assertEqual(schematic.to_bytes(), source)
                self.assertEqual(self.path.read_bytes(), source)
                self.assertFalse(project.is_modified)
        with self.assertRaises(KeyError):
            self.schematic.embedded_symbol("Missing:Part")
        with self.assertRaises(KeyError):
            self.schematic.embedded_symbol("Test:Part").restore_from(
                self.parent, "Missing"
            )

    def verifier(self, mode: str = "correct") -> Path:
        cli = self.directory / "fake-cli"
        cli.write_text(
            f"""#!/usr/bin/env python3
import pathlib,sys
source = pathlib.Path(sys.argv[-1]).read_text()
pending = '(property "Value" "new default")' in source
mode = {mode!r}
types = ["passive", "passive"] if pending and mode != "missing-effect" else ["output", "input"]
other = ["output", "input"]
if pending and mode == "unrelated-type":
    other[0] = "passive"
libtypes = types if mode != "missing-libpart-effect" else ["output", "input"]
components = ''.join('(comp (ref '+ref+') (libsource (lib Test) (part '+part+')))' for ref,part in [('R1','Part'),('R2','Part'),('C1','Other')])
libparts = ''.join('(libpart (lib Test) (part '+part+') (pins '+''.join('(pin (num '+str(index+1)+') (name '+name+') (type '+typ+'))' for index,(name,typ) in enumerate(zip(['A','B'],ptypes)))+'))' for part,ptypes in [('Part',libtypes),('Other',other)])
nets = []
for index,name in enumerate(['signal-A','signal-B']):
    if pending and mode == "unrelated-net":
        name += "-drift"
    nodes = []
    for ref,ptypes in [('R1',types),('R2',types),('C1',other)]:
        if pending and mode == "missing-member" and ref == 'R2':
            continue
        nodes.append('(node (ref '+ref+') (pin '+str(index+1)+') (pinfunction '+['A','B'][index]+') (pintype '+ptypes[index]+'))')
    nets.append('(net (name "'+name+'") '+''.join(nodes)+')')
output = '(export (version E) (components '+components+') (libparts '+libparts+') (nets '+''.join(nets)+'))'
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(output)
""",
            encoding="utf-8",
        )
        cli.chmod(0o755)
        return cli

    def test_unqualified_type_correction_fails_before_pending_source_changes(
        self,
    ) -> None:
        source = SOURCE.replace("Test:Part", "Part").encode()
        self.path.write_bytes(source)
        project = Project.open(self.directory)
        schematic = project.schematic().files[0]
        with self.assertRaises(UnsupportedSchematicOperationError):
            schematic.embedded_symbol("Part").restore_from(self.parent, "Parent")
        self.assertEqual(schematic.to_bytes(), source)
        self.assertEqual(self.path.read_bytes(), source)
        self.assertFalse(project.is_modified)

    def test_exact_revert_clears_pending_restore_without_cli_or_replacement(
        self,
    ) -> None:
        embedded = self.schematic.embedded_symbol("Test:Part")
        embedded.restore_from(self.parent, "Parent")
        original_parent = CACHE.replace("Test:Part", "Parent").replace(
            "Part_1_1", "Parent_1_1"
        )
        self.parent_path.write_text(
            f"(kicad_symbol_lib (version 20251024) {original_parent})", encoding="utf-8"
        )
        embedded.restore_from(self.reopen_parent(), "Parent")
        self.assertEqual(self.schematic.to_bytes(), SOURCE.encode())
        self.assertFalse(self.project.is_modified)
        inode = self.path.stat().st_ino
        self.project.save(kicad_cli=self.directory / "not-needed")
        self.assertEqual(self.path.stat().st_ino, inode)

    def test_duplicate_parent_identity_does_not_select_first_source(self) -> None:
        self.parent_path.write_text(
            f"(kicad_symbol_lib (version 20251024) {PARENT} {PARENT})", encoding="utf-8"
        )
        with self.assertRaises(AmbiguousSymbolError):
            self.schematic.embedded_symbol("Test:Part").restore_from(
                self.reopen_parent(), "Parent"
            )
        self.assertEqual(self.schematic.to_bytes(), SOURCE.encode())

    def test_save_proves_all_placements_and_full_pin_types_then_resets_baseline(
        self,
    ) -> None:
        embedded = self.schematic.embedded_symbol("Test:Part")
        embedded.restore_from(self.parent, "Parent")
        self.schematic.symbol("R1").set_attribute("MPN", "mixed edit")
        self.parent.symbol("Parent").body(1, 1).pin("1").set(electrical_type="input")
        cli = self.verifier()
        self.project.save(kicad_cli=cli)
        self.assertEqual(self.path.read_bytes(), self.schematic.to_bytes())
        self.assertFalse(self.project.is_modified)
        self.schematic.symbol("R1").set_attribute("MPN", "second edit")
        self.schematic.save(kicad_cli=cli)
        self.assertFalse(self.project.is_modified)
        inode = self.path.stat().st_ino
        self.project.save(kicad_cli=self.directory / "not-needed")
        self.assertEqual(self.path.stat().st_ino, inode)

    def test_missing_intended_effect_or_unrelated_electrical_drift_blocks_save(
        self,
    ) -> None:
        for mode in (
            "missing-effect",
            "missing-libpart-effect",
            "unrelated-type",
            "unrelated-net",
            "missing-member",
        ):
            with self.subTest(mode=mode):
                self.path.write_bytes(SOURCE.encode())
                project = Project.open(self.directory)
                schematic = project.schematic().files[0]
                schematic.embedded_symbol("Test:Part").restore_from(
                    self.parent, "Parent"
                )
                inode = self.path.stat().st_ino
                with self.assertRaises(SchematicVerificationError):
                    project.save(kicad_cli=self.verifier(mode))
                self.assertEqual(self.path.read_bytes(), SOURCE.encode())
                self.assertEqual(self.path.stat().st_ino, inode)
                self.assertTrue(project.is_modified)

    def test_native_materialization_recovers_independent_original_source(self) -> None:
        import shutil

        fixtures = Path(__file__).resolve().parents[1] / "fixtures/schematics"
        self.parent.discard()
        for path in (fixtures / "embedded-restore").glob("*.kicad_*"):
            shutil.copyfile(path, self.directory / path.name)
        project = Project.open(self.directory / "cpNode-IOX.kicad_pro")
        schematic = project.schematic().files[0]
        parent = SymbolLibrary.open(self.directory / "parent.kicad_sym")
        schematic.embedded_symbol("SPCoast:R").restore_from(parent, "R")
        self.assertEqual(
            schematic.to_bytes(),
            (fixtures / "attribute-edit/cpNode-IOX.kicad_sch").read_bytes(),
        )
        self.assertIn(b'(symbol "R_1_0"', schematic.to_bytes())
        self.assertNotIn(b'(symbol "SPCoast:R_1_0"', schematic.to_bytes())

    def test_type_change_rejects_excluded_or_alternate_placements_before_mutation(
        self,
    ) -> None:
        for addition in (
            "(unit 2)",
            "(dnp yes)",
            "(convert 2)",
            '(pin "1" (alternate "X"))',
        ):
            with self.subTest(addition=addition):
                source = SOURCE.replace(
                    '(unit 1) (uuid "first")', f'{addition} (uuid "first")', 1
                )
                self.path.write_bytes(source.encode())
                schematic = Project.open(self.directory).schematic().files[0]
                with self.assertRaises(UnsupportedSchematicOperationError):
                    schematic.embedded_symbol("Test:Part").restore_from(
                        self.parent, "Parent"
                    )
                self.assertEqual(schematic.to_bytes(), source.encode())

    def test_late_exact_revert_preserves_explicit_reverse_restore_for_retry(
        self,
    ) -> None:
        original_path = self.directory / "original.kicad_sym"
        original_path.write_text(
            "(kicad_symbol_lib (version 20251024) "
            + CACHE.replace("Test:Part", "Original").replace("Part_1_1", "Original_1_1")
            + ")",
            encoding="utf-8",
        )
        original = SymbolLibrary.open(original_path)
        embedded = self.schematic.embedded_symbol("Test:Part")
        embedded.restore_from(self.parent, "Parent")
        frozen = self.schematic.to_bytes()
        real_replace = os.replace
        reverted = False

        def revert_after_source_write(source: Path, target: Path) -> None:
            nonlocal reverted
            real_replace(source, target)
            if target == self.schematic.path and not reverted:
                reverted = True
                embedded.restore_from(original, "Original")

        cli = self.verifier()
        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace",
                side_effect=revert_after_source_write,
            ),
            self.assertRaises(ProjectLifecycleError),
        ):
            self.project.save(kicad_cli=cli)
        self.assertTrue(reverted)
        self.assertEqual(self.path.read_bytes(), frozen)
        self.assertEqual(self.schematic.to_bytes(), SOURCE.encode())
        self.assertTrue(self.project.is_modified)
        self.project.save(kicad_cli=cli)
        self.assertEqual(self.path.read_bytes(), SOURCE.encode())
        self.assertFalse(self.project.is_modified)
        self.project.close()
