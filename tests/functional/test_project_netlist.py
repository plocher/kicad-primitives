"""Project-owned Connectivity minimum: netlist obtain on the pending snapshot (#65)."""

import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.netlist import (
    KicadCliNotFoundError,
    NetlistExportError,
    NetlistParseError,
    connectivity_sets,
)
from kicad_primitives.projects import (
    Project,
    ProjectLifecycleError,
    ProjectSnapshot,
)
from kicad_primitives.schematics import (
    InvalidSchematicError,
    UnsupportedSchematicOperationError,
)
from tests.functional.test_schematic_editing import SOURCE

# Fake backend: report every staged schematic's R* reference and Value, the
# argv, and the staged .kicad_pro bytes, as a kicadsexpr export.
FAKE_CLI = """#!/usr/bin/env python3
import json, os, pathlib, re, sys
root = pathlib.Path(sys.argv[-1])
out = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])
comps, nodes = [], []
for sheet in sorted(root.parent.rglob('*.kicad_sch')):
    text = sheet.read_text()
    for ref, value in re.findall(
        r'"Reference" "(R[0-9]+)".*?"Value" "([^"]*)"', text, re.S
    ):
        comps.append('(comp (ref %s) (value "%s") (libsource (lib Device) (part R)))'
                     % (ref, value))
        nodes.append('(node (ref %s) (pin 1))' % ref)
record = os.environ.get('KP_RECORD')
if record:
    pathlib.Path(record).write_text(json.dumps(
        {'argv': sys.argv[1:], 'cwd': os.getcwd(),
         'pro': root.with_suffix('.kicad_pro').read_text()}))
out.write_text('(export (version E) (design (source "%s")) (components %s)'
               ' (nets (net (code 1) (name "N") %s)))'
               % (root, ' '.join(comps), ' '.join(nodes)))
"""


class ProjectNetlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve() / "board"
        self.directory.mkdir()
        self.pro = self.directory / "board.kicad_pro"
        self.pro.write_text('{"text_variables": {"V": "1"}}', encoding="utf-8")
        self.path = self.directory / "board.kicad_sch"
        self.path.write_bytes(
            SOURCE.replace(
                b"(generator eeschema)",
                b"(generator eeschema) (sheet (at 0 0) (size 10 10) "
                b'(property "Sheetfile" "sub/child.kicad_sch"))',
            )
        )
        self.child = self.directory / "sub/child.kicad_sch"
        self.child.parent.mkdir()
        self.child.write_bytes(
            SOURCE.replace(b"R1", b"R2").replace(b"uuid-r1", b"uuid-r2")
        )
        self.cli = Path(self.temp.name) / "fake-cli"
        self.cli.write_text(FAKE_CLI, encoding="utf-8")
        self.cli.chmod(0o755)
        self.project = Project.open(self.directory)

    def test_netlist_reflects_pending_hierarchy_without_saving(self) -> None:
        root, child = self.project.schematic().files
        originals = (self.path.read_bytes(), self.child.read_bytes())
        root.symbol("R1").set_attribute("Value", "22K")
        child.symbol("R2").set_attribute("Value", "33K")
        netlist = self.project.netlist(kicad_cli=self.cli)
        self.assertEqual(netlist.component("R1").value, "22K")
        self.assertEqual(netlist.component("R2").value, "33K")
        self.assertEqual(
            connectivity_sets(netlist),
            frozenset({frozenset({("R1", "1"), ("R2", "1")})}),
        )
        self.assertEqual((self.path.read_bytes(), self.child.read_bytes()), originals)
        self.assertTrue(self.project.is_modified)
        self.assertTrue(root.is_modified and child.is_modified)

    def test_provenance_records_project_and_checked_content(self) -> None:
        root, child = self.project.schematic().files
        root.symbol("R1").set_attribute("Value", "22K")
        netlist = self.project.netlist(kicad_cli=self.cli)
        provenance = netlist.provenance
        assert provenance is not None
        self.assertIsInstance(provenance, ProjectSnapshot)
        self.assertEqual(provenance.project_file, self.pro)
        self.assertEqual(
            provenance.project_sha256, hashlib.sha256(self.pro.read_bytes()).hexdigest()
        )
        self.assertEqual(
            [(d.path, d.sha256, d.is_modified) for d in provenance.documents],
            [
                (root.path, hashlib.sha256(root.to_bytes()).hexdigest(), True),
                (child.path, hashlib.sha256(child.to_bytes()).hexdigest(), False),
            ],
        )
        # Freshness: a later edit makes the recorded hash stale.
        root.symbol("R1").set_attribute("Value", "47K")
        self.assertNotEqual(
            provenance.documents[0].sha256, hashlib.sha256(root.to_bytes()).hexdigest()
        )

    def test_backend_receives_kicadsexpr_and_captured_project_settings(self) -> None:
        captured = self.pro.read_text(encoding="utf-8")
        self.project.schematic().files[0]
        self.pro.write_text('{"text_variables": {"V": "later"}}', encoding="utf-8")
        record = Path(self.temp.name) / "record.json"
        with patch.dict(os.environ, {"KP_RECORD": str(record)}):
            netlist = self.project.netlist(kicad_cli=self.cli)
        seen = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(
            seen["argv"][:5], ["sch", "export", "netlist", "--format", "kicadsexpr"]
        )
        self.assertEqual(seen["pro"], captured)
        self.assertEqual(Path(seen["cwd"]).resolve(), self.directory)
        staged_root = Path(seen["argv"][-1])
        self.assertEqual(staged_root.name, "board.kicad_sch")
        self.assertNotEqual(staged_root, self.path)
        self.assertFalse(staged_root.exists())  # stage removed after obtain
        self.assertEqual(netlist.source, str(staged_root))

    def test_locked_and_readonly_projects_remain_obtainable(self) -> None:
        (self.directory / "~board.kicad_pro.lck").touch()
        self.path.chmod(0o444)
        self.addCleanup(self.path.chmod, 0o644)
        project = Project.open(self.directory)
        project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        self.assertEqual(
            project.netlist(kicad_cli=self.cli).component("R1").value, "22K"
        )

    def test_acquisition_failures_raise_and_keep_pending_state(self) -> None:
        self.project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        with self.assertRaises(KicadCliNotFoundError):
            self.project.netlist(kicad_cli=Path(self.temp.name) / "missing")
        self.cli.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        with self.assertRaises(NetlistExportError):
            self.project.netlist(kicad_cli=self.cli)
        self.cli.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        with self.assertRaises(NetlistExportError):
            self.project.netlist(kicad_cli=self.cli)
        self.cli.write_text(
            "#!/bin/sh\nfor a; do :; done\n"
            'while [ "$1" != -o ]; do shift; done; echo junk > "$2"\n',
            encoding="utf-8",
        )
        with self.assertRaises(NetlistParseError):
            self.project.netlist(kicad_cli=self.cli)
        self.assertTrue(self.project.is_modified)

    def test_unsupported_context_and_closed_project_fail_explicitly(self) -> None:
        other = self.directory.parent / "other"
        other.mkdir()
        (other / "board.kicad_sch").write_bytes(self.path.read_bytes())
        (other / "other.kicad_pro").write_text(
            '{"schematic": {"top_level_sheets": [{"filename": "board.kicad_sch"}]}}',
            encoding="utf-8",
        )
        mismatched = Project.open(other)
        with self.assertRaises(UnsupportedSchematicOperationError):
            mismatched.netlist(kicad_cli=self.cli)
        self.child.unlink()
        with self.assertRaises(InvalidSchematicError):
            self.project.netlist(kicad_cli=self.cli)
        self.project.discard()
        with self.assertRaises(ProjectLifecycleError):
            self.project.netlist(kicad_cli=self.cli)


if __name__ == "__main__":
    unittest.main()
