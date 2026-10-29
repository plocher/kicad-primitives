"""Independent symbol-library lifecycle: close saves pending edits; discard is terminal."""

import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.symbols import FileConflictError, SymbolLibrary

ORIGINAL = (
    b'(kicad_symbol_lib (version 20251024) (symbol "A" (property "Note" "old")'
    b' (symbol "A_1_1" (pin passive line (at 0 0 0) (length 1)'
    b' (name "P") (number "1")))))'
)


class LibraryLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "Parts.kicad_sym"
        self.path.write_bytes(ORIGINAL)
        self.library = SymbolLibrary.open(self.path)

    def test_clean_open_close_writes_nothing_and_is_idempotent(self) -> None:
        inode = self.path.stat().st_ino
        self.library.symbol("A").set_attribute("Note", "old")
        self.library.symbol("A").body(1, 1).pin("1").set(name="P")
        self.library.close()
        self.library.close()
        self.assertTrue(self.library.is_closed)
        self.assertEqual(self.path.read_bytes(), ORIGINAL)
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertFalse(self.path.with_suffix(".bak").exists())
        with self.assertRaises(RuntimeError):
            self.library.symbol("A")

    def test_close_saves_pending_edits_and_failed_save_keeps_library_open(
        self,
    ) -> None:
        symbol = self.library.symbol("A")
        symbol.set_attribute("Note", "changed")
        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace",
                side_effect=OSError("failed"),
            ),
            self.assertRaises(OSError),
        ):
            self.library.close()
        self.assertFalse(self.library.is_closed)
        self.assertTrue(self.library.is_modified)
        self.assertEqual(self.path.read_bytes(), ORIGINAL)
        self.library.close()
        self.assertTrue(self.library.is_closed)
        self.assertEqual(
            self.path.read_bytes(), ORIGINAL.replace(b'"old"', b'"changed"')
        )
        self.assertEqual(self.path.with_suffix(".bak").read_bytes(), ORIGINAL)

    def test_close_conflict_keeps_library_open_for_discard(self) -> None:
        self.library.symbol("A").set_attribute("Note", "changed")
        foreign = ORIGINAL.replace(b'"old"', b'"foreign"')
        self.path.write_bytes(foreign)
        with self.assertRaises(FileConflictError):
            self.library.close()
        self.assertFalse(self.library.is_closed)
        self.library.discard()
        self.library.close()
        self.assertEqual(self.path.read_bytes(), foreign)

    def test_with_block_saves_on_normal_exit_and_discards_on_exception(
        self,
    ) -> None:
        with SymbolLibrary.open(self.path) as library:
            library.symbol("A").set_attribute("Note", "saved")
        self.assertTrue(library.is_closed)
        saved = ORIGINAL.replace(b'"old"', b'"saved"')
        self.assertEqual(self.path.read_bytes(), saved)
        with self.assertRaises(KeyError), SymbolLibrary.open(self.path) as library:
            library.symbol("A").set_attribute("Note", "abandoned")
            raise KeyError("client failure")
        self.assertTrue(library.is_closed)
        self.assertEqual(self.path.read_bytes(), saved)
        self.library.discard()

    def test_discard_invalidates_owned_handles_and_never_resets_for_continued_use(
        self,
    ) -> None:
        symbol = self.library.symbol("A")
        body = symbol.body(1, 1)
        pin = body.pin("1")
        value = symbol.attribute("Note")
        symbol.set_attribute("Note", "pending")
        self.library.discard()
        self.library.close()
        self.assertTrue(self.library.is_closed)
        self.assertEqual(value.value, "old")
        self.assertEqual(self.library.path, self.path)
        self.assertEqual(self.path.read_bytes(), ORIGINAL)
        for action in (
            lambda: self.library.to_bytes(),
            lambda: self.library.save(),
            lambda: self.library.create_symbol("New"),
            lambda: symbol.set_attribute("Note", "late"),
            lambda: body.add_text("late", x=0, y=0),
            lambda: pin.set(name="late"),
        ):
            with self.assertRaises(RuntimeError):
                action()

    def test_save_as_rebinds_current_handles_and_does_not_write_original(self) -> None:
        self.path.chmod(0o640)
        symbol = self.library.symbol("A")
        symbol.set_attribute("Note", "copy")
        destination = self.root / "New.kicad_sym"
        self.library.save_as(destination)
        self.assertEqual(self.library.path, destination)
        self.assertIs(self.library.symbol("A"), symbol)
        self.assertEqual(
            destination.read_bytes(), ORIGINAL.replace(b'"old"', b'"copy"')
        )
        self.assertEqual(self.path.read_bytes(), ORIGINAL)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertFalse(self.library.is_modified)
        self.assertFalse(destination.with_suffix(".bak").exists())
        self.library.close()

    def test_changed_overwrites_make_native_suffix_backup_and_noops_leave_it_alone(
        self,
    ) -> None:
        self.path.chmod(0o640)
        backup = self.path.with_suffix(".bak")
        self.library.symbol("A").set_attribute("Note", "first")
        self.library.save()
        self.assertEqual(backup.read_bytes(), ORIGINAL)
        self.assertFalse(self.path.with_name(self.path.name + ".bak").exists())
        first = self.path.read_bytes()
        self.library.symbol("A").set_attribute("Note", "second")
        self.library.save()
        self.assertEqual(backup.read_bytes(), first)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        before = (self.path.stat().st_ino, backup.stat().st_ino, backup.read_bytes())
        self.library.save()
        self.assertEqual(
            (self.path.stat().st_ino, backup.stat().st_ino, backup.read_bytes()), before
        )
        self.library.close()

    def test_backup_failure_keeps_original_prior_backup_pending_and_decision(
        self,
    ) -> None:
        backup = self.path.with_suffix(".bak")
        backup.write_bytes(b"prior backup")
        self.library.symbol("A").set_attribute("Note", "pending")
        pending = self.library.to_bytes()
        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace",
                side_effect=OSError("failed"),
            ),
            self.assertRaises(OSError),
        ):
            self.library.save()
        self.assertEqual(self.path.read_bytes(), ORIGINAL)
        self.assertEqual(backup.read_bytes(), b"prior backup")
        self.assertEqual(self.library.to_bytes(), pending)
        self.assertTrue(self.library.is_modified)
        self.library.discard()
        self.assertFalse(any(p.suffix == ".tmp" for p in self.root.iterdir()))

    def test_source_failure_restores_prior_backup_or_removes_only_our_new_backup(
        self,
    ) -> None:
        backup = self.path.with_suffix(".bak")
        real_replace = os.replace

        def failing_source(source: Path, target: Path) -> None:
            if target == self.path:
                raise OSError("source replacement failed")
            real_replace(source, target)

        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    backup.write_bytes(b"prior backup")
                    backup.chmod(0o640)
                library = SymbolLibrary.open(self.path)
                library.symbol("A").set_attribute("Note", "pending")
                with (
                    patch(
                        "kicad_primitives._symbol_persist.os.replace",
                        side_effect=failing_source,
                    ),
                    self.assertRaises(OSError),
                ):
                    library.save()
                self.assertEqual(self.path.read_bytes(), ORIGINAL)
                self.assertTrue(library.is_modified)
                if existing:
                    self.assertEqual(backup.read_bytes(), b"prior backup")
                    self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o640)
                else:
                    self.assertFalse(backup.exists())
                library.discard()
                self.assertFalse(any(p.suffix == ".tmp" for p in self.root.iterdir()))

    def test_save_as_failure_keeps_identity_and_pending_edits(self) -> None:
        destination = self.root / "existing.kicad_sym"
        destination.write_bytes(b"do not replace")
        with self.assertRaises(FileExistsError):
            self.library.save_as(destination)
        self.assertFalse(self.library.is_modified)
        self.assertEqual(self.library.path, self.path)
        self.library.symbol("A").set_attribute("Note", "pending")
        pending = self.library.to_bytes()
        fresh = self.root / "new.kicad_sym"
        with (
            patch(
                "kicad_primitives._symbol_persist.os.fsync",
                side_effect=OSError("failed"),
            ),
            self.assertRaises(OSError),
        ):
            self.library.save_as(fresh)
        self.assertEqual(self.library.path, self.path)
        self.assertEqual(self.library.to_bytes(), pending)
        self.assertTrue(self.library.is_modified)
        self.assertEqual(self.path.read_bytes(), ORIGINAL)
        self.assertEqual(destination.read_bytes(), b"do not replace")
        self.assertFalse(fresh.exists())
        self.assertFalse(any(p.suffix == ".tmp" for p in self.root.iterdir()))

    def test_save_as_forks_readonly_and_linked_sources_but_rejects_unsafe_destinations(
        self,
    ) -> None:
        home = self.root / "readonly-source"
        home.mkdir()
        original = home / "Parts.kicad_sym"
        original.write_bytes(ORIGINAL)
        original.chmod(0o444)
        home.chmod(0o555)
        self.addCleanup(home.chmod, 0o755)
        for kind in ("readonly", "symlink", "hardlink"):
            with self.subTest(kind=kind):
                source = self.root / f"{kind}.kicad_sym"
                if kind == "readonly":
                    source = original
                elif kind == "symlink":
                    source.symlink_to(original)
                else:
                    os.link(original, source)
                library = SymbolLibrary.open(source)
                library.symbol("A").set_attribute("Note", "fork")
                destination = self.root / f"{kind}-fork.kicad_sym"
                library.save_as(destination)
                self.assertEqual(source.read_bytes(), ORIGINAL)
                self.assertEqual(original.read_bytes(), ORIGINAL)
                self.assertEqual(stat.S_IMODE(original.stat().st_mode), 0o444)
                self.assertIn(b'"fork"', destination.read_bytes())
                self.assertFalse(destination.with_suffix(".bak").exists())
                library.close()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(home, target_is_directory=True)
        destination_link = self.root / "destination-link"
        destination_link.symlink_to(self.root / "missing")
        for destination in (
            destination_link,
            linked_parent / "new.kicad_sym",
            home / "new.kicad_sym",
            self.root / "absent" / "new.kicad_sym",
        ):
            with self.subTest(destination=destination):
                with self.assertRaises((OSError, RuntimeError, ValueError)):
                    self.library.save_as(destination)
                self.assertEqual(self.library.path, self.path)
        self.assertTrue(destination_link.is_symlink())
        self.assertEqual(original.read_bytes(), ORIGINAL)

    def test_closed_source_copy_is_nonmutating_even_through_private_source_integration(
        self,
    ) -> None:
        destination = self.root / "Destination.kicad_sym"
        raw = b"(kicad_symbol_lib (version 20251024))"
        destination.write_bytes(raw)
        library = SymbolLibrary.open(destination)
        for decision in ("discard", "close"):
            with self.subTest(decision=decision):
                source = SymbolLibrary.open(self.path)
                if decision == "close":
                    source.save()
                    source.close()
                else:
                    source.discard()
                with self.assertRaises(RuntimeError):
                    library.copy_symbol_from(source, "A", "Copy")
                self.assertEqual(library.to_bytes(), raw)
                self.assertEqual(destination.read_bytes(), raw)
                self.assertFalse(library.is_modified)

    def test_unsafe_backup_destinations_fail_before_any_original_write(self) -> None:
        backup = self.path.with_suffix(".bak")
        victim = self.root / "victim"
        victim.write_bytes(b"do not touch")
        self.library.symbol("A").set_attribute("Note", "pending")
        for kind in ("symlink", "hardlink", "readonly", "directory"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    backup.symlink_to(victim)
                elif kind == "hardlink":
                    os.link(victim, backup)
                elif kind == "readonly":
                    backup.write_bytes(b"prior")
                    backup.chmod(0o444)
                else:
                    backup.mkdir()
                try:
                    with self.assertRaises((OSError, ValueError, RuntimeError)):
                        self.library.save()
                    self.assertEqual(self.path.read_bytes(), ORIGINAL)
                    self.assertEqual(victim.read_bytes(), b"do not touch")
                    self.assertTrue(self.library.is_modified)
                finally:
                    if kind == "directory":
                        backup.rmdir()
                    else:
                        backup.unlink()
        collision = self.root / "Collision.bak"
        collision.write_bytes(ORIGINAL)
        library = SymbolLibrary.open(collision)
        library.symbol("A").set_attribute("Note", "pending")
        with self.assertRaises((ValueError, RuntimeError)):
            library.save()
        self.assertEqual(collision.read_bytes(), ORIGINAL)

    def test_backup_recovery_never_overwrites_or_deletes_a_concurrent_version(
        self,
    ) -> None:
        real_replace = os.replace
        real_link = os.link
        for existing, rewrite in ((False, False), (True, False), (True, True)):
            with self.subTest(existing=existing, rewrite=rewrite):
                root = self.root / f"race-{existing}-{rewrite}"
                root.mkdir()
                path = root / "Parts.kicad_sym"
                path.write_bytes(ORIGINAL)
                backup = path.with_suffix(".bak")
                if existing:
                    backup.write_bytes(b"prior backup")
                foreign = root / "foreign"
                foreign.write_bytes(ORIGINAL)
                foreign_inode = foreign.stat().st_ino
                raced = False

                def racing_replace(
                    source: Path,
                    target: Path,
                    *,
                    path: Path = path,
                    backup: Path = backup,
                    rewrite: bool = rewrite,
                    foreign: Path = foreign,
                ) -> None:
                    nonlocal raced
                    if target == path:
                        if rewrite:
                            backup.write_bytes(b"foreign rewrite")
                        raise OSError("source failed")
                    real_replace(source, target)
                    if target == backup and not raced and not rewrite:
                        raced = True
                        real_replace(foreign, backup)

                def racing_link(
                    source: Path,
                    target: Path,
                    *,
                    backup: Path = backup,
                    rewrite: bool = rewrite,
                    foreign: Path = foreign,
                ) -> None:
                    real_link(source, target)
                    if target == backup and not rewrite:
                        real_replace(foreign, backup)

                library = SymbolLibrary.open(path)
                library.symbol("A").set_attribute("Note", "pending")
                with (
                    patch(
                        "kicad_primitives._symbol_persist.os.replace",
                        side_effect=racing_replace,
                    ),
                    patch(
                        "kicad_primitives._symbol_persist.os.link",
                        side_effect=racing_link,
                    ),
                    self.assertRaises(FileConflictError),
                ):
                    library.save()
                self.assertEqual(path.read_bytes(), ORIGINAL)
                if rewrite:
                    self.assertEqual(backup.read_bytes(), b"foreign rewrite")
                else:
                    self.assertEqual(backup.stat().st_ino, foreign_inode)
                    self.assertEqual(backup.read_bytes(), ORIGINAL)
                if existing:
                    recoveries = tuple(root.glob(".Parts.bak.recovery.*.tmp"))
                    self.assertEqual(len(recoveries), 1)
                    self.assertEqual(recoveries[0].read_bytes(), b"prior backup")
                self.assertTrue(library.is_modified)
                library.discard()

    def test_published_backup_never_adopts_a_same_inode_same_byte_foreign_version(
        self,
    ) -> None:
        real_replace = os.replace
        real_link = os.link
        for existing in (False, True):
            with self.subTest(existing=existing):
                root = self.root / f"same-inode-{existing}"
                root.mkdir()
                path = root / "Parts.kicad_sym"
                path.write_bytes(ORIGINAL)
                backup = path.with_suffix(".bak")
                if existing:
                    backup.write_bytes(b"prior backup")
                foreign_version: tuple[int, int] | None = None
                source_attempted = False

                def rewrite_same_bytes(target: Path) -> None:
                    nonlocal foreign_version
                    info = target.stat()
                    target.write_bytes(ORIGINAL)
                    os.utime(
                        target,
                        ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000),
                    )
                    changed = target.stat()
                    foreign_version = (changed.st_ino, changed.st_mtime_ns)

                def racing_replace(
                    source: Path,
                    target: Path,
                    *,
                    path: Path = path,
                    backup: Path = backup,
                ) -> None:
                    nonlocal source_attempted
                    if target == path:
                        source_attempted = True
                        raise OSError("source replacement failed")
                    real_replace(source, target)
                    if target == backup:
                        rewrite_same_bytes(target)

                def racing_link(
                    source: Path,
                    target: Path,
                    *,
                    backup: Path = backup,
                ) -> None:
                    real_link(source, target)
                    if target == backup:
                        rewrite_same_bytes(target)

                library = SymbolLibrary.open(path)
                library.symbol("A").set_attribute("Note", "pending")
                with (
                    patch(
                        "kicad_primitives._symbol_persist.os.replace",
                        side_effect=racing_replace,
                    ),
                    patch(
                        "kicad_primitives._symbol_persist.os.link",
                        side_effect=racing_link,
                    ),
                    self.assertRaises(FileConflictError),
                ):
                    library.save()
                self.assertFalse(source_attempted)
                self.assertIsNotNone(foreign_version)
                actual = backup.stat()
                self.assertEqual((actual.st_ino, actual.st_mtime_ns), foreign_version)
                self.assertEqual(backup.read_bytes(), ORIGINAL)
                self.assertEqual(path.read_bytes(), ORIGINAL)
                if existing:
                    recoveries = tuple(root.glob(".Parts.bak.recovery.*.tmp"))
                    self.assertEqual(len(recoveries), 1)
                    self.assertEqual(recoveries[0].read_bytes(), b"prior backup")
                self.assertTrue(library.is_modified)
                library.discard()
