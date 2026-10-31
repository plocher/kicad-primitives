"""Project decisions and ZIP safety snapshots through public artifact seams."""

import os
import subprocess
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.projects import (
    Project,
    ProjectBackupError,
    ProjectWriteBlockedError,
)
from kicad_primitives.schematics import (
    InvalidSchematicError,
    SchematicConflictError,
    UnsupportedSchematicOperationError,
)
from tests.functional.test_schematic_editing import SOURCE


class ProjectLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.pro = self.root / "board.kicad_pro"
        self.pro.write_bytes(b'{"meta":{"filename":"board.kicad_pro"},"opaque":1}')
        self.sch = self.root / "board.kicad_sch"
        self.sch.write_bytes(SOURCE)

    def verifier(self) -> Path:
        """Provide fixed electrical evidence while exercising real file persistence."""
        cli = self.root / ".fake-cli"
        cli.write_text(
            "#!/usr/bin/env python3\nimport pathlib,sys\n"
            "pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text("
            "'(export (version E) (components (comp (ref R1) "
            "(libsource (lib Device) (part R)))) "
            '(nets (net (name "signal") (node (ref R1) (pin 1) '
            "(pinfunction ~) (pintype passive)))))')\n",
            encoding="utf-8",
        )
        cli.chmod(0o755)
        return cli

    def hierarchy(self, name: str = "sub/child.kicad_sch") -> tuple[Project, Path]:
        """Create a strict owned child without normalizing the root fixture."""
        self.sch.write_bytes(
            SOURCE.replace(
                b"(generator eeschema)",
                f'(generator eeschema) (sheet (at 0 0) (size 1 1) (property "Sheetfile" "{name}"))'.encode(),
            )
        )
        child = self.root / name
        child.parent.mkdir(parents=True, exist_ok=True)
        child.write_bytes(SOURCE.replace(b"R1", b"R2").replace(b"uuid-r1", b"uuid-r2"))
        return Project.open(self.pro), child

    def archives(self) -> tuple[Path, ...]:
        """Return the created Project snapshots, not arbitrary ZIP files."""
        return tuple(sorted((self.root / "board-backups").glob("board-*.zip")))

    def test_clean_open_close_writes_nothing_and_dirty_close_saves(self) -> None:
        before = {
            p.name: (p.read_bytes(), p.stat().st_ino) for p in (self.pro, self.sch)
        }
        clean = Project.open(self.pro)
        clean.schematic().files[0].symbol("R1").attribute("Value")
        clean.close(kicad_cli=self.root / "must-not-run")
        self.assertTrue(clean.is_closed)
        self.assertFalse(self.archives())
        for name, (raw, inode) in before.items():
            self.assertEqual(
                ((self.root / name).read_bytes(), (self.root / name).stat().st_ino),
                (raw, inode),
            )
        project = Project.open(self.pro)
        project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        project.close(kicad_cli=self.verifier())
        self.assertTrue(project.is_closed)
        self.assertEqual(self.sch.read_bytes(), SOURCE.replace(b'"10K"', b'"22K"'))
        self.assertEqual(len(self.archives()), 1)

    def test_with_block_saves_on_normal_exit_and_discards_on_exception(
        self,
    ) -> None:
        with (
            patch.dict(os.environ, {"KICAD_CLI": str(self.verifier())}),
            Project.open(self.pro) as project,
        ):
            project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        self.assertTrue(project.is_closed)
        saved = SOURCE.replace(b'"10K"', b'"22K"')
        self.assertEqual(self.sch.read_bytes(), saved)
        self.assertEqual(len(self.archives()), 1)
        with self.assertRaises(KeyError), Project.open(self.pro) as project:
            project.schematic().files[0].symbol("R1").set_attribute("Value", "33K")
            raise KeyError("client failure")
        self.assertTrue(project.is_closed)
        self.assertEqual(self.sch.read_bytes(), saved)
        self.assertEqual(len(self.archives()), 1)

    def test_clean_project_save_captures_full_file_set(self) -> None:
        project = Project.open(self.pro)
        before = {
            p.name: (p.read_bytes(), p.stat().st_ino) for p in (self.pro, self.sch)
        }
        project.save(kicad_cli=self.root / "not-needed")
        archives = tuple((self.root / "board-backups").glob("board-*.zip"))
        self.assertEqual(len(archives), 1)
        with zipfile.ZipFile(archives[0]) as archive:
            self.assertEqual(set(archive.namelist()), set(before))
            for name, (raw, inode) in before.items():
                self.assertEqual(archive.read(name), raw)
                self.assertEqual((self.root / name).stat().st_ino, inode)
        self.assertFalse(project.is_modified)
        project.schematic().files[0].symbol("R1").set_attribute("Value", "10K")
        project.close(kicad_cli=self.root / "must-not-run")
        self.assertTrue(project.is_closed)
        self.assertEqual(len(self.archives()), 1)

    def test_discard_exits_without_io_and_rejects_owned_operational_handles(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic().files[0]
        placed = schematic.symbol("R1")
        attribute = placed.attribute("Value")
        placed.set_attribute("Value", "pending")
        before = {p: (p.read_bytes(), p.stat().st_ino) for p in (self.pro, self.sch)}
        project.discard()
        project.close()
        self.assertEqual(attribute.value, "10K")
        self.assertEqual({p: (p.read_bytes(), p.stat().st_ino) for p in before}, before)
        self.assertFalse((self.root / "board-backups").exists())
        for action in (
            lambda: project.schematic().files[0],
            lambda: project.save(),
            lambda: schematic.save(),
            lambda: schematic.to_bytes(),
            lambda: schematic.symbol("R1"),
            lambda: placed.set_attribute("Value", "late"),
        ):
            with self.assertRaises(RuntimeError):
                action()

    def test_complete_native_allowlist_opaque_pcb_and_hidden_unrelated_omissions(
        self,
    ) -> None:
        pcb = self.root / "board.kicad_pcb"
        raw_pcb = b'(kicad_pcb (version 20260206)\r\n (opaque "keep" 001.00))\r\n'
        pcb.write_bytes(raw_pcb)
        expected = {
            self.pro.name: self.pro.read_bytes(),
            self.sch.name: SOURCE,
            pcb.name: raw_pcb,
        }
        for extension in (
            "kicad_prl",
            "kicad_sch",
            "kicad_sym",
            "kicad_pcb",
            "kicad_mod",
            "kicad_dru",
            "kicad_wks",
            "kicad_jobset",
            "json",
            "wbk",
        ):
            name = f"asset.{extension}"
            raw = f"opaque {extension}".encode()
            (self.root / name).write_bytes(raw)
            expected[name] = raw
        for name in ("fp-lib-table", "sym-lib-table", "design-block-lib-table"):
            (self.root / name).write_bytes(b"raw rows and flags")
            expected[name] = b"raw rows and flags"
        (self.root / "legit-backups").mkdir()
        (self.root / "legit-backups/asset.json").write_bytes(b"local data")
        expected["legit-backups/asset.json"] = b"local data"
        for name in (".history", ".git", ".hidden", "board-backups"):
            (self.root / name).mkdir()
            (self.root / name / "omit.json").write_bytes(b"omit")
        (self.root / "unrelated.txt").write_bytes(b"omit")
        project = Project.open(self.pro)
        before = {
            p: (p.read_bytes(), p.stat().st_ino) for p in (self.pro, self.sch, pcb)
        }
        project.save(kicad_cli=self.root / "no-cli")
        with zipfile.ZipFile(self.archives()[0]) as archive:
            self.assertEqual({n: archive.read(n) for n in archive.namelist()}, expected)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_ino) for p in before}, before)
        self.assertFalse((self.root / ".history/HEAD").exists())

    def test_opaque_pcb_freshness_missing_and_changed_companion_membership(
        self,
    ) -> None:
        pcb = self.root / "board.kicad_pcb"
        pcb.write_bytes(b'(kicad_pcb (version 20260206) (opaque "original"))')
        project = Project.open(self.pro)
        pcb.write_bytes(pcb.read_bytes() + b"\n")
        with self.assertRaises(SchematicConflictError):
            project.save()
        pcb.unlink()
        with self.assertRaises(SchematicConflictError):
            project.save()
        project = Project.open(self.pro)
        pcb.write_bytes(b"(kicad_pcb (version 20260206))")
        with self.assertRaises(SchematicConflictError):
            project.save()
        self.assertFalse(self.archives())

    def test_repeated_sheetfile_identity_cannot_hide_an_unvisited_missing_sheet(
        self,
    ) -> None:
        project, _ = self.hierarchy()
        raw = self.sch.read_bytes().replace(
            b'(property "Sheetfile" "sub/child.kicad_sch")',
            b'(property "Sheetfile" "missing.kicad_sch") (property "Sheetfile" "sub/child.kicad_sch")',
        )
        self.sch.write_bytes(raw)
        with self.assertRaises(ValueError):
            project.save()
        self.assertFalse(self.archives())

    def test_prebuilt_zip_failure_does_not_write_source(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic().files[0]
        schematic.symbol("R1").set_attribute("Value", "22K")
        with (
            patch(
                "zipfile.ZipFile.writestr", side_effect=OSError("compression failed")
            ),
            self.assertRaises(ProjectBackupError),
        ):
            project.save(kicad_cli=self.verifier())
        self.assertEqual(self.sch.read_bytes(), SOURCE)
        self.assertTrue(schematic.is_modified)
        self.assertFalse(self.archives())
        project.discard()
        self.assertEqual(self.sch.read_bytes(), SOURCE)

    def test_publication_failure_retains_saved_baseline_and_close_retries_history(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic().files[0]
        schematic.symbol("R1").set_attribute("Value", "22K")
        with (
            patch(
                "kicad_primitives._symbol_persist.os.link",
                side_effect=OSError("publication failed"),
            ),
            self.assertRaises(ProjectBackupError),
        ):
            project.save(kicad_cli=self.verifier())
        self.assertEqual(self.sch.read_bytes(), SOURCE.replace(b'"10K"', b'"22K"'))
        self.assertFalse(schematic.is_modified)
        self.assertFalse(self.archives())
        project.close(kicad_cli=self.root / "not-needed")
        self.assertTrue(project.is_closed)
        with zipfile.ZipFile(self.archives()[0]) as archive:
            self.assertEqual(archive.read(self.sch.name), self.sch.read_bytes())

    def test_partial_source_failure_advances_only_successful_baselines_and_has_no_archive(
        self,
    ) -> None:
        project, child_path = self.hierarchy()
        root, child = project.schematic().files
        root.symbol("R1").set_attribute("Value", "22K")
        child.symbol("R2").set_attribute("Value", "33K")
        child_original = child_path.read_bytes()
        real_replace = os.replace

        def fail_child(source: Path, target: Path) -> None:
            if target == child_path:
                raise OSError("second source failed")
            real_replace(source, target)

        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace", side_effect=fail_child
            ),
            self.assertRaises(OSError),
        ):
            project.save(kicad_cli=self.verifier())
        self.assertFalse(root.is_modified)
        self.assertTrue(child.is_modified)
        self.assertEqual(child_path.read_bytes(), child_original)
        self.assertFalse(self.archives())
        project.save(kicad_cli=self.verifier())
        self.assertFalse(project.is_modified)
        with zipfile.ZipFile(self.archives()[0]) as archive:
            self.assertEqual(archive.read("sub/child.kicad_sch"), child.to_bytes())

    def test_document_save_archives_selected_output_not_pending_sibling(
        self,
    ) -> None:
        project, child_path = self.hierarchy()
        root, child = project.schematic().files
        child_original = child.to_bytes()
        root.symbol("R1").set_attribute("Value", "22K")
        child.symbol("R2").set_attribute("Value", "33K")
        child_path.chmod(0o444)
        self.addCleanup(child_path.chmod, 0o644)
        root.save(kicad_cli=self.verifier())
        with zipfile.ZipFile(self.archives()[0]) as archive:
            self.assertEqual(archive.read("board.kicad_sch"), root.to_bytes())
            self.assertEqual(archive.read("sub/child.kicad_sch"), child_original)
        self.assertTrue(child.is_modified)
        self.assertTrue(project.is_modified)
        project.discard()
        self.assertEqual(child_path.read_bytes(), child_original)

    def test_exact_revert_and_failed_clean_save_still_close_without_writing(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic().files[0]
        schematic.symbol("R1").set_attribute("Value", "22K")
        schematic.symbol("R1").set_attribute("Value", "10K")
        self.assertFalse(project.is_modified)
        self.pro.write_bytes(self.pro.read_bytes() + b"\n")
        foreign = self.pro.read_bytes()
        with self.assertRaises(SchematicConflictError):
            project.save()
        project.close(kicad_cli=self.root / "must-not-run")
        self.assertTrue(project.is_closed)
        self.assertEqual(self.pro.read_bytes(), foreign)
        self.assertEqual(self.sch.read_bytes(), SOURCE)
        self.assertFalse(self.archives())

    def test_unreadable_linked_or_unsafe_archive_member_fails_before_original_replacement(
        self,
    ) -> None:
        for kind in (
            "unreadable",
            "symlink",
            "hardlink",
            "backslash",
            "reserved",
            "wildcard",
            "drive",
        ):
            with self.subTest(kind=kind):
                path = self.root / {
                    "backslash": "bad\\member.json",
                    "reserved": "CON.json",
                    "wildcard": "bad?.json",
                    "drive": "C:member.json",
                }.get(kind, "asset.json")
                if kind == "symlink":
                    path.symlink_to(self.pro)
                elif kind == "hardlink":
                    os.link(self.pro, path)
                else:
                    path.write_bytes(b"asset")
                    if kind == "unreadable":
                        path.chmod(0o000)
                try:
                    project = Project.open(self.pro)
                    project.schematic().files[0].symbol("R1").set_attribute(
                        "Value", "22K"
                    )
                    with self.assertRaises((OSError, ValueError)):
                        project.save(kicad_cli=self.verifier())
                    self.assertEqual(self.sch.read_bytes(), SOURCE)
                    self.assertFalse(self.archives())
                finally:
                    path.unlink()

    def test_required_hidden_child_is_not_silently_omitted_from_archive(self) -> None:
        project, _ = self.hierarchy(".hidden/child.kicad_sch")
        project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        before = self.sch.read_bytes()
        with self.assertRaises(ProjectBackupError):
            project.save(kicad_cli=self.verifier())
        self.assertEqual(self.sch.read_bytes(), before)
        self.assertFalse(self.archives())

    def test_full_unloaded_hierarchy_is_strict_even_on_clean_save(self) -> None:
        project, child_path = self.hierarchy()
        child_path.unlink()
        with self.assertRaises(InvalidSchematicError):
            project.save(kicad_cli=self.root / "no-cli")
        self.assertFalse(self.archives())
        self.sch.write_bytes(
            self.sch.read_bytes().replace(b"sub/child.kicad_sch", b"board.kicad_sch")
        )
        with self.assertRaises(UnsupportedSchematicOperationError):
            Project.open(self.pro).save()

    def test_later_pending_edit_during_verification_cannot_be_written_or_settled(
        self,
    ) -> None:
        project = Project.open(self.pro)
        placed = project.schematic().files[0].symbol("R1")
        placed.set_attribute("Value", "22K")
        cli = self.verifier()
        real_run = subprocess.run
        changed = False

        def edit_after_export(
            command: list[str],
            *,
            check: bool,
            capture_output: bool,
            text: bool,
            timeout: int,
        ) -> subprocess.CompletedProcess[str]:
            nonlocal changed
            result = real_run(
                command,
                check=check,
                capture_output=capture_output,
                text=text,
                timeout=timeout,
            )
            if not changed:
                changed = True
                placed.set_attribute("Value", "33K")
            return result

        with (
            patch(
                "kicad_primitives.netlist.subprocess.run", side_effect=edit_after_export
            ),
            self.assertRaises(RuntimeError),
        ):
            project.save(kicad_cli=cli)
        self.assertEqual(placed.value, "33K")
        self.assertEqual(self.sch.read_bytes(), SOURCE)
        self.assertTrue(project.is_modified)
        self.assertFalse(self.archives())
        project.discard()

    def test_later_pending_edit_during_source_write_keeps_frozen_baseline_and_archive(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic().files[0]
        placed = schematic.symbol("R1")
        placed.set_attribute("Value", "22K")
        frozen = schematic.to_bytes()
        real_replace = os.replace
        changed = False

        def edit_after_write(source: Path, target: Path) -> None:
            nonlocal changed
            real_replace(source, target)
            if target == self.sch and not changed:
                changed = True
                placed.set_attribute("Value", "33K")

        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace",
                side_effect=edit_after_write,
            ),
            self.assertRaises(RuntimeError),
        ):
            project.save(kicad_cli=self.verifier())
        self.assertEqual(self.sch.read_bytes(), frozen)
        self.assertEqual(placed.value, "33K")
        self.assertTrue(schematic.is_modified)
        with zipfile.ZipFile(self.archives()[0]) as archive:
            self.assertEqual(archive.read(self.sch.name), frozen)
        project.save(kicad_cli=self.verifier())
        self.assertFalse(project.is_modified)
        self.assertEqual(self.sch.read_bytes(), frozen.replace(b'"22K"', b'"33K"'))

    def test_archive_member_change_during_prebuild_is_not_adopted_or_overwritten(
        self,
    ) -> None:
        asset = self.root / "asset.json"
        asset.write_bytes(b"original member")
        project = Project.open(self.pro)
        project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        real_close = zipfile.ZipFile.close
        changed = False

        def change_after_prebuild(archive: zipfile.ZipFile) -> None:
            nonlocal changed
            real_close(archive)
            if archive.mode == "w" and archive.filename is None and not changed:
                changed = True
                asset.write_bytes(b"foreign member")

        with (
            patch("zipfile.ZipFile.close", new=change_after_prebuild),
            self.assertRaises(ProjectBackupError),
        ):
            project.save(kicad_cli=self.verifier())
        self.assertEqual(self.sch.read_bytes(), SOURCE)
        self.assertEqual(asset.read_bytes(), b"foreign member")
        self.assertTrue(project.is_modified)
        self.assertFalse(self.archives())

    def test_identical_content_under_new_filename_is_a_distinct_complete_snapshot(
        self,
    ) -> None:
        old = self.root / "old.json"
        old.write_bytes(b"same contents")
        project = Project.open(self.pro)
        project.save()
        first = self.archives()[0]
        old.rename(self.root / "renamed.json")
        project.save()
        self.assertEqual(len(self.archives()), 2)
        second = next(path for path in self.archives() if path != first)
        with zipfile.ZipFile(first) as archive:
            self.assertIn("old.json", archive.namelist())
            self.assertNotIn("renamed.json", archive.namelist())
        with zipfile.ZipFile(second) as archive:
            self.assertNotIn("old.json", archive.namelist())
            self.assertEqual(archive.read("renamed.json"), b"same contents")

    def test_hidden_git_history_state_is_not_read_and_no_git_command_is_executed(
        self,
    ) -> None:
        for folder in (".git", ".history"):
            (self.root / folder).mkdir()
            (self.root / folder / "config.json").write_bytes(b"invalid configuration")
        project = Project.open(self.pro)
        real_read = Path.read_bytes

        def guard_read(path: Path) -> bytes:
            self.assertFalse({".git", ".history"}.intersection(path.parts))
            return real_read(path)

        with (
            patch("pathlib.Path.read_bytes", new=guard_read),
            patch(
                "subprocess.run",
                side_effect=AssertionError("clean save executed a command"),
            ),
        ):
            project.save()
        self.assertEqual(len(self.archives()), 1)

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
        schematic = project.schematic().files[0]
        embedded = schematic.embedded_symbol("Device:R")
        placed = schematic.symbol("R1")
        project.discard()
        for action in (
            lambda: embedded.restore_from(parent, "R"),
            lambda: placed.attribute("Value"),
            lambda: schematic.embedded_symbols,
            lambda: project.erc(),
            lambda: project.schematic_files(),
        ):
            with self.assertRaises(RuntimeError):
                action()
        self.assertFalse(self.archives())

    def test_native_pro_schematic_pcb_and_unloaded_child_locks_block_actual_owned_paths(
        self,
    ) -> None:
        _, child = self.hierarchy()
        root = self.sch
        pcb = self.root / "board.kicad_pcb"
        pcb.write_bytes(b'(kicad_pcb (version 20260206) (generator "pcbnew"))')
        paths = (self.pro, root, pcb, child)
        original = {path: (path.read_bytes(), path.stat().st_ino) for path in paths}
        for source in paths:
            with self.subTest(source=source):
                lock = source.with_name(f"~{source.name}.lck")
                lock.write_bytes(b"native peer lock")
                try:
                    project = Project.open(self.pro)
                    schematic = project.schematic().files[0]
                    schematic.symbol("R1").set_attribute("Value", "22K")
                    # The child remains unloaded until the complete save walk.
                    for save in (project.save, schematic.save):
                        with self.assertRaises(ProjectWriteBlockedError):
                            save(kicad_cli=self.root / "must-not-run")
                    self.assertTrue(project.is_locked)
                    self.assertEqual(
                        {
                            path: (path.read_bytes(), path.stat().st_ino)
                            for path in paths
                        },
                        original,
                    )
                    self.assertFalse(self.archives())
                    self.assertTrue(lock.is_file())
                    self.assertEqual(schematic.symbol("R1").value, "22K")
                    project.discard()
                finally:
                    lock.unlink()

    def test_native_child_lock_appearing_after_first_write_blocks_later_source(
        self,
    ) -> None:
        project, child_path = self.hierarchy()
        root, child = project.schematic().files
        root.symbol("R1").set_attribute("Value", "22K")
        child.symbol("R2").set_attribute("Value", "33K")
        original_child = child_path.read_bytes()
        lock = child_path.with_name(f"~{child_path.name}.lck")
        real_replace = os.replace

        def peer_opens_child(source: Path, target: Path) -> None:
            real_replace(source, target)
            if target == root.path:
                lock.write_bytes(b"peer opened child")

        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace",
                side_effect=peer_opens_child,
            ),
            self.assertRaises(ProjectWriteBlockedError),
        ):
            project.save(kicad_cli=self.verifier())
        self.assertFalse(root.is_modified)
        self.assertTrue(child.is_modified)
        self.assertEqual(child_path.read_bytes(), original_child)
        self.assertTrue(lock.exists())
        self.assertFalse(self.archives())
        lock.unlink()
        project.save(kicad_cli=self.verifier())
        project.close()

    def test_native_lock_appearing_after_source_write_blocks_history_and_requires_retry(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic().files[0]
        schematic.symbol("R1").set_attribute("Value", "22K")
        lock = project.lock_file
        real_replace = os.replace

        def peer_opens_project(source: Path, target: Path) -> None:
            real_replace(source, target)
            if target == schematic.path:
                lock.write_bytes(b"peer opened Project")

        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace",
                side_effect=peer_opens_project,
            ),
            self.assertRaises(ProjectWriteBlockedError),
        ):
            project.save(kicad_cli=self.verifier())
        self.assertFalse(project.is_modified)
        self.assertFalse(self.archives())
        self.assertTrue(lock.exists())
        with self.assertRaises(ProjectWriteBlockedError):
            project.close(kicad_cli=self.root / "not-needed")
        self.assertFalse(project.is_closed)
        self.assertFalse(self.archives())
        lock.unlink()
        project.close(kicad_cli=self.root / "not-needed")
        self.assertTrue(project.is_closed)
        self.assertEqual(len(self.archives()), 1)
