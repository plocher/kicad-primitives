"""Same-location persistence and electrical gates through the public objects."""

import os
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.netlist import KicadCliNotFoundError, NetlistExportError
from kicad_primitives.projects import Project, ProjectWriteBlockedError
from kicad_primitives.schematics import (
    SchematicConflictError,
    SchematicVerificationError,
    UnsupportedSchematicOperationError,
)
from tests.functional.test_schematic_editing import SOURCE


class SchematicPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "board.kicad_sch"
        self.path.write_bytes(SOURCE)
        self.pro = self.directory / "board.kicad_pro"
        self.pro.write_text("{}", encoding="utf-8")
        self.cli = self.directory / "fake-cli"
        self.cli.write_text(
            """#!/usr/bin/env python3
import pathlib, sys
root = pathlib.Path(sys.argv[-1])
assert root.name == 'board.kicad_sch'
assert root.with_suffix('.kicad_pro').is_file()
source = ''.join(p.read_text() for p in root.parent.rglob('*.kicad_sch'))
net = 'CHANGED' if 'disconnect' in source else 'signal'
component = '(comp (ref R1) (value ignored) (libsource (lib Device) (part R)))'
node = '(node (ref R1) (pin 1) (pinfunction ~) (pintype passive))'
if 'omit-component' in source:
    component = ''
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(
    '(export (version E) (components '+component+')'
    '(nets (net (code 1) (name "'+net+'") '+node+')))')
""",
            encoding="utf-8",
        )
        self.cli.chmod(0o755)
        self.project = Project.open(self.directory)
        self.schematic = self.project.schematic()

    def test_explicit_save_preserves_mode_and_updates_baselines(self) -> None:
        self.path.chmod(0o640)
        symbol = self.schematic.symbol("R1")
        symbol.set_attribute("Value", "22K")
        self.schematic.save(kicad_cli=self.cli)
        self.assertEqual(self.path.read_bytes(), SOURCE.replace(b'"10K"', b'"22K"'))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertFalse(self.project.is_modified)
        info = self.path.stat()
        self.project.save(kicad_cli=self.directory / "not-needed")
        self.assertEqual(self.path.stat().st_ino, info.st_ino)
        symbol.set_attribute("Value", "33K")
        self.project.save(kicad_cli=self.cli)
        self.assertFalse(self.schematic.is_modified)
        self.assertEqual(symbol.value, "33K")

    def test_named_singleton_net_change_and_component_loss_block_save(self) -> None:
        for value in ("disconnect", "omit-component"):
            with self.subTest(value=value):
                self.schematic.symbol("R1").set_attribute("MPN", value)
                with self.assertRaises(SchematicVerificationError):
                    self.project.save(kicad_cli=self.cli)
                self.assertEqual(self.path.read_bytes(), SOURCE)
                self.assertTrue(self.project.is_modified)

    def test_guard_stale_context_and_links_fail_before_verifier(self) -> None:
        self.schematic.symbol("R1").set_attribute("Value", "22K")
        lock = self.directory / "~board.kicad_pro.lck"
        lock.touch()
        with self.assertRaises(ProjectWriteBlockedError):
            self.project.save(kicad_cli=self.directory / "missing-cli")
        lock.unlink()
        self.pro.write_text('{"text_variables":{"X":"new"}}', encoding="utf-8")
        with self.assertRaises(SchematicConflictError):
            self.project.save(kicad_cli=self.directory / "missing-cli")
        self.pro.write_text("{}", encoding="utf-8")
        foreign = SOURCE + b"\n"
        self.path.write_bytes(foreign)
        with self.assertRaises(SchematicConflictError):
            self.schematic.save(kicad_cli=self.directory / "missing-cli")
        self.path.write_bytes(SOURCE)
        link = self.directory / "hardlink.kicad_sch"
        os.link(self.path, link)
        with self.assertRaises(UnsupportedSchematicOperationError):
            self.project.save(kicad_cli=self.directory / "missing-cli")
        self.assertEqual(self.path.read_bytes(), SOURCE)

    def hierarchy(self, child_name: str = "child.kicad_sch") -> tuple[Project, Path]:
        source = SOURCE.replace(
            b"(generator eeschema)",
            (
                "(generator eeschema) (sheet (at 0 0) (size 10 10) "
                f'(property "Sheetfile" "{child_name}"))'
            ).encode(),
        )
        self.path.write_bytes(source)
        child = self.directory / child_name
        if not child.is_absolute() or child.is_relative_to(self.directory):
            child.parent.mkdir(parents=True, exist_ok=True)
            child.write_bytes(
                SOURCE.replace(b"R1", b"R2").replace(b"uuid-r1", b"uuid-r2")
            )
        return Project.open(self.directory), child

    def test_document_save_stages_only_its_changes_project_save_gates_all(self) -> None:
        project, child_path = self.hierarchy("sub/child.kicad_sch")
        root, child = project.schematics()
        root_before, child_before = root.to_bytes(), child.to_bytes()
        root.symbol("R1").set_attribute("Value", "22K")
        child.symbol("R2").set_attribute("MPN", "disconnect")
        root.save(kicad_cli=self.cli)
        self.assertEqual(
            self.path.read_bytes(), root_before.replace(b'"10K"', b'"22K"')
        )
        self.assertEqual(child_path.read_bytes(), child_before)
        self.assertTrue(project.is_modified)
        with self.assertRaises(SchematicVerificationError):
            project.save(kicad_cli=self.cli)
        self.assertEqual(child_path.read_bytes(), child_before)

    def test_aggregate_failure_preflight_does_not_partially_save(self) -> None:
        project, child_path = self.hierarchy()
        root, child = project.schematics()
        original = self.path.read_bytes()
        root.symbol("R1").set_attribute("Value", "22K")
        child.symbol("R2").set_attribute("Value", "33K")
        child_path.chmod(0o444)
        self.addCleanup(child_path.chmod, 0o644)
        with self.assertRaises(PermissionError):
            project.save(kicad_cli=self.directory / "missing")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(root.is_modified)
        child_path.chmod(0o644)
        project.save(kicad_cli=self.cli)
        self.assertFalse(project.is_modified)
        self.assertIn(b'"33K"', child_path.read_bytes())

    def test_stale_unchanged_child_and_missing_hierarchy_fail_before_cli(self) -> None:
        project, child_path = self.hierarchy()
        root, _child = project.schematics()
        root.symbol("R1").set_attribute("Value", "22K")
        child_path.write_bytes(child_path.read_bytes() + b"\n")
        with self.assertRaises(SchematicConflictError):
            project.save(kicad_cli=self.directory / "missing")
        child_path.unlink()
        with self.assertRaises(SchematicConflictError):
            project.save(kicad_cli=self.directory / "missing")

    def test_symlink_storage_is_not_dereferenced_and_overwritten(self) -> None:
        target = self.directory / "target.kicad_sch"
        self.path.rename(target)
        self.path.symlink_to(target)
        project = Project.open(self.directory)
        project.schematic().symbol("R1").set_attribute("Value", "22K")
        with self.assertRaises(UnsupportedSchematicOperationError):
            project.save(kicad_cli=self.directory / "missing")
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_bytes(), SOURCE)

    def test_failed_verifier_and_replace_leave_pending_content_and_original(
        self,
    ) -> None:
        self.schematic.symbol("R1").set_attribute("Value", "22K")
        with self.assertRaises(KicadCliNotFoundError):
            self.project.save(kicad_cli=self.directory / "missing")
        self.cli.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
        with self.assertRaises(NetlistExportError):
            self.project.save(kicad_cli=self.cli)
        self.assertEqual(self.path.read_bytes(), SOURCE)
        self.assertTrue(self.schematic.is_modified)

    def test_replace_failure_keeps_original_and_pending_edits_for_retry(self) -> None:
        self.schematic.symbol("R1").set_attribute("Value", "22K")
        with (
            patch(
                "kicad_primitives._symbol_persist.os.replace",
                side_effect=OSError("failed"),
            ),
            self.assertRaises(OSError),
        ):
            self.project.save(kicad_cli=self.cli)
        self.assertEqual(self.path.read_bytes(), SOURCE)
        self.assertTrue(self.project.is_modified)
        self.assertEqual(list(self.directory.glob(".*.tmp")), [])
        self.project.save(kicad_cli=self.cli)
        self.assertFalse(self.project.is_modified)

    def test_incomplete_or_collapsed_export_evidence_cannot_authorize_save(
        self,
    ) -> None:
        for body in (
            "'(export (version E))'",
            """'(export (version E) (components '
            + ('(comp (ref R1) (libsource (lib Device) (part C)))'
               if '"22K"' in source else
               '(comp (ref R1) (libsource (lib Device) (part R)))'
               '(comp (ref R1) (libsource (lib Device) (part C)))')
            + ') (nets))'""",
        ):
            with self.subTest(body=body):
                self.cli.write_text(
                    "#!/usr/bin/env python3\nimport pathlib,sys\n"
                    "source = pathlib.Path(sys.argv[-1]).read_text()\n"
                    f"output = ({body})\n"
                    "pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(output)\n",
                    encoding="utf-8",
                )
                self.path.write_bytes(SOURCE)
                self.project = Project.open(self.directory)
                self.schematic = self.project.schematic()
                self.schematic.symbol("R1").set_attribute("Value", "22K")
                inode = self.path.stat().st_ino
                with self.assertRaises(SchematicVerificationError):
                    self.project.save(kicad_cli=self.cli)
                self.assertEqual(self.path.read_bytes(), SOURCE)
                self.assertEqual(self.path.stat().st_ino, inode)
                self.assertTrue(self.project.is_modified)

    def test_readonly_child_directory_preflights_before_any_replacement(self) -> None:
        project, child_path = self.hierarchy("sub/child.kicad_sch")
        root, child = project.schematics()
        originals = [
            (sheet.path.read_bytes(), sheet.path.stat().st_ino)
            for sheet in (root, child)
        ]
        root.symbol("R1").set_attribute("Value", "22K")
        child.symbol("R2").set_attribute("Value", "33K")
        child_path.parent.chmod(0o555)
        self.addCleanup(child_path.parent.chmod, 0o755)
        with self.assertRaises(PermissionError):
            project.save(kicad_cli=self.cli)
        for sheet, (raw, inode) in zip((root, child), originals, strict=True):
            self.assertEqual(sheet.path.read_bytes(), raw)
            self.assertEqual(sheet.path.stat().st_ino, inode)
        self.assertTrue(project.is_modified)
