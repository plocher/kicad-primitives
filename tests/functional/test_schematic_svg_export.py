"""Project-owned schematic SVG export over the pending snapshot (#64).

Lifted from kproj ``schematic_exporter`` (``sch export svg --output DIR``,
one SVG per sheet, zero output is an error) through the public project surface.
"""

import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.netlist import KicadCliNotFoundError
from kicad_primitives.projects import Project, ProjectLifecycleError
from kicad_primitives.schematics import (
    SchematicConflictError,
    SchematicSvgError,
    SchematicSvgExport,
    UnsupportedSchematicOperationError,
)
from tests.functional.test_schematic_editing import SOURCE

# Fake backend: one SVG per staged sheet using KiCad's root-sheet naming, each
# embedding the staged Value text so tests can see pending content.
FAKE_CLI = """#!/usr/bin/env python3
import json, os, pathlib, re, sys
args = sys.argv[1:]
root = pathlib.Path(args[-1])
out = pathlib.Path(args[args.index('--output') + 1])
record = os.environ.get('KP_RECORD')
if record:
    pathlib.Path(record).write_text(json.dumps({'argv': args}))
mode = os.environ.get('KP_MODE', '')
pages = {root.stem: root}
if mode != 'omit-child':
    pages[root.stem + '-Child'] = root.parent / 'sub/child.kicad_sch'
if mode == 'extra':
    pages[root.stem + '-Unknown'] = root
if mode == 'none':
    pages = {}
for stem, sheet in pages.items():
    value = re.search(r'"Value" "([^"]*)"', sheet.read_text()).group(1)
    (out / (stem + '.svg')).write_text('<svg>' + value + '</svg>')
print('Done.')
"""


class SchematicSvgExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.directory = self.base / "board"
        self.directory.mkdir()
        self.pro = self.directory / "board.kicad_pro"
        self.pro.write_text("{}", encoding="utf-8")
        self.path = self.directory / "board.kicad_sch"
        self.path.write_bytes(
            SOURCE.replace(
                b"(generator eeschema)",
                b"(generator eeschema) (sheet (at 0 0) (size 10 10) "
                b'(property "Sheetname" "Child") '
                b'(property "Sheetfile" "sub/child.kicad_sch"))',
            )
        )
        self.child = self.directory / "sub/child.kicad_sch"
        self.child.parent.mkdir()
        self.child.write_bytes(
            SOURCE.replace(b"R1", b"R2").replace(b"uuid-r1", b"uuid-r2")
        )
        self.cli = self.base / "fake-cli"
        self.cli.write_text(FAKE_CLI, encoding="utf-8")
        self.cli.chmod(0o755)
        self.project = Project.open(self.directory)
        self.out = self.base / "svg"

    def export(self, mode: str = "", **kwargs: object) -> SchematicSvgExport:
        with patch.dict(os.environ, {"KP_MODE": mode}):
            return self.project.export_svgs(self.out, kicad_cli=self.cli, **kwargs)  # type: ignore[arg-type]

    def test_exports_pending_hierarchy_with_sheet_mapping_without_saving(self) -> None:
        root, _child = self.project.schematics()
        originals = (self.path.read_bytes(), self.child.read_bytes())
        root.symbol("R1").set_attribute("Value", "22K")
        result = self.export()
        self.assertEqual(result.output_dir, self.out)
        self.assertEqual(
            [(f.path.name, f.sheet_path, f.source_path) for f in result.files],
            [
                ("board-Child.svg", "/Child/", self.child),
                ("board.svg", "/", self.path),
            ],
        )
        self.assertEqual((self.out / "board.svg").read_text(), "<svg>22K</svg>")
        self.assertEqual((self.out / "board-Child.svg").read_text(), "<svg>10K</svg>")
        self.assertEqual(
            sorted(p.name for p in self.out.iterdir()), ["board-Child.svg", "board.svg"]
        )
        self.assertEqual((self.path.read_bytes(), self.child.read_bytes()), originals)
        self.assertTrue(self.project.is_modified)
        self.assertEqual(result.stdout.strip(), "Done.")
        self.assertEqual(
            result.snapshot.documents[0].sha256,
            hashlib.sha256(root.to_bytes()).hexdigest(),
        )
        self.assertTrue(result.snapshot.documents[0].is_modified)

    def test_backend_command_uses_staged_root_and_no_extra_plot_options(self) -> None:
        record = self.base / "record.json"
        with patch.dict(os.environ, {"KP_RECORD": str(record)}):
            self.export()
        argv = json.loads(record.read_text())["argv"]
        self.assertEqual(argv[:4], ["sch", "export", "svg", "--output"])
        self.assertEqual(len(argv), 6)
        self.assertEqual(Path(argv[-1]).name, "board.kicad_sch")
        self.assertNotEqual(Path(argv[-1]), self.path)
        self.assertFalse(Path(argv[-1]).exists())

    def test_unproved_files_are_returned_without_mapping(self) -> None:
        result = self.export("extra")
        unknown = [f for f in result.files if f.path.name == "board-Unknown.svg"]
        self.assertEqual(len(unknown), 1)
        self.assertIsNone(unknown[0].sheet_path)
        self.assertIsNone(unknown[0].source_path)

    def test_existing_or_unsafe_destinations_are_refused_before_backend(self) -> None:
        self.out.mkdir()
        with self.assertRaises(FileExistsError):
            self.project.export_svgs(self.out, kicad_cli=self.base / "missing")
        link = self.base / "link"
        link.symlink_to(self.base / "nowhere")
        with self.assertRaises(FileExistsError):
            self.project.export_svgs(link, kicad_cli=self.base / "missing")
        linked_parent = self.base / "parent-link"
        linked_parent.symlink_to(self.base)
        with self.assertRaises(UnsupportedSchematicOperationError):
            self.project.export_svgs(
                linked_parent / "new", kicad_cli=self.base / "missing"
            )
        with self.assertRaises(FileNotFoundError):  # parents are never created
            self.project.export_svgs(
                self.base / "absent/new", kicad_cli=self.base / "missing"
            )
        readonly = self.base / "readonly"
        readonly.mkdir(mode=0o555)
        self.addCleanup(readonly.chmod, 0o755)
        with self.assertRaises(PermissionError):
            self.project.export_svgs(readonly / "new", kicad_cli=self.base / "missing")
        self.assertFalse((readonly / "new").exists())

    def test_acquisition_failures_raise_and_never_create_output(self) -> None:
        with self.assertRaises(KicadCliNotFoundError):
            self.project.export_svgs(self.out, kicad_cli=self.base / "missing")
        for mode in ("none", "omit-child"):
            with self.subTest(mode=mode), self.assertRaises(SchematicSvgError):
                self.export(mode)
            self.assertFalse(self.out.exists())
        self.cli.write_text("#!/bin/sh\necho boom >&2\nexit 4\n", encoding="utf-8")
        with self.assertRaises(SchematicSvgError) as caught:
            self.export()
        self.assertIn("boom", str(caught.exception))
        self.assertFalse(self.out.exists())

    def test_locked_project_exports_and_closed_or_unsupported_fail(self) -> None:
        (self.directory / "~board.kicad_pro.lck").touch()
        locked = Project.open(self.directory)
        self.assertEqual(len(locked.export_svgs(self.out, kicad_cli=self.cli).files), 2)
        (self.directory / "other.kicad_pro").write_text("{}", encoding="utf-8")
        with self.assertRaises(UnsupportedSchematicOperationError):
            Project.open(self.directory / "other.kicad_pro").export_svgs(
                self.base / "other", kicad_cli=self.cli
            )
        self.child.unlink()
        with self.assertRaises(SchematicConflictError):
            self.project.export_svgs(self.base / "gone", kicad_cli=self.cli)
        self.project.discard()
        with self.assertRaises(ProjectLifecycleError):
            self.project.export_svgs(self.base / "closed", kicad_cli=self.cli)


if __name__ == "__main__":
    unittest.main()
