"""Physical table nouns own pending rows and explicit single-file decisions."""

import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.tables import LibraryTableConflictError, LibraryTables


class TableArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "config"
        self.home.mkdir()
        self.path = self.home / "sym-lib-table"
        self.original = (
            b"(sym_lib_table (version 7)\n"
            b' (lib (name "Keep") (type "KiCad") (uri "/keep.kicad_sym")'
            b' (options "opaque") (descr "stay") (disabled) (hidden)'
            b' (future "quoted \\"content\\""))\n'
            b' (lib (name "Old") (type "KiCad") (uri "/old.kicad_sym")))\n'
        )
        self.path.write_bytes(self.original)
        self.tables = LibraryTables.open(
            config_home=self.home, base_directory=self.root
        )

    def test_flag_overwrite_and_validate(self) -> None:
        """ADR 0011 D9: flag-based is_modified, fingerprint, overwrite, validate."""
        table = self.tables.table("symbol", "global")
        table.entry("Old").set_uri("/new.kicad_sym")
        table.entry("Old").set_uri("/old.kicad_sym")
        self.assertEqual(table.to_bytes(), self.original)
        self.assertTrue(table.is_modified)
        table.validate()
        table.entry("Old").set_uri("/new.kicad_sym")
        foreign = self.original + b"\n"
        self.path.write_bytes(foreign)
        with self.assertRaises(LibraryTableConflictError):
            table.save()
        self.assertEqual(self.path.read_bytes(), foreign)
        table.save(overwrite=True)
        self.assertIn(b"/new.kicad_sym", self.path.read_bytes())
        self.assertFalse(table.is_modified)
        before = self.path.stat().st_mtime_ns
        table.save()
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_edits_stay_pending_and_preserve_raw_rows_and_entry_identity(self) -> None:
        table = self.tables.table("symbol", "global")
        keep = table.entry("Keep")
        old = table.entry("Old")
        old.rename("Renamed")
        old.set_uri("/new.kicad_sym")
        self.assertIs(table.entry("Renamed"), old)
        self.assertIs(table.entry("Keep"), keep)
        expected = self.original.replace(b'"Old"', b'"Renamed"').replace(
            b'"/old.kicad_sym"', b'"/new.kicad_sym"'
        )
        self.assertEqual(table.to_bytes(), expected)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertTrue(table.is_modified)
        self.assertTrue(self.tables.is_modified)
        self.assertEqual(
            self.tables.resolve("Renamed", library_type="symbol").resolved_path,
            Path("/new.kicad_sym"),
        )
        old.set_uri("/new.kicad_sym")
        self.assertEqual(table.to_bytes(), expected)
        added = table.add_entry("Added", "/added.kicad_sym")
        added.delete()
        self.assertEqual(table.to_bytes(), expected)
        old.delete()
        table.add_entry("Renamed", "/replacement.kicad_sym")
        with self.assertRaises(RuntimeError):
            old.set_uri("/stale.kicad_sym")
        table.save()
        self.assertEqual(self.path.read_bytes(), table.to_bytes())
        self.assertFalse(table.is_modified)
        self.assertFalse(self.tables.is_modified)

    def test_save_as_can_fork_readonly_or_linked_source_without_writing_it(
        self,
    ) -> None:
        for kind in ("readonly", "symlink", "hardlink"):
            with self.subTest(kind=kind):
                home = self.root / kind
                home.mkdir()
                path = home / "sym-lib-table"
                source = self.root / f"{kind}-source"
                source.write_bytes(self.original)
                if kind == "symlink":
                    path.symlink_to(source)
                elif kind == "hardlink":
                    os.link(source, path)
                else:
                    path.write_bytes(self.original)
                table = LibraryTables.open(config_home=home).table("symbol", "global")
                table.entry("Old").set_uri("/forked.kicad_sym")
                path.chmod(0o444)
                home.chmod(0o555)
                self.addCleanup(home.chmod, 0o755)
                self.addCleanup(source.chmod, 0o644)
                destination = self.root / f"{kind}-copy"
                table.save_as(destination)
                self.assertEqual(path.read_bytes(), self.original)
                self.assertEqual(source.read_bytes(), self.original)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
                self.assertIn(b'"/forked.kicad_sym"', destination.read_bytes())
                self.assertFalse(table.is_modified)
                table.close()

    def test_compact_and_crlf_rows_keep_opaque_content_through_successive_edits(
        self,
    ) -> None:
        for source in (
            b'(sym_lib_table (lib (name "Old") (uri "/old") (future (opaque 001.00))))\n',
            b'(sym_lib_table\r\n\t(lib (name "Old") (uri "/old") (future (opaque 001.00)))\r\n)\r\n',
        ):
            with self.subTest(source=source):
                self.path.write_bytes(source)
                context = LibraryTables.open(config_home=self.home)
                table = context.table("symbol", "global")
                table.entry("Old").set_uri("/new")
                expected = source.replace(b'"/old"', b'"/new"')
                self.assertEqual(table.to_bytes(), expected)
                added = table.add_entry("New", "/newer")
                self.assertIn(b"(future (opaque 001.00))", table.to_bytes())
                added.delete()
                self.assertEqual(table.to_bytes(), expected)
                table.save()
                self.assertEqual(self.path.read_bytes(), expected)

    def test_nested_resolution_uses_same_pending_physical_table(self) -> None:
        nested = self.root / "nested-table"
        nested.write_bytes(
            b'(sym_lib_table (lib (name "Leaf") (type "KiCad") (uri "old.kicad_sym")))'
        )
        table = self.tables.table("symbol", "global")
        link = table.add_entry("Bundle", "nested-table", entry_type="Table")
        child = link.included_table
        self.assertIsNotNone(child)
        assert child is not None
        self.assertIs(link.included_table, child)
        child.entry("Leaf").set_uri("pending.kicad_sym")
        self.assertEqual(
            self.tables.resolve("Leaf", library_type="symbol").resolved_path,
            self.root / "pending.kicad_sym",
        )
        self.assertIn(b'"old.kicad_sym"', nested.read_bytes())
        child.discard()
        with self.assertRaises(RuntimeError):
            child.entry("Leaf")

    def test_missing_table_edits_do_not_create_a_file_until_save(self) -> None:
        table = self.tables.table("footprint", "global")
        table.add_entry("Mods", "Mods.pretty")
        self.assertFalse(table.path.exists())
        self.assertEqual(
            self.tables.resolve("Mods", library_type="footprint").resolved_path,
            self.root / "Mods.pretty",
        )
        table.save()
        self.assertTrue(table.path.is_file())
        table.close()

    def test_clean_close_writes_nothing_and_never_creates_a_missing_table(
        self,
    ) -> None:
        inode = self.path.stat().st_ino
        table = self.tables.table("symbol", "global")
        table.entry("Old").set_uri(table.entry("Old").uri)
        table.close()
        table.close()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.path.stat().st_ino, inode)
        with self.assertRaises(RuntimeError):
            table.to_bytes()
        missing = self.tables.table("footprint", "global")
        missing.close()
        self.assertFalse(missing.path.exists())

    def test_with_block_saves_on_normal_exit_and_discards_on_exception(
        self,
    ) -> None:
        with self.tables.table("symbol", "global") as table:
            table.entry("Old").set_uri("/saved.kicad_sym")
        self.assertTrue(table.is_closed)
        saved = self.path.read_bytes()
        self.assertIn(b'"/saved.kicad_sym"', saved)
        tables = LibraryTables.open(config_home=self.home)
        with (
            self.assertRaises(KeyError),
            tables.table("symbol", "global") as table,
        ):
            table.entry("Old").set_uri("/abandoned.kicad_sym")
            raise KeyError("client failure")
        self.assertTrue(table.is_closed)
        self.assertEqual(self.path.read_bytes(), saved)

    def test_discard_is_terminal_and_never_writes(self) -> None:
        table = self.tables.table("symbol", "global")
        entry = table.entry("Old")
        entry.set_uri("/pending.kicad_sym")
        table.discard()
        table.close()
        self.assertEqual(self.path.read_bytes(), self.original)
        with self.assertRaises(RuntimeError):
            entry.set_uri("/late.kicad_sym")
        with self.assertRaises(RuntimeError):
            table.add_entry("Late", "/late.kicad_sym")

    def test_close_saves_pending_edits_and_a_conflict_keeps_the_table_open(
        self,
    ) -> None:
        table = self.tables.table("symbol", "global")
        entry = table.entry("Old")
        entry.set_uri("/changed.kicad_sym")
        foreign = self.original.replace(b'"Old"', b'"Foreign"')
        self.path.write_bytes(foreign)
        with self.assertRaises(LibraryTableConflictError):
            table.close()
        self.assertFalse(table.is_closed)
        self.assertTrue(table.is_modified)
        self.assertEqual(self.path.read_bytes(), foreign)
        table.discard()
        self.path.write_bytes(self.original)
        table = LibraryTables.open(config_home=self.home).table("symbol", "global")
        table.entry("Old").set_uri("/changed.kicad_sym")
        table.close()
        self.assertTrue(table.is_closed)
        self.assertIn(b'"/changed.kicad_sym"', self.path.read_bytes())

    def test_single_file_save_as_rebinds_only_after_success_and_preserves_original(
        self,
    ) -> None:
        self.path.chmod(0o640)
        table = self.tables.table("symbol", "global")
        entry = table.entry("Old")
        entry.rename("Renamed")
        expected = table.to_bytes()
        destination = self.root / "new-table"
        table.save_as(destination)
        self.assertEqual(table.path, destination)
        self.assertIs(self.tables.table("symbol", "global"), table)
        self.assertIs(table.entry("Renamed"), entry)
        self.assertEqual(destination.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertFalse(table.is_modified)
        entry.set_uri("/later.kicad_sym")
        table.save()
        self.assertIn(b'"/later.kicad_sym"', destination.read_bytes())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(destination.with_suffix(".bak").exists())
        table.close()

    def test_existing_symlink_and_unsafe_parent_save_as_fail_without_rebind(
        self,
    ) -> None:
        table = self.tables.table("symbol", "global")
        existing = self.root / "existing"
        existing.write_bytes(b"do not replace")
        link = self.root / "link"
        link.symlink_to(existing)
        dangling = self.root / "dangling"
        dangling.symlink_to(self.root / "absent")
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(self.home, target_is_directory=True)
        readonly = self.root / "readonly"
        readonly.mkdir()
        readonly.chmod(0o555)
        self.addCleanup(readonly.chmod, 0o755)
        for target in (
            existing,
            link,
            dangling,
            linked_parent / "new-table",
            self.root / "missing-parent" / "new-table",
            readonly / "new-table",
        ):
            with self.subTest(target=target):
                table.save()
                with self.assertRaises((OSError, RuntimeError, ValueError)):
                    table.save_as(target)
                self.assertEqual(table.path, self.path)
                self.assertFalse(table.is_modified)
                self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(existing.read_bytes(), b"do not replace")
        self.assertTrue(link.is_symlink())
        self.assertTrue(dangling.is_symlink())

    def test_save_as_flush_or_racing_collision_keeps_pending_source_and_original(
        self,
    ) -> None:
        table = self.tables.table("symbol", "global")
        table.entry("Old").set_uri("/pending.kicad_sym")
        expected = table.to_bytes()
        destination = self.root / "new-table"
        with (
            patch(
                "kicad_primitives._symbol_persist.os.fsync",
                side_effect=OSError("failed"),
            ),
            self.assertRaises(OSError),
        ):
            table.save_as(destination)
        self.assertFalse(destination.exists())
        self.assertEqual(table.path, self.path)
        self.assertTrue(table.is_modified)
        self.assertEqual(table.to_bytes(), expected)
        self.assertEqual(self.path.read_bytes(), self.original)
        real_link = os.link

        def racing_link(source: Path, target: Path) -> None:
            target.write_bytes(b"racing writer")
            real_link(source, target)

        with (
            patch("kicad_primitives._symbol_persist.os.link", side_effect=racing_link),
            self.assertRaises(FileExistsError),
        ):
            table.save_as(destination)
        self.assertEqual(destination.read_bytes(), b"racing writer")
        self.assertEqual(table.path, self.path)
        self.assertEqual(table.to_bytes(), expected)
        table.discard()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(any(p.suffix == ".tmp" for p in self.root.iterdir()))

    def test_overwrite_conflicts_links_modes_and_replacement_failure(self) -> None:
        table = self.tables.table("symbol", "global")
        self.path.chmod(0o640)
        table.entry("Old").set_uri("/pending.kicad_sym")
        expected = table.to_bytes()
        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace",
                side_effect=OSError("failed"),
            ),
            self.assertRaises(OSError),
        ):
            table.save()
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(table.to_bytes(), expected)
        self.assertTrue(table.is_modified)
        table.save()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertFalse(self.path.with_suffix(".bak").exists())
        alias = self.root / "alias"
        os.link(self.path, alias)
        table.entry("Old").set_uri("/again.kicad_sym")
        with self.assertRaises(ValueError):
            table.save()
        alias.unlink()
        self.path.chmod(0o444)
        self.addCleanup(self.path.chmod, 0o644)
        table.entry("Old").rename("Renamed")
        with self.assertRaises(PermissionError):
            table.save()

    def test_old_apply_surface_is_absent_and_ambiguity_stays_visible(self) -> None:
        for name in ("add_library", "remove_library", "rename_library"):
            self.assertFalse(hasattr(self.tables, name))
        self.path.write_bytes(
            b'(sym_lib_table (lib (name "A") (type "KiCad") (uri "/a"))'
            b' (lib (name "A") (type "KiCad") (uri "/b")))'
        )
        table = self.tables.table("symbol", "global")
        self.assertEqual([e.uri for e in table.entries], ["/a", "/b"])
        for action in (
            lambda: table.entry("A"),
            lambda: table.entries[0].rename("Other"),
            lambda: table.entries[0].set_uri("/changed"),
            lambda: table.entries[0].delete(),
        ):
            with self.assertRaises(ValueError):
                action()
        self.assertFalse(table.is_modified)
