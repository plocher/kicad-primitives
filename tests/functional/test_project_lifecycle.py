"""Project decisions and ZIP safety snapshots through public artifact seams."""

import os
import subprocess
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.projects import Project, ProjectBackupError
from kicad_primitives.schematics import (
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

    def test_clean_project_save_captures_full_file_set_and_settles_close(self) -> None:
        project = Project.open(self.pro)
        with self.assertRaises(RuntimeError):
            project.close()
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
        project.schematic().symbol("R1").set_attribute("Value", "10K")
        project.close()
        self.assertTrue(project.is_closed)

    def test_discard_exits_without_io_and_rejects_owned_operational_handles(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic()
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
            lambda: project.schematic(),
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
            "kicad_pro",
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

    def test_same_second_archives_are_unique_and_zero_budget_means_unlimited(
        self,
    ) -> None:
        project = Project.open(self.pro, backup_size_limit_bytes=0)
        with patch("kicad_primitives._project_backup.datetime") as clock:
            clock.now.return_value.strftime.return_value = "2026-10-27_010203"
            for _ in range(3):
                project.save()
        self.assertEqual(
            {p.name for p in self.archives()},
            {
                "board-2026-10-27_010203.zip",
                "board-2026-10-27_010203-001.zip",
                "board-2026-10-27_010203-002.zip",
            },
        )
        for path in self.archives():
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.read(self.pro.name), self.pro.read_bytes())
        limited = Project.open(self.pro, backup_size_limit_bytes=1)
        with patch("kicad_primitives._project_backup.datetime") as clock:
            clock.now.return_value.strftime.return_value = "2026-10-27_010203"
            limited.save()
        self.assertEqual(len(self.archives()), 1)
        self.assertEqual(self.archives()[0].name, "board-2026-10-27_010203-003.zip")
        self.assertGreater(self.archives()[0].stat().st_size, 1)
        limited.close()

    def test_invalid_explicit_budget_fails_without_writing(self) -> None:
        for value in (-1, True, "100"):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                Project.open(self.pro, backup_size_limit_bytes=value)  # type: ignore[arg-type]
        self.assertFalse((self.root / "board-backups").exists())

    def test_opaque_pcb_freshness_missing_and_changed_companion_membership(
        self,
    ) -> None:
        pcb = self.root / "board.kicad_pcb"
        pcb.write_bytes(b'(kicad_pcb (version 20260206) (opaque "original"))')
        project = Project.open(self.pro)
        pcb.write_bytes(pcb.read_bytes() + b"\n")
        with self.assertRaises(SchematicConflictError):
            project.save()
        with self.assertRaises(RuntimeError):
            project.close()
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

    def test_prebuilt_zip_failure_does_not_write_source_or_authorize_close(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic()
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
        with self.assertRaises(RuntimeError):
            project.close()

    def test_publication_failure_retains_saved_baseline_and_clean_retry_makes_history(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic()
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
        with self.assertRaises(RuntimeError):
            project.close()
        project.save(kicad_cli=self.root / "not-needed")
        with zipfile.ZipFile(self.archives()[0]) as archive:
            self.assertEqual(archive.read(self.sch.name), self.sch.read_bytes())
        project.close()

    def test_partial_source_failure_advances_only_successful_baselines_and_has_no_archive(
        self,
    ) -> None:
        project, child_path = self.hierarchy()
        root, child = project.schematics()
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
        with self.assertRaises(RuntimeError):
            project.close()
        project.save(kicad_cli=self.verifier())
        self.assertFalse(project.is_modified)
        with zipfile.ZipFile(self.archives()[0]) as archive:
            self.assertEqual(archive.read("sub/child.kicad_sch"), child.to_bytes())

    def test_document_save_archives_selected_output_not_pending_sibling_and_does_not_settle_root(
        self,
    ) -> None:
        project, child_path = self.hierarchy()
        root, child = project.schematics()
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
        with self.assertRaises(RuntimeError):
            project.close()

    def test_failed_clean_save_and_later_real_edits_revoke_prior_decision(self) -> None:
        project = Project.open(self.pro)
        project.save()
        schematic = project.schematic()
        schematic.symbol("R1").set_attribute("Value", "22K")
        schematic.symbol("R1").set_attribute("Value", "10K")
        self.assertFalse(project.is_modified)
        with self.assertRaises(RuntimeError):
            project.close()
        project.save()
        self.pro.write_bytes(self.pro.read_bytes() + b"\n")
        with self.assertRaises(SchematicConflictError):
            project.save()
        with self.assertRaises(RuntimeError):
            project.close()

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
                    project.schematic().symbol("R1").set_attribute("Value", "22K")
                    with self.assertRaises((OSError, ValueError)):
                        project.save(kicad_cli=self.verifier())
                    self.assertEqual(self.sch.read_bytes(), SOURCE)
                    self.assertFalse(self.archives())
                finally:
                    path.unlink()

    def test_required_hidden_child_is_not_silently_omitted_from_archive(self) -> None:
        project, _ = self.hierarchy(".hidden/child.kicad_sch")
        project.schematic().symbol("R1").set_attribute("Value", "22K")
        before = self.sch.read_bytes()
        with self.assertRaises(ProjectBackupError):
            project.save(kicad_cli=self.verifier())
        self.assertEqual(self.sch.read_bytes(), before)
        self.assertFalse(self.archives())

    def test_full_unloaded_hierarchy_is_strict_even_on_clean_save(self) -> None:
        project, child_path = self.hierarchy()
        child_path.unlink()
        with self.assertRaises(SchematicConflictError):
            project.save(kicad_cli=self.root / "no-cli")
        self.assertFalse(self.archives())
        self.sch.write_bytes(
            self.sch.read_bytes().replace(b"sub/child.kicad_sch", b"board.kicad_sch")
        )
        with self.assertRaises(UnsupportedSchematicOperationError):
            Project.open(self.pro).save()

    def test_retention_removes_oldest_same_second_archive_not_newer_suffix(
        self,
    ) -> None:
        with patch("kicad_primitives._project_backup.datetime") as clock:
            clock.now.return_value.strftime.return_value = "2026-10-27_010203"
            Project.open(self.pro, backup_size_limit_bytes=0).save()
            size = self.archives()[0].stat().st_size
            project = Project.open(self.pro, backup_size_limit_bytes=size * 2)
            project.save()
            project.save()
        self.assertEqual(
            {p.name for p in self.archives()},
            {"board-2026-10-27_010203-001.zip", "board-2026-10-27_010203-002.zip"},
        )

    def test_later_pending_edit_during_verification_cannot_be_written_or_settled(
        self,
    ) -> None:
        project = Project.open(self.pro)
        placed = project.schematic().symbol("R1")
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
        with self.assertRaises(RuntimeError):
            project.close()

    def test_later_pending_edit_during_source_write_keeps_frozen_baseline_and_archive(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic()
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
        with self.assertRaises(RuntimeError):
            project.close()
        project.save(kicad_cli=self.verifier())
        self.assertFalse(project.is_modified)
        self.assertEqual(self.sch.read_bytes(), frozen.replace(b'"22K"', b'"33K"'))

    def test_archive_member_change_during_prebuild_is_not_adopted_or_overwritten(
        self,
    ) -> None:
        asset = self.root / "asset.json"
        asset.write_bytes(b"original member")
        project = Project.open(self.pro)
        project.schematic().symbol("R1").set_attribute("Value", "22K")
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

    def test_retention_failure_leaves_complete_new_archive_but_no_close_authorization(
        self,
    ) -> None:
        project = Project.open(self.pro, backup_size_limit_bytes=1)
        project.save()
        previous = self.archives()[0]
        project.schematic().symbol("R1").set_attribute("Value", "22K")
        real_unlink = Path.unlink

        def fail_previous(path: Path, *, missing_ok: bool = False) -> None:
            if path == previous:
                raise PermissionError("old snapshot protected")
            real_unlink(path, missing_ok=missing_ok)

        with (
            patch("pathlib.Path.unlink", new=fail_previous),
            self.assertRaises(ProjectBackupError),
        ):
            project.save(kicad_cli=self.verifier())
        self.assertEqual(len(self.archives()), 2)
        self.assertFalse(project.is_modified)
        with self.assertRaises(RuntimeError):
            project.close()
        for path in self.archives():
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
        project.save(kicad_cli=self.root / "not-needed")
        self.assertEqual(len(self.archives()), 1)
        project.close()

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

    def test_board_only_file_set_and_unsafe_native_board_formats(self) -> None:
        self.sch.unlink()
        pcb = self.root / "board.kicad_pcb"
        valid = b'(kicad_pcb (version 20260206) (generator "pcbnew"))'
        pcb.write_bytes(valid)
        project = Project.open(self.pro)
        project.save(kicad_cli=self.root / "not-needed")
        with zipfile.ZipFile(self.archives()[0]) as archive:
            self.assertEqual(set(archive.namelist()), {self.pro.name, pcb.name})
            self.assertEqual(archive.read(pcb.name), valid)
        project.close()
        for raw in (
            b"(kicad_pcb (version 20990101))",
            b"(kicad_pcb (version bad))",
            b"(wrong (version 20260206))",
            b"(",
        ):
            with self.subTest(raw=raw):
                pcb.write_bytes(raw)
                context = Project.open(self.pro)
                with self.assertRaises(ValueError):
                    context.save()
                self.assertEqual(pcb.read_bytes(), raw)
                with self.assertRaises(RuntimeError):
                    context.close()

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
        schematic = project.schematic()
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
