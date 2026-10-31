"""Schematic geometry and electrical structure read (#35).

Enough for FieldUnit-style ingest: wires, junctions, labels, no-connects,
sheet hierarchy edges, with positions. Read-only; no geometry edit.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import Project


class GeometryCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="kp_geom_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative: str, contents: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def project(self, body: str, name: str = "board") -> Project:
        self.write(f"{name}.kicad_pro", json.dumps({"meta": {"version": 1}}))
        self.write(f"{name}.kicad_sch", body)
        return Project.open(self.root)


class StructureTests(GeometryCase):
    def test_wires_junctions_labels_no_connects_and_sheets(self) -> None:
        project = self.project(
            """(kicad_sch (version 20250114)
  (title_block (title "G"))
  (wire (pts (xy 10 20) (xy 10 30) (xy 40 30))
    (uuid "w1"))
  (junction (at 10 30) (uuid "j1"))
  (label "NET_A" (at 12 20 0) (uuid "l1"))
  (global_label "+5V" (shape input) (at 50 50 180) (uuid "g1"))
  (hierarchical_label "SCL" (shape bidirectional) (at 60 60 0) (uuid "h1"))
  (no_connect (at 70 70) (uuid "n1"))
  (sheet (at 100 100) (size 30 20) (uuid "s1")
    (property "Sheetname" "Child")
    (property "Sheetfile" "child.kicad_sch"))
  (symbol (lib_id "Device:R") (at 5 5 0) (uuid "r1")
    (property "Reference" "R1") (property "Value" "1k"))
)"""
        )
        self.write("child.kicad_sch", "(kicad_sch (version 20250114))")
        sch = project.schematic().files[0]

        self.assertEqual(len(sch.wires), 1)
        wire = sch.wires[0]
        self.assertEqual(wire.points, ((10.0, 20.0), (10.0, 30.0), (40.0, 30.0)))
        self.assertEqual(wire.uuid, "w1")

        self.assertEqual(len(sch.junctions), 1)
        self.assertEqual((sch.junctions[0].x, sch.junctions[0].y), (10.0, 30.0))
        self.assertEqual(sch.junctions[0].uuid, "j1")

        self.assertEqual(len(sch.labels), 1)
        self.assertEqual(sch.labels[0].text, "NET_A")
        self.assertEqual(sch.labels[0].kind, "label")
        self.assertEqual(
            (sch.labels[0].x, sch.labels[0].y, sch.labels[0].rotation),
            (12.0, 20.0, 0.0),
        )

        self.assertEqual(len(sch.global_labels), 1)
        self.assertEqual(sch.global_labels[0].text, "+5V")
        self.assertEqual(sch.global_labels[0].shape, "input")
        self.assertEqual(sch.global_labels[0].rotation, 180.0)

        self.assertEqual(len(sch.hierarchical_labels), 1)
        self.assertEqual(sch.hierarchical_labels[0].text, "SCL")
        self.assertEqual(sch.hierarchical_labels[0].shape, "bidirectional")

        self.assertEqual(len(sch.no_connects), 1)
        self.assertEqual((sch.no_connects[0].x, sch.no_connects[0].y), (70.0, 70.0))

        self.assertEqual(len(sch.sheet_symbols), 1)
        sheet = sch.sheet_symbols[0]
        self.assertEqual(sheet.name, "Child")
        self.assertEqual(sheet.filename, "child.kicad_sch")
        self.assertEqual(
            (sheet.x, sheet.y, sheet.width, sheet.height), (100.0, 100.0, 30.0, 20.0)
        )
        self.assertEqual(sheet.uuid, "s1")

        # Placed symbols still present (geometry does not drop #28 surface).
        self.assertEqual([s.reference for s in sch.symbols], ["R1"])

    def test_empty_geometry_is_empty_tuples(self) -> None:
        sch = (
            self.project(
                """(kicad_sch (version 20250114)
  (symbol (lib_id "Device:R") (at 0 0 0) (uuid u)
    (property "Reference" "R1") (property "Value" "1"))
)"""
            )
            .schematic()
            .files[0]
        )
        self.assertEqual(sch.wires, ())
        self.assertEqual(sch.junctions, ())
        self.assertEqual(sch.labels, ())
        self.assertEqual(sch.global_labels, ())
        self.assertEqual(sch.hierarchical_labels, ())
        self.assertEqual(sch.no_connects, ())
        self.assertEqual(sch.sheet_symbols, ())

    def test_sheet_file_resolves_relative_to_parent_via_project(self) -> None:
        self.write("main.kicad_pro", json.dumps({"meta": {"version": 1}}))
        self.write(
            "main.kicad_sch",
            """(kicad_sch (version 20250114)
  (sheet (at 0 0) (size 10 10) (uuid s)
    (property "Sheetname" "Nested")
    (property "Sheetfile" "blocks/child.kicad_sch"))
)""",
        )
        self.write(
            "blocks/child.kicad_sch",
            """(kicad_sch (version 20250114)
  (wire (pts (xy 1 1) (xy 2 2)) (uuid w))
)""",
        )
        project = Project.open(self.root)
        root = project.schematic().files[0]
        self.assertEqual(root.sheet_symbols[0].filename, "blocks/child.kicad_sch")
        child = project.schematic().file(self.root / "blocks/child.kicad_sch")
        self.assertEqual(len(child.wires), 1)
        self.assertEqual(child.wires[0].points, ((1.0, 1.0), (2.0, 2.0)))


if __name__ == "__main__":
    unittest.main()
