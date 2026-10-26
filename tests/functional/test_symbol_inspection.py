"""Library behavior ported from FieldUnit-Subdivision at 4f9f140fcf1be1ee2e24773c71481c1346beb9c5.

Fixtures and assertions originate in tests/test_kicad_plant_graph.py:
SymbolLibraryReaderTests and tests/test_kicad_library_overview.py:OverviewTests.
Only library behavior is ported; HTML and Railroad policy remain in the donor.
"""

import unittest
from dataclasses import FrozenInstanceError
from inspect import signature
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives import schematics, symbols
from kicad_primitives.symbols import (
    AmbiguousAttributeError,
    InheritanceError,
    InvalidLibraryError,
    SymbolLibrary,
    UnsupportedOperationError,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class AttributeApiTests(unittest.TestCase):
    def test_canonical_public_names_have_no_property_aliases(self) -> None:
        for module, canonical, obsolete in (
            (symbols, "SymbolAttribute", "SymbolProperty"),
            (symbols, "AmbiguousAttributeError", "AmbiguousPropertyError"),
            (schematics, "PlacedAttribute", "PlacedProperty"),
        ):
            with self.subTest(name=canonical):
                self.assertIn(canonical, module.__all__)
                self.assertTrue(hasattr(module, canonical))
                self.assertNotIn(obsolete, module.__all__)
                self.assertFalse(hasattr(module, obsolete))
        for model in (symbols.Symbol, schematics.PlacedSymbol):
            with self.subTest(model=model.__name__):
                self.assertTrue(
                    hasattr(model, "attributes")
                    or "attributes" in model.__annotations__
                )
                self.assertFalse(hasattr(model, "properties"))
                self.assertTrue(callable(model.attribute))
                self.assertFalse(hasattr(model, "property"))
        for action in ("set", "add", "delete"):
            with self.subTest(action=action):
                method = getattr(symbols.Symbol, f"{action}_attribute")
                self.assertIn("name", signature(method).parameters)
                self.assertNotIn("property_name", signature(method).parameters)
                self.assertFalse(hasattr(SymbolLibrary, f"{action}_attribute"))
                self.assertFalse(hasattr(SymbolLibrary, f"{action}_property"))


class LibraryCase(unittest.TestCase):
    """Give each contract a disposable explicitly named library."""

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Example.kicad_sym"

    def library(self, contents: str) -> SymbolLibrary:
        """Open literal test content without changing its layout."""
        self.path.write_bytes(contents.encode("utf-8"))
        return SymbolLibrary.open(self.path)


class DonorInspectionTests(unittest.TestCase):
    def test_pin_contracts_from_unchanged_older_donor_fixture(self) -> None:
        library = SymbolLibrary.open(FIXTURES / "minimal_railroad.kicad_sym")
        self.assertEqual(library.version, 20231618)
        for name, reference, pins in (
            ("IRJ", "B", {("1", "A"), ("2", "B")}),
            ("IRJ-Signal", "B", {("1", "A"), ("2", "B"), ("3", "SIGNAL")}),
            ("Switch_Powered", "SW", {("1", "C"), ("2", "N"), ("3", "R")}),
        ):
            with self.subTest(symbol=name):
                symbol = library.symbol(name)
                self.assertEqual(symbol.attribute("Reference").value, reference)
                self.assertEqual(
                    {(p.number, p.name) for b in symbol.bodies for p in b.pins},
                    pins,
                )
        with self.assertRaises(UnsupportedOperationError):
            library.symbol("IRJ").set_attribute("Reference", "X")
        with self.assertRaises(UnsupportedOperationError):
            library.save()

    def test_overview_fields_units_and_escaping(self) -> None:
        library = SymbolLibrary.open(FIXTURES / "overview.kicad_sym")
        self.assertEqual([s.name for s in library.symbols], ["Gadget", "Marker"])
        gadget = library.symbol("Gadget")
        for key, expected in (
            ("Role", "DEVICE"),
            ("Pin.OCC", "binary out"),
            ("hold_ms", "1500"),
            ("Description", 'A <b>gadget</b> & its "friend"'),
        ):
            with self.subTest(attribute=key):
                self.assertEqual(gadget.attribute(key).value, expected)
        self.assertFalse(gadget.attribute("Value").autoplace)
        self.assertEqual(
            [
                (b.unit, b.body_style, tuple(p.name for p in b.pins))
                for b in gadget.bodies
            ],
            [(0, 1, ()), (1, 1, ("~{OCC}",)), (2, 1, ("EN",))],
        )
        self.assertEqual(len(gadget.bodies[0].rectangles), 1)
        self.assertEqual(gadget.bodies[0].rectangles[0].start_x, -2.54)
        self.assertEqual(gadget.bodies[1].pins[0].x, 5.08)
        self.assertEqual(gadget.bodies[1].pins[0].rotation, 180)
        self.assertEqual(library.symbol("Marker").attribute("Kind").value, "END_CTC")
        self.assertEqual(
            library.to_bytes(), (FIXTURES / "overview.kicad_sym").read_bytes()
        )


class StructuralInspectionTests(LibraryCase):
    def test_private_modifier_is_not_an_attribute_name(self) -> None:
        library = self.library("""(kicad_symbol_lib (version 20251024)
          (symbol "Crystal"
            (property private "KLC_S3.3" "reason one" (hide yes))
            (property private "KLC_S4.1" "reason two")
            (property "private" "a genuinely named property")
          ))""")
        props = library.symbol("Crystal").attributes
        self.assertEqual([p.name for p in props], ["KLC_S3.3", "KLC_S4.1", "private"])
        self.assertEqual([p.is_private for p in props], [True, True, False])
        self.assertTrue(props[0].hidden)
        self.assertEqual(props[1].value, "reason two")
        with self.assertRaises(FrozenInstanceError):
            props[0].value = "mutated"  # type: ignore[misc]

    def test_repeated_attributes_remain_visible_but_lookup_is_ambiguous(self) -> None:
        library = self.library("""(kicad_symbol_lib (version 20251024)
          (symbol "Repeated" (property "Note" "first") (property "Note" "second")))""")
        self.assertEqual(
            [p.value for p in library.symbol("Repeated").attributes],
            ["first", "second"],
        )
        with self.assertRaises(AmbiguousAttributeError):
            library.symbol("Repeated").attribute("Note")
        with self.assertRaises(AmbiguousAttributeError):
            library.resolve("Repeated")

    def test_top_level_numeric_suffix_and_body_style_identity(self) -> None:
        library = self.library("""(kicad_symbol_lib (version 20251024)
          (symbol "Part_1_2"
            (property "ki_locked" "")
            (symbol "Part_1_2_0_0"
              (pin passive line (at 0 1 90) (length 2) (hide yes)
                (name "COM") (number "1")))
            (symbol "Part_1_2_1_1"
              (pin input inverted (at 2 3 180) (length 1)
                (name "A") (number "2")))
            (symbol "Part_1_2_1_2"
              (pin input line (at 3 4 180) (length 1)
                (name "A") (number "2")))))""")
        symbol = library.symbol("Part_1_2")
        self.assertTrue(symbol.units_locked)
        self.assertEqual(
            [(b.unit, b.body_style) for b in symbol.bodies], [(0, 0), (1, 1), (1, 2)]
        )
        self.assertTrue(symbol.bodies[0].pins[0].hidden)
        self.assertEqual(symbol.bodies[1].pins[0].shape, "inverted")
        self.assertEqual(symbol.bodies[1].pins[0].electrical_type, "input")

    def test_forward_chained_inheritance_and_empty_field_rules(self) -> None:
        library = self.library("""(kicad_symbol_lib (version 20251024)
          (symbol "Child" (extends "Middle")
            (property "Description" "") (property "Note" ""))
          (symbol "Root"
            (property "Reference" "U") (property "Description" "base")
            (property "Note" "root") (property "ki_keywords" "base keywords")
            (symbol "Root_1_1"
              (pin input line (at 0 0 0) (length 1) (name "IN") (number "1"))))
          (symbol "Middle" (extends "Root")
            (property "Reference" "IC") (property "Note" "middle")
            (property "ki_keywords" "")))""")
        declared = library.symbol("Child")
        resolved = library.resolve("Child")
        self.assertFalse(declared.resolved)
        self.assertTrue(resolved.resolved)
        self.assertEqual(declared.attribute("Description").value, "")
        for key, value, origin in (
            ("Reference", "IC", "Middle"),
            ("Description", "base", "Root"),
            ("Note", "", "Child"),
            ("ki_keywords", "base keywords", "Root"),
        ):
            with self.subTest(attribute=key):
                prop = resolved.attribute(key)
                self.assertEqual((prop.value, prop.origin_symbol), (value, origin))
        self.assertEqual(resolved.bodies[0].origin_symbol, "Root")
        self.assertEqual(resolved.bodies[0].pins[0].name, "IN")
        self.assertEqual(declared.bodies, ())

    def test_bad_inheritance_does_not_block_declared_inspection(self) -> None:
        for nodes in (
            '(symbol "A" (extends "Missing") (property "Note" "kept"))',
            '(symbol "A" (extends "B")) (symbol "B" (extends "A"))',
            '(symbol "A" (extends "A"))',
        ):
            with self.subTest(nodes=nodes):
                library = self.library(f"(kicad_symbol_lib (version 20251024) {nodes})")
                self.assertEqual(library.symbol("A").name, "A")
                with self.assertRaises(InheritanceError):
                    library.resolve("A")

    def test_invalid_input_fails_instead_of_skipping_required_content(self) -> None:
        for content in (
            ")",
            "(kicad_symbol_lib",
            "(wrong (version 20251024))",
            "(kicad_symbol_lib)",
            "(kicad_symbol_lib (version nope))",
            "(kicad_symbol_lib (version 20251024)) (extra)",
            "(kicad_symbol_lib (version 20251024) (version 20251024))",
            '(kicad_symbol_lib (version 20251024) (symbol "Bad" (property "Missing")))',
            '(kicad_symbol_lib (version 20251024) (symbol "Bad" (symbol "Other_1_1")))',
            '(kicad_symbol_lib (version 20251024) (symbol "Bad" (symbol "Bad_1_1" (pin input line (name "A") (number "1")))))',
        ):
            with self.subTest(content=content), self.assertRaises(InvalidLibraryError):
                self.library(content)
        self.path.write_bytes(b"\xff")
        with self.assertRaises(InvalidLibraryError):
            SymbolLibrary.open(self.path)

    def test_future_format_rejected_and_missing_symbol_is_explicit(self) -> None:
        with self.assertRaises(UnsupportedOperationError):
            self.library("(kicad_symbol_lib (version 20990101))")
        library = self.library("(kicad_symbol_lib (version 20251024))")
        with self.assertRaises(KeyError):
            library.symbol("Missing")


if __name__ == "__main__":
    unittest.main()
