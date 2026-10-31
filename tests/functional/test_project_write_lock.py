"""Project write lock/guard hooks (#27).

Native KiCad 10.0.1 include/lockfile.h:54-55 and common/wildcards_and_files_ext.cpp:126-127
use "~" plus the full original filename and ".lck", not donor basename guesses.
No lock acquisition/deletion or implicit pcbnew host detection is provided.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import patch

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
        (self.root / "board.kicad_sch").write_text(
            "(kicad_sch (version 20260306))", encoding="utf-8"
        )

    def open_project(self) -> Project:
        return Project.open(self.root)


class LockDetectionTests(LockCase):
    def test_lock_path_and_unlocked_by_default(self) -> None:
        project = self.open_project()
        self.assertEqual(
            project.lock_file, (self.root / "~board.kicad_pro.lck").resolve()
        )
        self.assertFalse(project.is_locked)
        project.ensure_writes_allowed()  # no raise

    def test_lock_file_presence(self) -> None:
        (self.root / "~board.kicad_pro.lck").write_text("kicad", encoding="utf-8")
        project = self.open_project()
        self.assertTrue(project.is_locked)

    def test_locked_blocks_writes(self) -> None:
        (self.root / "~board.kicad_pro.lck").write_text("kicad", encoding="utf-8")
        project = self.open_project()
        with self.assertRaises(ProjectWriteBlockedError) as cm:
            project.ensure_writes_allowed()
        self.assertIsInstance(cm.exception, PermissionError)
        self.assertIn("~board.kicad_pro.lck", str(cm.exception))
        self.assertIn("KiCad", str(cm.exception))

    def test_dry_run_allows_preview_when_locked(self) -> None:
        (self.root / "~board.kicad_pro.lck").write_text("kicad", encoding="utf-8")
        project = self.open_project()
        project.ensure_writes_allowed(dry_run=True)  # no raise

    def test_explicit_host_assertion_bypasses_only_the_guard_query(self) -> None:
        (self.root / "~board.kicad_pro.lck").write_text("kicad", encoding="utf-8")
        project = self.open_project()
        self.assertTrue(project.is_locked)
        project.ensure_writes_allowed(inside_kicad=True)

    def test_write_is_permitted_matrix(self) -> None:
        project = self.open_project()
        self.assertTrue(project.write_is_permitted())
        (self.root / "~board.kicad_pro.lck").write_text("kicad", encoding="utf-8")
        self.assertFalse(project.write_is_permitted())
        self.assertTrue(project.write_is_permitted(inside_kicad=True))

    def test_donor_basename_lock_is_not_a_compatibility_alias(self) -> None:
        (self.root / "board.lck").write_bytes(b"not a native KiCad lock")
        project = self.open_project()
        self.assertFalse(project.is_locked)
        self.assertTrue(project.write_is_permitted())

    def test_any_native_lock_presence_including_dangling_link_is_reported(
        self,
    ) -> None:
        lock = self.root / "~board.kicad_pro.lck"
        lock.symlink_to(self.root / "missing")
        project = self.open_project()
        self.assertTrue(project.is_locked)
        project.save()
        self.assertTrue(lock.is_symlink())
        self.assertFalse((self.root / "board-backups").exists())

    def test_importable_pcbnew_does_not_authorize_filesystem_persistence(self) -> None:
        lock = self.root / "~board.kicad_pro.lck"
        lock.write_bytes(b"peer owns unsaved buffers")
        project = self.open_project()
        original = project.project_file.read_bytes()
        with patch.dict(sys.modules, {"pcbnew": ModuleType("pcbnew")}):
            self.assertFalse(project.write_is_permitted())
            project.ensure_writes_allowed(inside_kicad=True)
        self.assertEqual(project.project_file.read_bytes(), original)
        self.assertEqual(lock.read_bytes(), b"peer owns unsaved buffers")
        self.assertFalse((self.root / "board-backups").exists())


if __name__ == "__main__":
    unittest.main()
