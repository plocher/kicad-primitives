"""Live rectangle and body-text handles: minimal set/delete (#66)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.symbols import (
    LibraryLifecycleError,
    StaleSymbolError,
    SymbolLibrary,
    SymbolRectangle,
    SymbolText,
    UnsupportedOperationError,
)

RECT_A = (
    "      (rectangle\n"
    "        (start -2.540 2.54)\n"
    "        (end 2.54 -2.54)\n"
    "        (stroke (width 0.254) (type default))\n"
    "        (fill (type background))\n"
    "      )\n"
)
RECT_B = (
    "      (rectangle (start 0 0) (end 1 1) (stroke (width 0)) (fill (type none)))\n"
)
TEXT_A = (
    '      (text "LABEL"\n'
    "        (at 0 3.81 0)\n"
    "        (effects (font (size 1.27 1.27)) (justify left))\n"
    "      )\n"
)
TEXT_B = '      (text "B" (at 1 1 900) (effects (font (size 1 1))))\n'
SOURCE = (
    "(kicad_symbol_lib\n"
    "  (version 20251024)\n"
    '  (symbol "Part"\n'
    '    (property "Reference" "U" (at 0 0 0))\n'
    '    (symbol "Part_0_1"\n' + RECT_A + RECT_B + TEXT_A + TEXT_B + "    )\n"
    '    (symbol "Part_1_1"\n'
    '      (pin passive line (at 0 0 0) (length 1) (name "A") (number "1"))\n'
    "    )\n"
    "  )\n"
    ")\n"
).encode()


class GraphicsAdjustTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "Parts.kicad_sym"
        self.path.write_bytes(SOURCE)
        self.library = SymbolLibrary.open(self.path)
        self.body = self.library.symbol("Part").body(0, 1)

    def test_handles_are_live_and_stable_across_unrelated_edits(self) -> None:
        rect, other = self.body.rectangles
        text = self.body.texts[0]
        self.assertIsInstance(rect, SymbolRectangle)
        self.assertIsInstance(text, SymbolText)
        self.assertEqual((rect.start_x, rect.start_y), (-2.54, 2.54))
        self.assertEqual(
            (text.text, text.x, text.y, text.rotation), ("LABEL", 0, 3.81, 0)
        )
        self.library.symbol("Part").body(1, 1).add_pin("2", "B", "input", x=1, y=1)
        self.library.symbol("Part").set_attribute("Value", "X")
        added = self.body.add_rectangle(start=(5, 5), end=(6, 6))
        self.assertEqual(self.body.rectangles, (rect, other, added))
        self.library.rename_symbol("Part", "Renamed")
        self.assertIs(self.library.symbol("Renamed").body(0, 1).rectangles[0], rect)
        self.assertEqual(rect.end_x, 2.54)

    def test_rectangle_set_replaces_only_target_atoms(self) -> None:
        rect = self.body.rectangles[0]
        rect.set(start=(-5.08, 2.54), end=(2.54, -5.08))
        expected = SOURCE.replace(
            b"(start -2.540 2.54)", b"(start -5.08 2.54)"
        ).replace(
            b"(end 2.54 -2.54)\n        (stroke", b"(end 2.54 -5.08)\n        (stroke"
        )
        self.assertEqual(self.library.to_bytes(), expected)
        self.assertEqual((rect.start_x, rect.end_y), (-5.08, -5.08))
        self.assertTrue(self.library.is_modified)
        self.assertEqual(self.path.read_bytes(), SOURCE)

    def test_equal_values_are_lexical_noops(self) -> None:
        rect = self.body.rectangles[0]
        rect.set(start=(-2.54, 2.54))  # source spells -2.540
        rect.set(end=(2.54, -2.54))
        self.body.texts[0].set(text="LABEL", x=0.0, y=3.81, rotation=0)
        self.assertEqual(self.library.to_bytes(), SOURCE)
        self.assertFalse(self.library.is_modified)

    def test_text_set_preserves_effects_and_other_text(self) -> None:
        text = self.body.texts[0]
        text.set(text='New "label"', rotation=90)
        expected = SOURCE.replace(b'(text "LABEL"', b'(text "New \\"label\\""').replace(
            b"(at 0 3.81 0)", b"(at 0 3.81 90)"
        )
        self.assertEqual(self.library.to_bytes(), expected)
        self.assertEqual((text.text, text.rotation), ('New "label"', 90))
        text.set(x=1.5, y=-2)
        self.assertIn(b"(at 1.5 -2 90)", self.library.to_bytes())
        self.assertIn(TEXT_B.encode(), self.library.to_bytes())

    def test_delete_removes_node_and_separator_and_shifts_later_handles(self) -> None:
        first, second = self.body.rectangles
        first.delete()
        self.assertEqual(self.library.to_bytes(), SOURCE.replace(RECT_A.encode(), b""))
        self.assertEqual(self.body.rectangles, (second,))
        with self.assertRaises(StaleSymbolError):
            first.set(start=(0, 0))
        with self.assertRaises(StaleSymbolError):
            _ = first.start_x
        second.set(end=(2, 2))
        self.assertIn(b"(end 2 2)", self.library.to_bytes())
        text_a, text_b = self.body.texts
        text_b.delete()
        self.assertEqual(self.body.texts, (text_a,))
        self.assertNotIn(b'(text "B"', self.library.to_bytes())
        self.assertIn(TEXT_A.encode(), self.library.to_bytes())
        self.assertEqual(self.path.read_bytes(), SOURCE)

    def test_add_then_delete_restores_exact_bytes(self) -> None:
        added = self.body.add_text("TMP", x=0, y=0)
        added.delete()
        self.assertEqual(self.library.to_bytes(), SOURCE)

    def test_invalid_requests_fail_without_edits(self) -> None:
        rect, text = self.body.rectangles[0], self.body.texts[0]
        for action, error in (
            (lambda: rect.set(), ValueError),
            (lambda: text.set(), ValueError),
            (lambda: rect.set(start=(float("nan"), 0)), ValueError),
            (lambda: rect.set(start=[0, 0]), TypeError),  # type: ignore[arg-type]
            (lambda: text.set(text="a\x00b"), ValueError),
            (lambda: text.set(x="1"), TypeError),  # type: ignore[arg-type]
        ):
            with self.subTest(error=error), self.assertRaises(error):
                action()
        self.assertEqual(self.library.to_bytes(), SOURCE)

    def test_readonly_format_and_lifecycle_invalidate(self) -> None:
        old = SOURCE.replace(b"20251024", b"20231120")
        self.path.write_bytes(old)
        library = SymbolLibrary.open(self.path)
        rect = library.symbol("Part").body(0, 1).rectangles[0]
        with self.assertRaises(UnsupportedOperationError):
            rect.set(start=(0, 0))
        with self.assertRaises(UnsupportedOperationError):
            rect.delete()
        self.assertEqual(library.to_bytes(), old)

        rect, text = self.body.rectangles[0], self.body.texts[0]
        self.library.delete_symbol("Part")
        for action in (lambda: rect.set(start=(0, 0)), text.delete):
            with self.assertRaises(StaleSymbolError):
                action()

    def test_discard_invalidates_graphic_handles(self) -> None:
        rect = self.body.rectangles[0]
        self.library.discard()
        with self.assertRaises(StaleSymbolError):
            rect.set(start=(0, 0))
        with self.assertRaises(LibraryLifecycleError):
            self.library.to_bytes()

    def test_save_persists_graphics_edits_explicitly(self) -> None:
        self.body.rectangles[1].delete()
        self.body.texts[0].set(text="SAVED")
        pending = self.library.to_bytes()
        self.assertEqual(self.path.read_bytes(), SOURCE)
        self.library.save()
        self.assertEqual(self.path.read_bytes(), pending)
        self.assertEqual(
            SymbolLibrary.open(self.path).symbol("Part").body(0, 1).texts[0].text,
            "SAVED",
        )


if __name__ == "__main__":
    unittest.main()
