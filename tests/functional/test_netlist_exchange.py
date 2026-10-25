"""Netlist exchange parse/export gates (Subdivision donor anchors).

Donor anchors (behavior only):
- FieldUnit-Subdivision/tests/test_kicad_plant_graph.py NetlistReaderTests
- FieldUnit-Subdivision/tools/contract/netlist_diff.py connectivity rule
- FieldUnit-Subdivision KicadCliExporterSmokeTests (discovery, not live KiCad)

Package locks:
- ``Netlist.open`` needs no KiCad install.
- Exchange data is not project-owned Connectivity.
- Export uses private ADR 0007 discovery; failures stay explicit.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives._kicad_cli import KicadCliNotFoundError
from kicad_primitives.netlist import (
    Netlist,
    NetlistExportError,
    NetlistParseError,
    connectivity_sets,
    export_netlist,
    obtain_netlist,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MINIMAL_NET = FIXTURES / "minimal_plant.net"


class NetlistParseTests(unittest.TestCase):
    def test_reads_components_and_nets_from_fixture(self) -> None:
        model = Netlist.open(MINIMAL_NET)
        self.assertEqual(model.source, "minimal_plant.kicad_sch")
        self.assertIn("SW783", model.components)
        self.assertEqual(model.components["SW783"].part, "Switch_Powered")
        self.assertEqual(model.component("DOT1").value, "MT")
        self.assertEqual(model.component("DOT1").fields.get("Rulebook"), "261")
        self.assertEqual(model.component("S784S1").value, "784SAB")
        self.assertEqual(model.component("SW783").lib_id, "Railroad:Switch_Powered")

        west = model.net("/MT_WEST")
        self.assertEqual(
            {(n.reference, n.pin) for n in west.nodes},
            {("B1", "1"), ("DOT1", "2")},
        )
        signal = model.net("Net-(B1-SIGNAL)")
        self.assertEqual(
            {(n.reference, n.pin) for n in signal.nodes},
            {("B1", "3"), ("S784S1", "1")},
        )

    def test_connectivity_sets_ignore_names_and_singletons(self) -> None:
        model = Netlist.open(MINIMAL_NET)
        sets = connectivity_sets(model)
        self.assertIn(frozenset({("B1", "1"), ("DOT1", "2")}), sets)
        self.assertIn(frozenset({("B1", "3"), ("S784S1", "1")}), sets)
        without_b = connectivity_sets(model, ignore=re.compile(r"^B"))
        self.assertNotIn(frozenset({("B1", "1"), ("DOT1", "2")}), without_b)

    def test_missing_and_invalid_files(self) -> None:
        with self.assertRaises(FileNotFoundError):
            Netlist.open(FIXTURES / "no-such.net")
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "not-export.net"
            bad.write_text("(kicad_sch (version 20251024))\n", encoding="utf-8")
            with self.assertRaises(NetlistParseError):
                Netlist.open(bad)

    def test_lookup_failures(self) -> None:
        model = Netlist.open(MINIMAL_NET)
        with self.assertRaises(KeyError):
            model.component("NOPE")
        with self.assertRaises(KeyError):
            model.net("/missing")


class NetlistExportTests(unittest.TestCase):
    def test_export_requires_schematic_file(self) -> None:
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "gone.kicad_sch"
            with self.assertRaises(FileNotFoundError):
                export_netlist(missing)

    def test_export_uses_resolved_cli_and_writes_output(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sch = root / "board.kicad_sch"
            sch.write_text("(kicad_sch (version 20251024))\n", encoding="utf-8")
            out = root / "board.net"
            cli = root / "fake-kicad-cli"
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(0o755)

            def fake_run(command: list[str], **kwargs: object) -> object:
                del kwargs
                self.assertEqual(command[0], str(cli.resolve()))
                self.assertEqual(
                    command[1:6],
                    ["sch", "export", "netlist", "--format", "kicadsexpr"],
                )
                Path(command[command.index("-o") + 1]).write_text(
                    MINIMAL_NET.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

                class Result:
                    returncode = 0
                    stderr = ""
                    stdout = ""

                return Result()

            with patch("kicad_primitives.netlist.subprocess.run", side_effect=fake_run):
                path = export_netlist(sch, out, kicad_cli=cli)
            self.assertEqual(path, out.resolve())
            self.assertTrue(out.is_file())
            model = Netlist.open(out)
            self.assertEqual(model.source, "minimal_plant.kicad_sch")

    def test_obtain_parses_temp_export(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sch = root / "board.kicad_sch"
            sch.write_text("(kicad_sch (version 20251024))\n", encoding="utf-8")
            cli = root / "fake-kicad-cli"
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(0o755)

            def fake_run(command: list[str], **kwargs: object) -> object:
                del kwargs
                Path(command[command.index("-o") + 1]).write_text(
                    MINIMAL_NET.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

                class Result:
                    returncode = 0
                    stderr = ""
                    stdout = ""

                return Result()

            with patch("kicad_primitives.netlist.subprocess.run", side_effect=fake_run):
                model = obtain_netlist(sch, kicad_cli=cli)
            self.assertEqual(model.component("SW783").part, "Switch_Powered")

    def test_export_nonzero_exit_is_export_error(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sch = root / "board.kicad_sch"
            sch.write_text("(kicad_sch (version 20251024))\n", encoding="utf-8")
            cli = root / "fake-kicad-cli"
            cli.write_text("#!/bin/sh\n", encoding="utf-8")
            cli.chmod(0o755)

            class Result:
                returncode = 2
                stderr = "boom"
                stdout = ""

            with (
                patch(
                    "kicad_primitives.netlist.subprocess.run",
                    return_value=Result(),
                ),
                self.assertRaises(NetlistExportError),
            ):
                export_netlist(sch, root / "out.net", kicad_cli=cli)

    def test_export_discovery_miss(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sch = root / "board.kicad_sch"
            sch.write_text("(kicad_sch (version 20251024))\n", encoding="utf-8")
            with self.assertRaises(KicadCliNotFoundError):
                export_netlist(sch, kicad_cli=root / "missing-cli")


if __name__ == "__main__":
    unittest.main()
