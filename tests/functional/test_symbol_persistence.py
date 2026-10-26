"""Public single-file safety contracts; all filesystem output is disposable."""

import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.symbols import (
    FileConflictError,
    SymbolLibrary,
    UnsupportedOperationError,
)

ORIGINAL = b'(kicad_symbol_lib (version 20251024) (symbol "A" (property "Note" "old")))'


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Example.kicad_sym"
        self.path.write_bytes(ORIGINAL)
        self.library = SymbolLibrary.open(self.path)

    def test_external_change_conflicts_for_changed_and_unchanged_save(self) -> None:
        for edit in (False, True):
            with self.subTest(edit=edit):
                self.path.write_bytes(ORIGINAL)
                library = SymbolLibrary.open(self.path)
                if edit:
                    library.set_attribute("A", "Note", "mine")
                foreign = ORIGINAL.replace(b'"old"', b'"someone else"')
                self.path.write_bytes(foreign)
                with self.assertRaises(FileConflictError):
                    library.save()
                self.assertEqual(self.path.read_bytes(), foreign)

    def test_mode_is_preserved_and_baseline_updates_after_save(self) -> None:
        self.path.chmod(0o640)
        self.library.set_attribute("A", "Note", "one")
        self.library.save()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        first = self.path.read_bytes()
        self.library.save()
        self.assertEqual(self.path.read_bytes(), first)
        self.library.set_attribute("A", "Note", "two")
        self.library.save()
        self.assertEqual(self.path.read_bytes(), ORIGINAL.replace(b'"old"', b'"two"'))

    def test_replacement_failure_preserves_original_and_can_retry(self) -> None:
        self.library.set_attribute("A", "Note", "new")
        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace",
                side_effect=OSError("failed"),
            ),
            self.assertRaises(OSError),
        ):
            self.library.save()
        self.assertEqual(self.path.read_bytes(), ORIGINAL)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.library.save()
        self.assertEqual(self.path.read_bytes(), ORIGINAL.replace(b'"old"', b'"new"'))

    def test_flush_failure_does_not_truncate_source_or_leave_temp_file(self) -> None:
        self.library.set_attribute("A", "Note", "new")
        with (
            patch(
                "kicad_primitives._symbol_persist.os.fsync",
                side_effect=OSError("failed"),
            ),
            self.assertRaises(OSError),
        ):
            self.library.save()
        self.assertEqual(self.path.read_bytes(), ORIGINAL)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_deleted_file_is_a_conflict_not_implicit_recreation(self) -> None:
        self.library.set_attribute("A", "Note", "new")
        self.path.unlink()
        with self.assertRaises(FileConflictError):
            self.library.save()
        self.assertFalse(self.path.exists())

    def test_links_are_readable_but_not_replaced(self) -> None:
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind):
                link = self.path.with_name(f"{kind}.kicad_sym")
                if kind == "symlink":
                    link.symlink_to(self.path)
                else:
                    os.link(self.path, link)
                try:
                    library = SymbolLibrary.open(link)
                    library.set_attribute("A", "Note", "new")
                    with self.assertRaises(UnsupportedOperationError):
                        library.save()
                    self.assertEqual(self.path.read_bytes(), ORIGINAL)
                    self.assertEqual(link.read_bytes(), ORIGINAL)
                finally:
                    link.unlink()

    def test_readonly_permissions_are_not_bypassed_with_directory_replace(self) -> None:
        self.path.chmod(0o444)
        self.addCleanup(self.path.chmod, 0o644)
        self.library.set_attribute("A", "Note", "new")
        with self.assertRaises(PermissionError):
            self.library.save()
        self.assertEqual(self.path.read_bytes(), ORIGINAL)


if __name__ == "__main__":
    unittest.main()
