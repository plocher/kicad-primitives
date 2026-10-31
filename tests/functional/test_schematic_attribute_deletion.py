"""PlacedSymbol.delete_attribute contracts, including jBOM alias normalization."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import Project
from kicad_primitives.schematics import (
    AmbiguousPlacedSymbolError,
    PlacedSymbol,
    UnsupportedSchematicOperationError,
)
from tests.functional.test_schematic_editing import SOURCE

MANUFACTURER = b'\n    (property "Manufacturer" "" (at 52 56 0))'

# Fake netlist backend: one stable singleton net unless the staged source
# contains "disconnect" (an electrical change).
FAKE_CLI = """#!/usr/bin/env python3
import pathlib, sys
root = pathlib.Path(sys.argv[-1])
source = ''.join(p.read_text() for p in root.parent.rglob('*.kicad_sch'))
net = 'CHANGED' if 'disconnect' in source else 'signal'
component = '(comp (ref R1) (value ignored) (libsource (lib Device) (part R)))'
node = '(node (ref R1) (pin 1) (pinfunction ~) (pintype passive))'
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(
    '(export (version E) (components '+component+')'
    '(nets (net (code 1) (name "'+net+'") '+node+')))')
"""

# jBOM annotate normalization map (jbom/services/annotation_service.py).
ALIASES = {
    "V": "Voltage",
    "A": "Current",
    "W": "Power",
    "Amperage": "Current",
    "Wattage": "Power",
}


def normalize_aliases(symbol: PlacedSymbol) -> list[str]:
    """Client-owned jBOM policy: set canonical, delete alias; report conflicts."""
    names = {a.name: a.value for a in symbol.attributes}
    conflicts: list[str] = []
    for alias, canonical in ALIASES.items():
        if alias not in names:
            continue
        current = names.get(canonical, "")
        if current and current != names[alias]:
            conflicts.append(alias)
            continue
        if not current:
            symbol.set_attribute(canonical, names[alias])
            names[canonical] = names[alias]
        symbol.delete_attribute(alias)
    return conflicts


class AttributeDeletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "board.kicad_pro").write_text("{}", encoding="utf-8")
        self.path = self.directory / "board.kicad_sch"
        self.path.write_bytes(SOURCE)

    def open(self, source: bytes = SOURCE) -> tuple[Project, PlacedSymbol]:
        self.path.write_bytes(source)
        project = Project.open(self.directory)
        return project, project.schematic().files[0].symbol("R1")

    def test_delete_removes_node_and_separator_only_without_writing(self) -> None:
        project, symbol = self.open()
        symbol.delete_attribute("Manufacturer")
        self.assertEqual(
            project.schematic().files[0].to_bytes(), SOURCE.replace(MANUFACTURER, b"")
        )
        self.assertNotIn("Manufacturer", [a.name for a in symbol.attributes])
        with self.assertRaises(KeyError):
            symbol.attribute("Manufacturer")
        self.assertIs(project.schematic().files[0].symbol("R1"), symbol)
        self.assertTrue(project.is_modified)
        self.assertEqual(self.path.read_bytes(), SOURCE)

    def test_inserted_then_deleted_attribute_restores_exact_bytes(self) -> None:
        project, symbol = self.open()
        symbol.set_attribute("MPN", "X")
        symbol.delete_attribute("MPN")
        self.assertEqual(project.schematic().files[0].to_bytes(), SOURCE)
        # ADR 0009: is_modified is a flag that edits set, not a byte comparison.
        self.assertTrue(project.is_modified)

    def test_compact_and_crlf_layouts_drop_only_their_separator(self) -> None:
        compact = SOURCE.replace(MANUFACTURER, b' (property "MPN" "X")')
        project, symbol = self.open(compact)
        symbol.delete_attribute("MPN")
        self.assertEqual(
            project.schematic().files[0].to_bytes(), SOURCE.replace(MANUFACTURER, b"")
        )
        crlf = SOURCE.replace(b"\n", b"\r\n")
        project, symbol = self.open(crlf)
        symbol.delete_attribute("Manufacturer")
        self.assertEqual(
            project.schematic().files[0].to_bytes(),
            crlf.replace(MANUFACTURER.replace(b"\n", b"\r\n"), b""),
        )

    def test_missing_ambiguous_mandatory_and_flags_fail_without_edits(self) -> None:
        repeated = SOURCE.replace(
            b'(property "Manufacturer" ""',
            b'(property "MPN" "a") (property "MPN" "b") (property "Manufacturer" ""',
        )
        cases: tuple[tuple[bytes, str, type[Exception]], ...] = (
            (SOURCE, "MPN", KeyError),
            (SOURCE, "manufacturer", KeyError),
            (repeated, "MPN", AmbiguousPlacedSymbolError),
            (SOURCE, "Reference", UnsupportedSchematicOperationError),
            (SOURCE, "value", UnsupportedSchematicOperationError),
            (SOURCE, "Footprint", UnsupportedSchematicOperationError),
            (SOURCE, "Datasheet", UnsupportedSchematicOperationError),
            (SOURCE, "Description", UnsupportedSchematicOperationError),
            (SOURCE, "dnp", UnsupportedSchematicOperationError),
            (SOURCE, "in_bom", UnsupportedSchematicOperationError),
            (
                SOURCE.replace(b"20260306", b"20250114"),
                "Manufacturer",
                UnsupportedSchematicOperationError,
            ),
            (
                SOURCE.replace(b'(uuid "uuid-r1")', b""),
                "Manufacturer",
                UnsupportedSchematicOperationError,
            ),
        )
        for source, name, error in cases:
            with self.subTest(name=name, error=error):
                project, symbol = self.open(source)
                with self.assertRaises(error):
                    symbol.delete_attribute(name)
                self.assertEqual(project.schematic().files[0].to_bytes(), source)
                self.assertEqual(self.path.read_bytes(), source)

    def test_invalid_names_raise_ordinary_errors(self) -> None:
        _project, symbol = self.open()
        with self.assertRaises(TypeError):
            symbol.delete_attribute(1)  # type: ignore[arg-type]
        for name in ("", "a\x00b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                symbol.delete_attribute(name)

    def test_jbom_alias_normalization_saves_with_connectivity_proof(self) -> None:
        source = SOURCE.replace(
            b'(property "Manufacturer" ""',
            b'(property "V" "5V" (at 52 58 0))\n'
            b'    (property "Wattage" "0.25W" (at 52 60 0))\n'
            b'    (property "A" "1A" (at 52 62 0))\n'
            b'    (property "Current" "2A" (at 52 64 0))\n'
            b'    (property "Manufacturer" ""',
        )
        project, symbol = self.open(source)
        conflicts = normalize_aliases(symbol)
        self.assertEqual(conflicts, ["A"])
        self.assertEqual(symbol.attribute("Voltage").value, "5V")
        self.assertEqual(symbol.attribute("Power").value, "0.25W")
        self.assertEqual(symbol.attribute("A").value, "1A")
        for alias in ("V", "Wattage"):
            with self.assertRaises(KeyError):
                symbol.attribute(alias)
        self.assertEqual(self.path.read_bytes(), source)

        pending = project.schematic().files[0].to_bytes()
        project.save()
        self.assertEqual(self.path.read_bytes(), pending)
        self.assertFalse(project.is_modified)

    def test_client_sees_an_electrical_deletion_and_save_still_writes(self) -> None:
        source = SOURCE.replace(MANUFACTURER, b'\n    (property "Net" "disconnect")')
        project, symbol = self.open(source)
        cli = self.directory / "fake-cli"
        cli.write_text(FAKE_CLI, encoding="utf-8")
        cli.chmod(0o755)
        before = project.netlist(kicad_cli=cli)
        symbol.delete_attribute("Net")
        after = project.netlist(kicad_cli=cli)
        self.assertNotEqual(
            [net.name for net in before.nets], [net.name for net in after.nets]
        )
        project.save()
        self.assertEqual(
            self.path.read_bytes(), project.schematic().files[0].to_bytes()
        )
        self.assertFalse(project.is_modified)


if __name__ == "__main__":
    unittest.main()
