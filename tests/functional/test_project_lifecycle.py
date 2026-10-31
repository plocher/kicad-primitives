"""Project save, close, and discard through public artifact seams (ADR 0011 D5).

``project.save()`` saves every changed document the project owns and nothing
else: it runs no KiCad, writes no backup, and checks no lock.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.projects import Project, ProjectUnsavedError
from kicad_primitives.schematics import (
    SchematicConflictError,
    SchematicSaveError,
    UnsupportedSchematicOperationError,
)
from tests.functional.test_schematic_editing import SOURCE

EDITED = SOURCE.replace(b'"10K"', b'"22K"')


class ProjectCase(unittest.TestCase):
    """Disposable one-sheet project; hierarchy() adds a child sheet file."""

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.pro = self.root / "board.kicad_pro"
        self.pro.write_bytes(b'{"meta":{"filename":"board.kicad_pro"},"opaque":1}')
        self.sch = self.root / "board.kicad_sch"
        self.sch.write_bytes(SOURCE)

    def hierarchy(self) -> tuple[Project, Path]:
        """Create a root with one child sheet file in a subdirectory."""
        self.sch.write_bytes(
            SOURCE.replace(
                b"(generator eeschema)",
                b'(generator eeschema) (sheet (at 0 0) (size 1 1) (property "Sheetfile" "sub/child.kicad_sch"))',
            )
        )
        child = self.root / "sub/child.kicad_sch"
        child.parent.mkdir()
        child.write_bytes(SOURCE.replace(b"R1", b"R2").replace(b"uuid-r1", b"uuid-r2"))
        return Project.open(self.pro), child

    def snapshot(self) -> dict[Path, tuple[bytes, int, int]]:
        return {
            path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
            for path in self.root.rglob("*")
            if path.is_file()
        }


class ProjectLifecycleTests(ProjectCase):
    def test_clean_open_and_close_write_nothing(self) -> None:
        before = self.snapshot()
        project = Project.open(self.pro)
        project.schematic().files[0].symbol("R1").attribute("Value")
        project.save()
        project.close()
        self.assertTrue(project.is_closed)
        self.assertEqual(self.snapshot(), before)

    def test_save_writes_changed_sheet_files_only_and_nothing_else(self) -> None:
        project, child = self.hierarchy()
        (self.root / "~board.kicad_pro.lck").write_bytes(b"peer lock")
        root_file, _child_file = project.schematic().files
        child_before = (
            child.read_bytes(),
            child.stat().st_ino,
            child.stat().st_mtime_ns,
        )
        root_file.symbol("R1").set_attribute("Value", "22K")
        with patch(
            "subprocess.run", side_effect=AssertionError("save executed a command")
        ):
            project.save()
        self.assertIn(b'"22K"', self.sch.read_bytes())
        self.assertEqual(
            (child.read_bytes(), child.stat().st_ino, child.stat().st_mtime_ns),
            child_before,
        )
        self.assertFalse(project.is_modified)
        self.assertFalse((self.root / "board-backups").exists())
        self.assertEqual(
            (self.root / "~board.kicad_pro.lck").read_bytes(), b"peer lock"
        )

    def test_dirty_close_saves_then_closes(self) -> None:
        project = Project.open(self.pro)
        project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        project.close()
        self.assertTrue(project.is_closed)
        self.assertEqual(self.sch.read_bytes(), EDITED)

    def test_failed_close_raises_and_stays_open_with_pending_changes(self) -> None:
        project = Project.open(self.pro)
        sheet = project.schematic().files[0]
        sheet.symbol("R1").set_attribute("Value", "22K")
        self.sch.write_bytes(SOURCE + b"\n")
        with self.assertRaises(SchematicSaveError) as caught:
            project.close()
        self.assertEqual(
            [(r.path, r.status) for r in caught.exception.results],
            [(self.sch, "conflict")],
        )
        self.assertFalse(project.is_closed)
        self.assertTrue(project.is_modified)
        self.assertEqual(self.sch.read_bytes(), SOURCE + b"\n")

    def test_with_block_saves_on_normal_exit_and_discards_on_exception(
        self,
    ) -> None:
        with Project.open(self.pro) as project:
            project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        self.assertTrue(project.is_closed)
        self.assertEqual(self.sch.read_bytes(), EDITED)
        with self.assertRaises(KeyError), Project.open(self.pro) as project:
            project.schematic().files[0].symbol("R1").set_attribute("Value", "33K")
            raise KeyError("client failure")
        self.assertTrue(project.is_closed)
        self.assertEqual(self.sch.read_bytes(), EDITED)

    def test_discard_exits_without_io_and_rejects_owned_operational_handles(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic()
        sheet = schematic.files[0]
        placed = sheet.symbol("R1")
        attribute = placed.attribute("Value")
        placed.set_attribute("Value", "pending")
        before = self.snapshot()
        project.discard()
        project.close()
        self.assertEqual(attribute.value, "10K")
        self.assertEqual(self.snapshot(), before)
        for action in (
            lambda: project.schematic(),
            lambda: project.save(),
            lambda: schematic.save(),
            lambda: schematic.files,
            lambda: sheet.save(),
            lambda: sheet.to_bytes(),
            lambda: sheet.symbol("R1"),
            lambda: placed.set_attribute("Value", "late"),
        ):
            with self.assertRaises(RuntimeError):
                action()

    def test_partial_failure_saves_what_it_can_and_a_later_save_finishes(
        self,
    ) -> None:
        project, child_path = self.hierarchy()
        root_file, child_file = project.schematic().files
        root_file.symbol("R1").set_attribute("Value", "22K")
        child_file.symbol("R2").set_attribute("Value", "33K")
        child_original = child_path.read_bytes()
        child_path.write_bytes(child_original + b"\n")
        with self.assertRaises(SchematicSaveError) as caught:
            project.save()
        statuses = {r.path: r.status for r in caught.exception.results}
        self.assertEqual(statuses, {child_path: "conflict", self.sch: "written"})
        self.assertFalse(root_file.is_modified)
        self.assertTrue(child_file.is_modified)
        self.assertEqual(child_path.read_bytes(), child_original + b"\n")
        child_path.write_bytes(child_original)
        project.save()
        self.assertFalse(project.is_modified)
        self.assertIn(b'"33K"', child_path.read_bytes())

    def test_terminal_project_rejects_retained_embedded_and_placed_queries(
        self,
    ) -> None:
        from kicad_primitives.symbols import SymbolLibrary

        self.sch.write_bytes(
            SOURCE.replace(
                b"(generator eeschema)",
                b'(generator eeschema) (lib_symbols (symbol "Device:R"))',
            )
        )
        parent_path = self.root / "Parent.kicad_sym"
        parent_path.write_bytes(b'(kicad_symbol_lib (version 20251024) (symbol "R"))')
        parent = SymbolLibrary.open(parent_path)
        project = Project.open(self.pro)
        sheet = project.schematic().files[0]
        embedded = sheet.embedded_symbol("Device:R")
        placed = sheet.symbol("R1")
        project.discard()
        for action in (
            lambda: embedded.restore_from(parent, "R"),
            lambda: placed.attribute("Value"),
            lambda: sheet.embedded_symbols,
            lambda: project.erc(),
            lambda: project.schematic_files(),
        ):
            with self.assertRaises(RuntimeError):
                action()
        parent.discard()

    def test_save_ignores_files_that_were_never_opened(self) -> None:
        project, child = self.hierarchy()
        before = self.snapshot()
        os.utime(child, None)
        project.save()
        project.close()
        after = self.snapshot()
        self.assertEqual(
            {p: v[:2] for p, v in after.items()}, {p: v[:2] for p, v in before.items()}
        )


class OnCloseTests(ProjectCase):
    """KiCad's close-project dialog: save all, do not save, or cancel."""

    def test_on_close_save_is_the_default(self) -> None:
        self.assertEqual(Project.open(self.pro).on_close, "save")

    def test_on_close_discard_drops_unsaved_changes(self) -> None:
        project = Project.open(self.pro, on_close="discard")
        project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        project.close()
        self.assertTrue(project.is_closed)
        self.assertEqual(self.sch.read_bytes(), SOURCE)

    def test_on_close_raise_names_unsaved_files_and_stays_open(self) -> None:
        _, child = self.hierarchy()
        project = Project.open(self.pro, on_close="raise")
        _root_file, child_file = project.schematic().files
        child_file.symbol("R2").set_attribute("Value", "33K")
        with self.assertRaises(ProjectUnsavedError) as caught:
            project.close()
        self.assertEqual(caught.exception.unsaved, (child,))
        self.assertFalse(project.is_closed)
        child_file.save()
        project.close()
        self.assertTrue(project.is_closed)
        self.assertIn(b'"33K"', child.read_bytes())
        clean = Project.open(self.pro, on_close="raise")
        clean.schematic()
        clean.close()
        self.assertTrue(clean.is_closed)

    def test_with_block_applies_on_close_and_discards_on_exception(self) -> None:
        with (
            self.assertRaises(ProjectUnsavedError),
            Project.open(self.pro, on_close="raise") as project,
        ):
            project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        self.assertFalse(project.is_closed)
        project.discard()
        with self.assertRaises(KeyError), Project.open(self.pro) as project:
            project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
            raise KeyError("client failure")
        self.assertEqual(self.sch.read_bytes(), SOURCE)

    def test_invalid_on_close_fails_at_open(self) -> None:
        with self.assertRaises(ValueError):
            Project.open(self.pro, on_close="maybe")  # type: ignore[arg-type]


