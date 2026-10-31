"""Native KiCad peer locks are queries, not write guards (ADR 0009, ADR 0011 D9).

Native KiCad 10.0.1 include/lockfile.h:54-55 and common/wildcards_and_files_ext.cpp:126-127
use "~" plus the full original filename and ".lck", not donor basename guesses.
No lock acquisition or deletion is provided, and no package write consults a lock.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import Project

SHEET = (
    '(kicad_sch (version 20260306) (uuid "00000000-0000-4000-8000-000000000001")'
    ' (sheet (at 0 0) (size 1 1) (uuid "00000000-0000-4000-8000-000000000002")'
    ' (property "Sheetfile" "child.kicad_sch")))'
)


class LockQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="kp_lock_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "board.kicad_pro").write_text(
            json.dumps({"meta": {"version": 1}}), encoding="utf-8"
        )
        (self.root / "board.kicad_sch").write_text(SHEET, encoding="utf-8")
        (self.root / "child.kicad_sch").write_text(
            "(kicad_sch (version 20260306))", encoding="utf-8"
        )

    def test_lock_path_and_unlocked_by_default(self) -> None:
        project = Project.open(self.root)
        self.assertEqual(project.lock_file, self.root / "~board.kicad_pro.lck")
        self.assertFalse(project.is_locked)

    def test_project_root_pcb_and_loaded_child_locks_are_reported(self) -> None:
        (self.root / "board.kicad_pcb").write_text("(kicad_pcb (version 20260206))")
        for name in ("board.kicad_pro", "board.kicad_sch", "board.kicad_pcb"):
            with self.subTest(name=name):
                lock = self.root / f"~{name}.lck"
                lock.write_text("kicad", encoding="utf-8")
                try:
                    self.assertTrue(Project.open(self.root).is_locked)
                finally:
                    lock.unlink()
        child_lock = self.root / "~child.kicad_sch.lck"
        child_lock.write_text("kicad", encoding="utf-8")
        project = Project.open(self.root)
        self.assertFalse(project.is_locked)  # The child is not loaded yet.
        project.schematic()
        self.assertTrue(project.is_locked)

    def test_dangling_link_lock_counts_and_donor_basename_does_not(self) -> None:
        (self.root / "board.lck").write_bytes(b"not a native KiCad lock")
        self.assertFalse(Project.open(self.root).is_locked)
        lock = self.root / "~board.kicad_pro.lck"
        lock.symlink_to(self.root / "missing")
        self.assertTrue(Project.open(self.root).is_locked)

    def test_writes_do_not_consult_locks_and_never_touch_them(self) -> None:
        lock = self.root / "~board.kicad_pro.lck"
        lock.write_bytes(b"peer owns unsaved buffers")
        project = Project.open(self.root)
        self.assertTrue(project.is_locked)
        project.schematic().files[1].validate()
        project.save()
        project.backup(project.backup_directory)
        project.save_as(self.root.parent / "copy", "copy")
        self.assertEqual(lock.read_bytes(), b"peer owns unsaved buffers")


if __name__ == "__main__":
    unittest.main()
