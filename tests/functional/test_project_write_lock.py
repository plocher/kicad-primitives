"""Project write lock/guard hooks (#27).

Donor behavior from jBOM kicad_runtime / ProjectContext lock_file, without
CLI stderr chatter or hard-wired pcbnew product coupling.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import (
    Project,
    ProjectWriteBlockedError,
)


class LockCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="kp_lock_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "board.kicad_pro").write_text(
            json.dumps({"meta": {"version": 1}}), encoding="utf-8"
        )

    def open_project(self) -> Project:
        return Project.open(self.root)


class LockDetectionTests(LockCase):
    def test_lock_path_and_unlocked_by_default(self) -> None:
        project = self.open_project()
        self.assertEqual(project.lock_file, (self.root / "board.lck").resolve())
        self.assertFalse(project.is_locked)
        project.ensure_writes_allowed()  # no raise

    def test_lock_file_presence(self) -> None:
        (self.root / "board.lck").write_text("kicad", encoding="utf-8")
        project = self.open_project()
        self.assertTrue(project.is_locked)

    def test_locked_blocks_writes(self) -> None:
        (self.root / "board.lck").write_text("kicad", encoding="utf-8")
        project = self.open_project()
        with self.assertRaises(ProjectWriteBlockedError) as cm:
            project.ensure_writes_allowed()
        self.assertIsInstance(cm.exception, PermissionError)
        self.assertIn("board.lck", str(cm.exception))
        self.assertIn("KiCad", str(cm.exception))

    def test_dry_run_allows_preview_when_locked(self) -> None:
        (self.root / "board.lck").write_text("kicad", encoding="utf-8")
        project = self.open_project()
        project.ensure_writes_allowed(dry_run=True)  # no raise

    def test_inside_kicad_bypasses_lock(self) -> None:
        (self.root / "board.lck").write_text("kicad", encoding="utf-8")
        project = self.open_project()
        project.ensure_writes_allowed(inside_kicad=True)

    def test_write_is_permitted_matrix(self) -> None:
        project = self.open_project()
        self.assertTrue(project.write_is_permitted())
        (self.root / "board.lck").write_text("kicad", encoding="utf-8")
        self.assertFalse(project.write_is_permitted())
        self.assertTrue(project.write_is_permitted(inside_kicad=True))


if __name__ == "__main__":
    unittest.main()
