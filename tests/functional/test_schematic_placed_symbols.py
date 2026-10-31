"""Placed-symbol and title-block read via project context (#28).

Donor behavior anchors (merged; not three half-readers):
- jBOM/tests/services/readers/test_schematic_reader.py (components + title block)
- FieldUnit-Subdivision SchematicPlacementReader (transform / unit / mirror)

Package rules:
- Schematics open only through Project (ADR 0002).
- Only top-level placed (symbol ...) nodes; lib_symbols definitions are not placements.
- Read-only; no edit writer in this slice.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import InvalidProjectError, Project
from kicad_primitives.schematics import (
    AmbiguousPlacedSymbolError,
    InvalidSchematicError,
    PlacedSymbol,
    Schematic,
    SheetFile,
    TitleBlock,
)


class SchematicCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="kp_sch_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative: str, contents: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def project_with(self, sch_name: str, sch_body: str) -> Project:
        self.write(f"{sch_name}.kicad_pro", json.dumps({"meta": {"version": 1}}))
        self.write(f"{sch_name}.kicad_sch", sch_body)
        return Project.open(self.root)


class OpenViaProjectTests(SchematicCase):
    def test_root_schematic_via_project(self) -> None:
        project = self.project_with(
            "board",
            """(kicad_sch (version 20250114)
  (title_block (title "Board") (rev "1"))
  (symbol (lib_id "Device:R") (at 1 2 0) (uuid u1)
    (property "Reference" "R1") (property "Value" "10k")
  )
)""",
        )
        self.assertIsInstance(project.schematic(), Schematic)
        schematic = project.schematic().files[0]
        self.assertIsInstance(schematic, SheetFile)
        self.assertEqual(project.schematic().root_files, (schematic,))
        self.assertEqual(schematic.path, (self.root / "board.kicad_sch").resolve())
        self.assertEqual(schematic.version, 20250114)
        self.assertEqual(schematic.title_block.title, "Board")
        self.assertEqual(schematic.title_block.revision, "1")
        self.assertEqual(len(schematic.symbols), 1)
        self.assertEqual(schematic.symbols[0].reference, "R1")

    def test_missing_root_schematic_raises(self) -> None:
        self.write("board.kicad_pro", json.dumps({"meta": {"version": 1}}))
        with self.assertRaises(InvalidProjectError):
            Project.open(self.root)

    def test_open_child_sheet_path_must_belong_to_hierarchy(self) -> None:
        self.write("main.kicad_pro", json.dumps({"meta": {"version": 1}}))
        self.write(
            "main.kicad_sch",
            """(kicad_sch (version 20250114)
  (sheet (at 0 0) (size 1 1)
    (property "Sheetname" "Child")
    (property "Sheetfile" "child.kicad_sch"))
)""",
        )
        child = self.write(
            "child.kicad_sch",
            """(kicad_sch (version 20250114)
  (symbol (lib_id "Device:C") (at 0 0 0) (uuid c1)
    (property "Reference" "C1") (property "Value" "100n"))
)""",
        )
        outsider = self.write(
            "other.kicad_sch",
            """(kicad_sch (version 20250114)
  (symbol (lib_id "Device:R") (at 0 0 0) (uuid r1)
    (property "Reference" "R9") (property "Value" "1"))
)""",
        )
        project = Project.open(self.root)
        opened = project.schematic().file(child)
        self.assertEqual([s.reference for s in opened.symbols], ["C1"])
        with self.assertRaises(KeyError):
            project.schematic().file(outsider)

    def test_schematics_lists_hierarchy_in_order(self) -> None:
        self.write("main.kicad_pro", json.dumps({"meta": {"version": 1}}))
        self.write(
            "main.kicad_sch",
            """(kicad_sch (version 20250114)
  (sheet (at 0 0) (size 1 1)
    (property "Sheetfile" "power.kicad_sch"))
  (symbol (lib_id "Device:R") (at 1 1 0) (uuid a)
    (property "Reference" "R1") (property "Value" "1k"))
)""",
        )
        self.write(
            "power.kicad_sch",
            """(kicad_sch (version 20250114)
  (symbol (lib_id "Device:C") (at 2 2 0) (uuid b)
    (property "Reference" "C1") (property "Value" "10u"))
)""",
        )
        project = Project.open(self.root)
        sheets = project.schematic().files
        self.assertEqual(
            [s.path.name for s in sheets],
            ["main.kicad_sch", "power.kicad_sch"],
        )
        self.assertEqual(
            [sym.reference for sheet in sheets for sym in sheet.symbols],
            ["R1", "C1"],
        )


class PlacedSymbolTests(SchematicCase):
    def test_merged_fields_transform_unit_flags(self) -> None:
        project = self.project_with(
            "flags",
            """(kicad_sch (version 20250114) (generator eeschema)
  (symbol (lib_id "Connector:Plug") (at 10 20 90) (unit 2) (mirror x)
    (in_bom yes) (on_board no) (in_pos_files no) (dnp yes) (exclude_from_sim yes)
    (uuid "deadbeef-0001")
    (property "Reference" "J22" (at 10 10 0))
    (property "Value" "PLUG" (at 10 12 0))
    (property "Footprint" "Conn:Plug" (at 10 14 0))
    (property "MPN" "ABC-1")
    (instances (project "flags" (path "/" (reference "J22") (unit 2))))
  )
)""",
        )
        symbol = project.schematic().files[0].symbol("J22")
        self.assertIsInstance(symbol, PlacedSymbol)
        self.assertEqual(symbol.reference, "J22")
        self.assertEqual(symbol.lib_id, "Connector:Plug")
        self.assertEqual(symbol.uuid, "deadbeef-0001")
        self.assertEqual(symbol.value, "PLUG")
        self.assertEqual(symbol.footprint, "Conn:Plug")
        self.assertEqual(symbol.x, 10.0)
        self.assertEqual(symbol.y, 20.0)
        self.assertEqual(symbol.rotation, 90.0)
        self.assertEqual(symbol.mirror, "x")
        self.assertEqual(symbol.unit, 2)
        self.assertTrue(symbol.in_bom)
        self.assertFalse(symbol.on_board)
        self.assertFalse(symbol.in_pos_files)
        self.assertTrue(symbol.dnp)
        self.assertTrue(symbol.exclude_from_sim)
        self.assertEqual(symbol.attribute("MPN").value, "ABC-1")
        self.assertEqual(
            [p.name for p in symbol.attributes],
            ["Reference", "Value", "Footprint", "MPN"],
        )

    def test_lib_symbols_definitions_are_not_placements(self) -> None:
        project = self.project_with(
            "board",
            """(kicad_sch (version 20250114)
  (lib_symbols
    (symbol "Device:R"
      (property "Reference" "R")
      (property "Value" "R")
      (symbol "Device:R_0_1" (pin passive line (at 0 0 0) (length 1)
        (name "~") (number "1")))
    )
  )
  (symbol (lib_id "Device:R") (at 5 5 0) (uuid p1)
    (property "Reference" "R1") (property "Value" "10k")
  )
)""",
        )
        symbols = project.schematic().files[0].symbols
        self.assertEqual([s.reference for s in symbols], ["R1"])
        self.assertEqual(symbols[0].lib_id, "Device:R")

    def test_power_and_dnp_are_included_without_bom_policy(self) -> None:
        project = self.project_with(
            "board",
            """(kicad_sch (version 20250114)
  (symbol (lib_id "power:GND") (at 0 0 0) (uuid g1)
    (in_bom no) (property "Reference" "#PWR01") (property "Value" "GND"))
  (symbol (lib_id "Device:R") (at 1 1 0) (uuid r1) (dnp yes)
    (property "Reference" "R2") (property "Value" "1k"))
)""",
        )
        refs = {s.reference for s in project.schematic().files[0].symbols}
        self.assertEqual(refs, {"#PWR01", "R2"})

    def test_ambiguous_and_missing_reference_lookup(self) -> None:
        project = self.project_with(
            "board",
            """(kicad_sch (version 20250114)
  (symbol (lib_id "Device:R") (at 0 0 0) (uuid a)
    (property "Reference" "R1") (property "Value" "1"))
  (symbol (lib_id "Device:R") (at 1 1 0) (uuid b)
    (property "Reference" "R1") (property "Value" "2"))
)""",
        )
        sch = project.schematic().files[0]
        self.assertEqual(len(sch.symbols), 2)
        with self.assertRaises(AmbiguousPlacedSymbolError):
            sch.symbol("R1")
        with self.assertRaises(KeyError):
            sch.symbol("R9")

    def test_invalid_schematic_fails_explicitly(self) -> None:
        project = self.project_with("board", "(not_a_schematic)")
        with self.assertRaises(InvalidSchematicError):
            project.schematic().files[0]
        bad = self.root / "board.kicad_sch"
        bad.write_bytes(b"\xff")
        with self.assertRaises(InvalidSchematicError):
            project.schematic().files[0]


class TitleBlockTests(SchematicCase):
    def test_scalar_fields_and_comments(self) -> None:
        project = self.project_with(
            "meta",
            """(kicad_sch (version 20250114)
  (title_block
    (title "MySch")
    (date "2026-05-09")
    (rev "A")
    (company "Acme")
    (comment 1 "designer")
    (comment 2 "")
    (comment 9 "released")
  )
)""",
        )
        block = project.schematic().files[0].title_block
        self.assertIsInstance(block, TitleBlock)
        self.assertEqual(block.title, "MySch")
        self.assertEqual(block.revision, "A")
        self.assertEqual(block.date, "2026-05-09")
        self.assertEqual(block.company, "Acme")
        self.assertEqual(dict(block.comments), {1: "designer", 2: "", 9: "released"})

    def test_missing_title_block_is_empty(self) -> None:
        project = self.project_with(
            "meta",
            "(kicad_sch (version 20250114))",
        )
        block = project.schematic().files[0].title_block
        self.assertEqual(block.title, "")
        self.assertEqual(dict(block.comments), {})


if __name__ == "__main__":
    unittest.main()
