"""Schematic.save(): the D3 write set and the D4 failure policy (ADR 0011).

Only changed sheet files are written, children before parents. Problems found
before any write stop the save with nothing written. Conflicts are never
retried or overwritten unless asked. Short-lived errors get one retry at the
end. Lasting errors stop the save at once.
"""

import errno
import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.projects import Project
from kicad_primitives.schematics import Schematic, SchematicSaveError, SheetFile
from tests.functional.test_schematic_editing import SOURCE


class SchematicSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        (self.directory / "board.kicad_pro").write_text("{}", encoding="utf-8")
        self.root_path = self.directory / "board.kicad_sch"
        self.root_path.write_bytes(
            SOURCE.replace(
                b"(generator eeschema)",
                b"(generator eeschema)"
                b' (sheet (at 0 0) (size 1 1) (property "Sheetfile" "sub/a.kicad_sch"))'
                b' (sheet (at 0 9) (size 1 1) (property "Sheetfile" "sub/b.kicad_sch"))',
            )
        )
        (self.directory / "sub").mkdir()
        self.a_path = self.directory / "sub/a.kicad_sch"
        self.a_path.write_bytes(SOURCE.replace(b"R1", b"R2"))
        self.b_path = self.directory / "sub/b.kicad_sch"
        self.b_path.write_bytes(SOURCE.replace(b"R1", b"R3"))
        self.project = Project.open(self.directory)
        self.schematic = self.project.schematic()
        self.root, self.a, self.b = self.schematic.files

    def edit_all(self) -> None:
        self.root.symbol("R1").set_attribute("Value", "1K")
        self.a.symbol("R2").set_attribute("Value", "2K")
        self.b.symbol("R3").set_attribute("Value", "3K")

    def disk(self) -> dict[Path, tuple[bytes, int, int]]:
        return {
            path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
            for path in (self.root_path, self.a_path, self.b_path)
        }

    def statuses(self, error: SchematicSaveError) -> dict[Path, str]:
        return {result.path: result.status for result in error.results}

    def test_only_changed_files_are_written_children_first(self) -> None:
        self.assertIsInstance(self.schematic, Schematic)
        before = self.disk()
        self.schematic.save()
        self.assertEqual(self.disk(), before)
        self.root.symbol("R1").set_attribute("Value", "1K")
        self.b.symbol("R3").set_attribute("Value", "3K")
        order: list[Path] = []
        real_replace = os.replace

        def record(source: Path, target: Path) -> None:
            order.append(Path(target))
            real_replace(source, target)

        with patch("kicad_primitives._symbol_persist.os.replace", side_effect=record):
            self.schematic.save()
        self.assertEqual(order, [self.b_path, self.root_path])
        self.assertEqual(self.disk()[self.a_path], before[self.a_path])
        self.assertFalse(self.schematic.is_modified)

    def test_invalid_content_writes_nothing(self) -> None:
        old = SOURCE.replace(b"R1", b"R3").replace(b"20260306", b"20250114")
        self.b_path.write_bytes(old)
        project = Project.open(self.directory)
        root, _a, b = project.schematic().files
        root.symbol("R1").set_attribute("Value", "1K")
        # Public edits refuse read-only formats; force the flag to reach the gate.
        object.__setattr__(b, "_modified", True)
        before = self.disk()
        with self.assertRaises(SchematicSaveError) as caught:
            project.schematic().validate()
        self.assertEqual(self.statuses(caught.exception)[self.b_path], "failed")
        with self.assertRaises(SchematicSaveError) as caught:
            project.save()
        self.assertEqual(
            self.statuses(caught.exception),
            {self.b_path: "failed", self.root_path: "unsaved"},
        )
        self.assertEqual(self.disk(), before)
        self.assertTrue(root.is_modified)

    def test_unwritable_targets_found_before_any_write_write_nothing(self) -> None:
        cases = {
            "read-only file": lambda: self.a_path.chmod(0o444),
            "read-only directory": lambda: self.a_path.parent.chmod(0o555),
            "hard link": lambda: os.link(self.a_path, self.directory / "alias.sch"),
        }
        undo = {
            "read-only file": lambda: self.a_path.chmod(0o644),
            "read-only directory": lambda: self.a_path.parent.chmod(0o755),
            "hard link": lambda: (self.directory / "alias.sch").unlink(),
        }
        self.edit_all()
        for name, apply in cases.items():
            with self.subTest(name=name):
                apply()
                try:
                    before = self.disk()
                    with self.assertRaises(SchematicSaveError) as caught:
                        self.schematic.save()
                    self.assertEqual(
                        self.statuses(caught.exception)[self.a_path], "failed"
                    )
                    self.assertEqual(self.disk(), before)
                    self.assertTrue(all(f.is_modified for f in self.schematic.files))
                finally:
                    undo[name]()
        self.schematic.save()
        self.assertFalse(self.schematic.is_modified)

    def test_symlinked_sheet_file_is_not_dereferenced(self) -> None:
        target = self.directory / "target.kicad_sch"
        self.b_path.rename(target)
        self.b_path.symlink_to(target)
        project = Project.open(self.directory)
        project.schematic().files[2].symbol("R3").set_attribute("Value", "3K")
        with self.assertRaises(SchematicSaveError):
            project.save()
        self.assertTrue(self.b_path.is_symlink())
        self.assertNotIn(b'"3K"', target.read_bytes())

    def test_conflict_stays_unsaved_unless_overwrite_is_asked(self) -> None:
        self.edit_all()
        foreign = self.a_path.read_bytes() + b"\n"
        self.a_path.write_bytes(foreign)
        with self.assertRaises(SchematicSaveError) as caught:
            self.schematic.save()
        self.assertEqual(
            self.statuses(caught.exception),
            {
                self.a_path: "conflict",
                self.b_path: "written",
                self.root_path: "written",
            },
        )
        self.assertEqual(self.a_path.read_bytes(), foreign)
        self.assertTrue(self.a.is_modified)
        self.schematic.save(overwrite=True)
        self.assertIn(b'"2K"', self.a_path.read_bytes())
        self.assertFalse(self.schematic.is_modified)

    def test_short_lived_error_is_retried_once_at_the_end(self) -> None:
        self.edit_all()
        real_replace = os.replace
        failures = {"left": 1}

        def busy_once(source: Path, target: Path) -> None:
            if Path(target) == self.a_path and failures["left"]:
                failures["left"] -= 1
                raise BlockingIOError(errno.EAGAIN, "busy")
            real_replace(source, target)

        with (
            patch("kicad_primitives._symbol_persist.os.replace", side_effect=busy_once),
            patch("kicad_primitives._schematic_save.time.sleep") as sleep,
        ):
            self.schematic.save()
        sleep.assert_called_once()
        self.assertFalse(self.schematic.is_modified)
        self.assertEqual(list(self.directory.rglob(".*.tmp")), [])

    def test_short_lived_error_that_persists_is_reported_after_one_retry(
        self,
    ) -> None:
        self.edit_all()
        real_replace = os.replace
        calls: list[Path] = []

        def always_busy(source: Path, target: Path) -> None:
            calls.append(Path(target))
            if Path(target) == self.a_path:
                raise InterruptedError(errno.EINTR, "interrupted")
            real_replace(source, target)

        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace", side_effect=always_busy
            ),
            patch("kicad_primitives._schematic_save.time.sleep"),
            self.assertRaises(SchematicSaveError) as caught,
        ):
            self.schematic.save()
        self.assertEqual(calls.count(self.a_path), 2)
        self.assertEqual(
            self.statuses(caught.exception),
            {self.a_path: "failed", self.b_path: "written", self.root_path: "written"},
        )
        self.assertTrue(self.a.is_modified)

    def test_permission_change_during_write_is_reported_without_retry(self) -> None:
        self.edit_all()
        real_replace = os.replace
        calls: list[Path] = []

        def denied(source: Path, target: Path) -> None:
            calls.append(Path(target))
            if Path(target) == self.a_path:
                raise PermissionError(errno.EACCES, "denied")
            real_replace(source, target)

        with (
            patch("kicad_primitives._symbol_persist.os.replace", side_effect=denied),
            self.assertRaises(SchematicSaveError) as caught,
        ):
            self.schematic.save()
        self.assertEqual(calls.count(self.a_path), 1)
        self.assertEqual(self.statuses(caught.exception)[self.a_path], "failed")
        self.assertEqual(self.statuses(caught.exception)[self.root_path], "written")

    def test_lasting_or_unknown_error_stops_the_save_at_once(self) -> None:
        real_replace = os.replace
        for error in (OSError(errno.ENOSPC, "disk full"), OSError("unknown")):
            with self.subTest(error=error):
                project = Project.open(self.directory)
                root, a, b = project.schematic().files
                for sheet, ref in ((root, "R1"), (a, "R2"), (b, "R3")):
                    sheet.symbol(ref).set_attribute("Value", f"{id(error)}")
                before = self.disk()

                def fail_a(source: Path, target: Path, error: OSError = error) -> None:
                    if Path(target) == self.a_path:
                        raise error
                    real_replace(source, target)

                with (
                    patch(
                        "kicad_primitives._symbol_persist.os.replace",
                        side_effect=fail_a,
                    ),
                    self.assertRaises(SchematicSaveError) as caught,
                ):
                    project.save()
                # Write order is a, b, root: the failure on a stops b and root.
                self.assertEqual(
                    self.statuses(caught.exception),
                    {
                        self.a_path: "failed",
                        self.b_path: "unsaved",
                        self.root_path: "unsaved",
                    },
                )
                self.assertEqual(self.disk(), before)
                self.assertTrue(all(f.is_modified for f in (root, a, b)))
                project.discard()

    def test_saved_file_mode_is_kept(self) -> None:
        self.root_path.chmod(0o640)
        self.root.symbol("R1").set_attribute("Value", "1K")
        self.project.save()
        self.assertEqual(stat.S_IMODE(self.root_path.stat().st_mode), 0o640)

    def test_layer_zero_sheet_file_save_runs_no_hierarchy_policy(self) -> None:
        sheet = SheetFile.open(self.a_path)
        sheet.symbol("R2").set_attribute("Value", "2K")
        sheet.save()
        self.assertIn(b'"2K"', self.a_path.read_bytes())
        sheet.close()


if __name__ == "__main__":
    unittest.main()
