"""SheetFile layer-0 lifecycle: open, modify, validate, save, revert, discard, close.

ADR 0011 D1 and D6. A sheet file is one ``.kicad_sch`` file. Its save writes
only that file, runs no KiCad, and checks no lock. Its revert reloads from
disk while the fingerprint still matches.
"""

import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import Project
from kicad_primitives.schematics import (
    InvalidSchematicError,
    SchematicConflictError,
    SchematicLifecycleError,
    SheetFile,
    UnsupportedSchematicOperationError,
)
from tests.functional.test_schematic_editing import SOURCE

EDITED = SOURCE.replace(b'"10K"', b'"22K"')


class SheetFileLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.path = self.directory / "board.kicad_sch"
        self.path.write_bytes(SOURCE)

    def test_open_reads_one_file_outside_a_project(self) -> None:
        sheet = SheetFile.open(self.path)
        self.assertEqual(sheet.path, self.path)
        self.assertEqual(sheet.symbol("R1").value, "10K")
        self.assertFalse(sheet.is_modified)
        self.assertFalse(sheet.is_closed)
        for bad in (self.directory / "missing.kicad_sch", self.directory / "x.txt"):
            with self.subTest(bad=bad), self.assertRaises(InvalidSchematicError):
                if bad.suffix == ".txt":
                    bad.write_text("(kicad_sch)")
                SheetFile.open(bad)

    def test_save_writes_changes_only_and_keeps_mode(self) -> None:
        self.path.chmod(0o640)
        sheet = SheetFile.open(self.path)
        before = self.path.stat()
        sheet.save()
        self.assertEqual(self.path.stat().st_ino, before.st_ino)
        self.assertEqual(self.path.stat().st_mtime_ns, before.st_mtime_ns)
        sheet.symbol("R1").set_attribute("Value", "22K")
        self.assertTrue(sheet.is_modified)
        self.assertEqual(self.path.read_bytes(), SOURCE)
        sheet.save()
        self.assertEqual(self.path.read_bytes(), EDITED)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertFalse(sheet.is_modified)

    def test_conflict_is_never_overwritten_unless_asked(self) -> None:
        sheet = SheetFile.open(self.path)
        sheet.symbol("R1").set_attribute("Value", "22K")
        foreign = SOURCE + b"\n"
        self.path.write_bytes(foreign)
        with self.assertRaises(SchematicConflictError):
            sheet.save()
        self.assertEqual(self.path.read_bytes(), foreign)
        self.assertTrue(sheet.is_modified)
        sheet.save(overwrite=True)
        self.assertEqual(self.path.read_bytes(), EDITED)
        self.assertFalse(sheet.is_modified)
        self.path.write_bytes(SOURCE)
        sheet.symbol("R1").set_attribute("Value", "33K")
        with self.assertRaises(SchematicConflictError):
            sheet.save()

    def test_validate_rejects_read_only_formats_without_writing(self) -> None:
        SheetFile.open(self.path).validate()
        old = SOURCE.replace(b"20260306", b"20250114")
        self.path.write_bytes(old)
        sheet = SheetFile.open(self.path)
        with self.assertRaises(UnsupportedSchematicOperationError):
            sheet.validate()
        self.assertEqual(self.path.read_bytes(), old)

    def test_revert_reloads_from_disk_and_stales_old_handles(self) -> None:
        sheet = SheetFile.open(self.path)
        old = sheet.symbol("R1")
        old.set_attribute("Value", "22K")
        sheet.revert()
        self.assertFalse(sheet.is_modified)
        self.assertEqual(sheet.to_bytes(), SOURCE)
        with self.assertRaises(UnsupportedSchematicOperationError):
            old.set_attribute("Value", "33K")
        fresh = sheet.symbol("R1")
        self.assertIsNot(fresh, old)
        fresh.set_attribute("Value", "33K")
        self.assertTrue(sheet.is_modified)
        self.assertEqual(self.path.read_bytes(), SOURCE)

    def test_revert_refuses_a_changed_or_missing_file(self) -> None:
        sheet = SheetFile.open(self.path)
        sheet.symbol("R1").set_attribute("Value", "22K")
        self.path.write_bytes(SOURCE + b"\n")
        with self.assertRaises(SchematicConflictError):
            sheet.revert()
        self.assertTrue(sheet.is_modified)
        self.assertEqual(sheet.symbol("R1").value, "22K")
        self.path.unlink()
        with self.assertRaises(SchematicConflictError):
            sheet.revert()

    def test_close_saves_discard_does_not_and_both_end_the_artifact(self) -> None:
        sheet = SheetFile.open(self.path)
        sheet.symbol("R1").set_attribute("Value", "22K")
        sheet.discard()
        sheet.discard()
        self.assertTrue(sheet.is_closed)
        self.assertEqual(self.path.read_bytes(), SOURCE)
        for action in (sheet.to_bytes, sheet.save, sheet.revert, sheet.validate):
            with (
                self.subTest(action=action),
                self.assertRaises(SchematicLifecycleError),
            ):
                action()
        sheet = SheetFile.open(self.path)
        sheet.symbol("R1").set_attribute("Value", "22K")
        sheet.close()
        sheet.close()
        self.assertEqual(self.path.read_bytes(), EDITED)

    def test_with_block_closes_on_exit_and_discards_on_exception(self) -> None:
        with SheetFile.open(self.path) as sheet:
            sheet.symbol("R1").set_attribute("Value", "22K")
        self.assertTrue(sheet.is_closed)
        self.assertEqual(self.path.read_bytes(), EDITED)
        with self.assertRaises(KeyError), SheetFile.open(self.path) as sheet:
            sheet.symbol("R1").set_attribute("Value", "33K")
            raise KeyError("client failure")
        self.assertEqual(self.path.read_bytes(), EDITED)


class ProjectOwnedSheetFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        (self.directory / "board.kicad_pro").write_text("{}", encoding="utf-8")
        self.root = self.directory / "board.kicad_sch"
        self.root.write_bytes(
            SOURCE.replace(
                b"(generator eeschema)",
                b'(generator eeschema) (sheet (at 0 0) (size 1 1) (property "Sheetfile" "child.kicad_sch"))',
            )
        )
        self.child = self.directory / "child.kicad_sch"
        self.child.write_bytes(SOURCE.replace(b"R1", b"R2"))

    def test_owned_sheet_file_save_writes_only_itself(self) -> None:
        project = Project.open(self.directory)
        root, child = project.schematic().files
        root_before = root.to_bytes()
        root.symbol("R1").set_attribute("Value", "22K")
        child.symbol("R2").set_attribute("Value", "33K")
        child.save()
        self.assertEqual(self.root.read_bytes(), root_before)
        self.assertIn(b'"33K"', self.child.read_bytes())
        self.assertTrue(root.is_modified)
        self.assertFalse(child.is_modified)

    def test_owned_sheet_file_close_and_discard_are_not_supported_yet(self) -> None:
        project = Project.open(self.directory)
        root = project.schematic().files[0]
        for action in (root.close, root.discard):
            with (
                self.subTest(action=action),
                self.assertRaises(UnsupportedSchematicOperationError),
            ):
                action()
        self.assertFalse(root.is_closed)
        project.discard()
        self.assertTrue(root.is_closed)


if __name__ == "__main__":
    unittest.main()