class SchematicRevertTests(ProjectCase):
    def test_revert_reloads_every_sheet_file_and_keeps_identity(self) -> None:
        project, child = self.hierarchy()
        schematic = project.schematic()
        root_file, child_file = schematic.files
        old = child_file.symbol("R2")
        root_file.symbol("R1").set_attribute("Value", "22K")
        old.set_attribute("Value", "33K")
        schematic.revert()
        self.assertIs(project.schematic(), schematic)
        self.assertEqual(schematic.files, (root_file, child_file))
        self.assertFalse(schematic.is_modified)
        self.assertEqual(child_file.to_bytes(), child.read_bytes())
        with self.assertRaises(UnsupportedSchematicOperationError):
            old.set_attribute("Value", "44K")
        child_file.symbol("R2").set_attribute("Value", "44K")
        self.assertTrue(schematic.is_modified)

    def test_revert_refuses_any_changed_file_and_changes_nothing(self) -> None:
        project, child = self.hierarchy()
        schematic = project.schematic()
        root_file, _child_file = schematic.files
        root_file.symbol("R1").set_attribute("Value", "22K")
        child.write_bytes(child.read_bytes() + b"\n")
        with self.assertRaises(SchematicConflictError):
            schematic.revert()
        self.assertTrue(root_file.is_modified)
        self.assertEqual(root_file.symbol("R1").value, "22K")

    def test_revert_walks_the_trees_again(self) -> None:
        project, _child = self.hierarchy()
        schematic = project.schematic()
        self.assertEqual(len(schematic.files), 2)
        # Another tool saved a root without the child sheet; revert after a
        # save of ours picks up the disk state we wrote, then the new tree.
        root_file = schematic.files[0]
        flat = SOURCE
        self.sch.write_bytes(flat)
        root_file._mark_saved(flat)  # Pretend our last save wrote this.
        schematic.revert()
        self.assertEqual(schematic.files, (root_file,))
        self.assertEqual(root_file.sheet_symbols, ())


if __name__ == "__main__":
    unittest.main()
