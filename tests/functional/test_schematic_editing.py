"""Object-edit contracts lifted from jBOM test_annotate_repairs, not CSV policy."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import Project
from kicad_primitives.schematics import (
    AmbiguousPlacedSymbolError,
    UnsupportedSchematicOperationError,
)

SOURCE = b"""(kicad_sch (version 20260306) (generator eeschema)
  (symbol (lib_id "Device:R") (at 50 50 0) (uuid "uuid-r1")
    (property "Reference" "R1" (at 52 48 0))
    (property "Value" "10K" (at 52 52 0) (effects (font (size 1.27 1.27))))
    (property "Manufacturer" "" (at 52 56 0))
  )
)
"""


class SchematicEditingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "board.kicad_pro").write_text("{}", encoding="utf-8")
        self.path = self.directory / "board.kicad_sch"
        self.path.write_bytes(SOURCE)
        self.project = Project.open(self.directory)
        self.schematic = self.project.schematic().files[0]

    def test_update_preserves_presentation_and_old_handles_observe_edits(self) -> None:
        symbol = self.schematic.symbol("R1")
        symbol.set_attribute("Value", "33K")
        symbol.set_attribute("Manufacturer", "Yageo")
        expected = SOURCE.replace(b'"10K"', b'"33K"').replace(
            b'"Manufacturer" ""', b'"Manufacturer" "Yageo"'
        )
        self.assertEqual(self.schematic.to_bytes(), expected)
        self.assertEqual(symbol.value, "33K")
        self.assertEqual(symbol.attribute("Manufacturer").value, "Yageo")
        self.assertIs(self.schematic.symbol("R1"), symbol)
        self.assertIs(self.project.schematic().files[0], self.schematic)
        self.assertIs(self.project.schematic().files[0], self.schematic)
        self.assertTrue(self.schematic.is_modified)
        self.assertTrue(self.project.is_modified)
        self.assertEqual(self.path.read_bytes(), SOURCE)

    def test_missing_attribute_is_created_hidden_and_reparsed_for_next_edit(
        self,
    ) -> None:
        symbol = self.schematic.symbol("R1")
        symbol.set_attribute("MPN", 'résistor "A"\\B')
        first = self.schematic.to_bytes()
        self.assertEqual(symbol.attribute("MPN").value, 'résistor "A"\\B')
        self.assertIn(b"(at 50 50 0)", first)
        self.assertIn(b"(hide yes)", first)
        inserted = """
    (property "MPN" "résistor \\"A\\"\\\\B"
      (at 50 50 0)
      (effects (font (size 1.27 1.27)) (hide yes))
    )""".encode()
        self.assertEqual(first.replace(inserted, b""), SOURCE)
        symbol.set_attribute("MPN", "")
        self.assertEqual(symbol.attribute("MPN").value, "")
        self.assertEqual(self.path.read_bytes(), SOURCE)

    def test_equal_value_is_exact_noop_and_reverting_clears_modified(self) -> None:
        symbol = self.schematic.symbol("R1")
        symbol.set_attribute("Value", "10K")
        self.assertEqual(self.schematic.to_bytes(), SOURCE)
        self.assertFalse(self.schematic.is_modified)
        symbol.set_attribute("Value", "20K")
        symbol.set_attribute("Value", "10K")
        self.assertFalse(self.project.is_modified)

    def test_ambiguous_attribute_is_rejected_even_when_equal(self) -> None:
        self.path.write_bytes(
            SOURCE.replace(
                b'(property "Manufacturer" ""',
                b'(property "Value" "10K") (property "Manufacturer" ""',
            )
        )
        with self.assertRaises(AmbiguousPlacedSymbolError):
            Project.open(self.directory).schematic().files[0]

    def test_mandatory_duplicates_fail_intake_without_first_wins_or_skipping(
        self,
    ) -> None:
        for name, first, second in (
            ("Value", "10K", "20K"),
            ("Reference", "", "R2"),
            ("Description", "first", "second"),
        ):
            with self.subTest(name=name):
                source = SOURCE.replace(
                    b'(property "Manufacturer" ""',
                    f'(property "{name}" "{first}") (property "{name.lower()}" "{second}") '
                    '(property "Manufacturer" ""'.encode(),
                )
                self.path.write_bytes(source)
                with self.assertRaises(AmbiguousPlacedSymbolError):
                    Project.open(self.directory).schematic().files[0]
                self.assertEqual(self.path.read_bytes(), source)

    def test_custom_repeated_attributes_remain_inspectable_without_first_wins(
        self,
    ) -> None:
        source = SOURCE.replace(
            b'(property "Manufacturer" ""',
            b'(property "MPN" "first") (property "MPN" "second") '
            b'(property "Manufacturer" ""',
        )
        self.path.write_bytes(source)
        symbol = Project.open(self.directory).schematic().files[0].symbol("R1")
        self.assertEqual(
            [p.value for p in symbol.attributes if p.name == "MPN"], ["first", "second"]
        )
        with self.assertRaises(AmbiguousPlacedSymbolError):
            symbol.attribute("MPN")
        symbol.set_attribute("Value", "22K")
        self.assertEqual(symbol.value, "22K")

    def test_unsafe_reference_power_flags_and_missing_uuid_fail_without_edits(
        self,
    ) -> None:
        for source, name, value in (
            (SOURCE, "reference", "R2"),
            (SOURCE, "dnp", "yes"),
            (SOURCE.replace(b"Device:R", b"power:GND"), "Value", "AGND"),
            (SOURCE.replace(b'(uuid "uuid-r1")', b""), "Value", "22K"),
            (SOURCE.replace(b"20260306", b"20250114"), "Value", "22K"),
            (SOURCE.replace(b"20260306", b"20990101"), "Value", "22K"),
        ):
            with self.subTest(name=name, source=source):
                self.path.write_bytes(source)
                schematic = Project.open(self.directory).schematic().files[0]
                with self.assertRaises(UnsupportedSchematicOperationError):
                    schematic.symbol("R1").set_attribute(name, value)
                self.assertEqual(schematic.to_bytes(), source)
                self.assertEqual(self.path.read_bytes(), source)

    def test_crlf_unicode_escapes_and_opaque_content_survive_successive_edits(
        self,
    ) -> None:
        source = SOURCE.replace(b"\n", b"\r\n").replace(
            b"(generator eeschema)",
            r'(generator eeschema) (opaque "café \"x\"")'.encode(),
        )
        self.path.write_bytes(source)
        schematic = Project.open(self.directory).schematic().files[0]
        symbol = schematic.symbol("R1")
        symbol.set_attribute("Value", 'résistor "A"\\B')
        symbol.set_attribute("New", "first")
        symbol.set_attribute("New", "second\nline")
        preview = schematic.to_bytes()
        self.assertEqual(preview.count(b"\n"), preview.count(b"\r\n"))
        self.assertIn(r'(opaque "café \"x\"")'.encode(), preview)
        self.assertEqual(symbol.attribute("New").value, "second\nline")
        self.assertEqual(self.path.read_bytes(), source)
