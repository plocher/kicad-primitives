"""Footprint-library read model: two levels, cached summaries, immediate directory ops.

Fixture provenance: ``tests/fixtures/footprints/Fixture.pretty`` holds
hand-written KiCad 10 (format 20260206) files shaped like the installed
library files, plus a legacy-format, a future-format, and a broken file.
KiCad 10.0.1 ``kicad-cli fp export svg`` renders every valid fixture.

Lifted from EagleLib2KiCad (behavior only): footprint identity is the file
stem, listing is sorted by stem, and ``pad_count`` is the raw pad node count.
"""

import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.footprints import (
    Footprint,
    FootprintLibrary,
    FootprintLifecycleError,
    FootprintSummary,
    InvalidFootprintError,
    Pad,
    PadDrill,
    UnsupportedOperationError,
    matches_filters,
)
from kicad_primitives.tables import LibraryTables

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "footprints" / "Fixture.pretty"
)
VALID = (
    "Connector_1x02_MP",
    "Ganged_A1_B12",
    "Legacy",
    "Mismatch",
    "MountingHole_3.2mm_M3",
    "R_0603",
)


class FootprintCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "Fixture.pretty"
        shutil.copytree(FIXTURE, self.path)
        self.library = FootprintLibrary.open(self.path)
        self.addCleanup(self.library.discard)

    def read(self, name: str) -> bytes:
        return (self.path / f"{name}.kicad_mod").read_bytes()


class SummaryTests(FootprintCase):
    def test_summaries_are_sorted_stems_and_failures_are_reported_separately(
        self,
    ) -> None:
        self.assertEqual(tuple(s.name for s in self.library.summaries), VALID)
        self.assertEqual(
            [(f.name, f.error.split(":")[0]) for f in self.library.failures],
            [
                ("Broken", "InvalidFootprintError"),
                ("Future", "UnsupportedOperationError"),
            ],
        )
        self.assertEqual(self.library.name, "Fixture")
        self.assertEqual(self.library.path, self.path)
        self.assertEqual(self.library.on_close, "save")
        for summary in self.library.summaries:
            self.assertIsInstance(summary, FootprintSummary)
            self.assertEqual(summary.path, self.path / f"{summary.name}.kicad_mod")

    def test_summary_fields_follow_the_file(self) -> None:
        r = self.library.summary("R_0603")
        self.assertEqual(r.declared_name, "R_0603")
        self.assertEqual(r.version, 20260206)
        self.assertEqual(
            r.description, 'Resistor SMD 0603 (1608 Metric), "square" ends'
        )
        self.assertEqual(r.tags, "resistor 0603")
        self.assertEqual(r.footprint_type, "smd")
        self.assertEqual(r.flags, frozenset())
        self.assertEqual(
            [(a.name, a.value, a.layer, a.hidden) for a in r.attributes],
            [
                ("Reference", "REF**", "F.SilkS", False),
                ("Value", "R_0603", "F.Fab", False),
                ("KiLib_Generator", "SMD_2terminal_chip_molded", "F.SilkS", True),
            ],
        )
        self.assertEqual(r.attribute("value").value, "R_0603")
        self.assertEqual(r.attribute("KiLib_Generator").hidden, True)
        with self.assertRaises(KeyError):
            r.attribute("kilib_generator")
        hole = self.library.summary("MountingHole_3.2mm_M3")
        self.assertEqual(hole.footprint_type, "unspecified")
        self.assertEqual(
            hole.flags, frozenset({"exclude_from_pos_files", "exclude_from_bom"})
        )
        self.assertEqual(self.library.summary("Legacy").version, 20240108)

    def test_mismatched_internal_name_loads_under_the_file_stem(self) -> None:
        summary = self.library.summary("Mismatch")
        self.assertEqual(summary.name, "Mismatch")
        self.assertEqual(summary.declared_name, "InternalName")
        footprint = self.library.footprint("Mismatch")
        self.assertEqual(footprint.name, "Mismatch")
        self.assertEqual(footprint.declared_name, "InternalName")

    def test_pad_counts_follow_kicad_10_0_1(self) -> None:
        counts = {
            s.name: (s.pad_count, s.unique_pad_count) for s in self.library.summaries
        }
        self.assertEqual(counts["R_0603"], (2, 2))
        # NPTH is a pad node but never a numbered pad.
        self.assertEqual(counts["MountingHole_3.2mm_M3"], (1, 0))
        # 1, 2, MP, MP, paste-only "3", NPTH: unique copper numbers are 1, 2, MP.
        self.assertEqual(counts["Connector_1x02_MP"], (6, 3))
        # A ganged name is one number in 10.0.1 (GetUniquePadCount).
        self.assertEqual(counts["Ganged_A1_B12"], (3, 2))

    def test_pads_are_immutable_values(self) -> None:
        pads = self.library.footprint("Connector_1x02_MP").pads
        self.assertEqual(
            pads[0],
            Pad(
                number="1",
                pad_type="thru_hole",
                shape="roundrect",
                x=0.0,
                y=0.0,
                rotation=0.0,
                width=1.2,
                height=1.75,
                layers=("*.Cu", "*.Mask"),
                drill=PadDrill(0.75, 0.75, oval=False),
            ),
        )
        self.assertEqual(pads[1].rotation, 90.0)
        self.assertEqual(pads[1].drill, PadDrill(0.75, 1.1, oval=True))
        self.assertEqual(pads[2].number, "MP")
        self.assertIsNone(pads[2].drill)
        self.assertEqual(pads[4].layers, ("F.Paste",))
        self.assertFalse(pads[4].on_copper)
        self.assertEqual(pads[5].number, "")
        self.assertEqual(pads[5].pad_type, "np_thru_hole")
        with self.assertRaises(AttributeError):
            pads[0].number = "9"  # type: ignore[misc]

    def test_filters_follow_ki_fp_filters_rules(self) -> None:
        r = self.library.summary("R_0603")
        self.assertTrue(r.matches_filters([]))
        self.assertTrue(r.matches_filters(["r_*"]))
        self.assertTrue(r.matches_filters(["R_????"]))
        self.assertFalse(r.matches_filters(["R_???"]))
        self.assertFalse(r.matches_filters(["0603"]))  # anchored, not substring
        self.assertTrue(r.matches_filters(["X*", "*0603"]))
        self.assertTrue(r.matches_filters(["Fixture:R_*"], nickname="fixture"))
        self.assertFalse(r.matches_filters(["Other:R_*"], nickname="Fixture"))
        self.assertFalse(r.matches_filters(["Fixture:R_*"]))
        self.assertTrue(matches_filters("R_0603", ["r_0603"]))
        self.assertFalse(matches_filters("R.0603", ["R?0603x"]))
        self.assertTrue(self.library.footprint("R_0603").matches_filters(["R_*"]))


class LiveFootprintTests(FootprintCase):
    def test_footprint_is_the_same_object_while_open(self) -> None:
        first = self.library.footprint("R_0603")
        self.assertIs(self.library.footprint("R_0603"), first)
        self.assertIs(first.library, self.library)
        self.assertEqual(self.library.footprints, (first,))
        self.assertFalse(first.is_modified)
        self.assertFalse(self.library.is_modified)
        self.assertEqual(first.to_bytes(), self.read("R_0603"))
        self.assertEqual(first.summary, self.library.summary("R_0603"))
        first.discard()
        self.assertTrue(first.is_closed)
        self.assertEqual(self.library.footprints, ())
        second = self.library.footprint("R_0603")
        self.assertIsNot(second, first)
        with self.assertRaises(FootprintLifecycleError):
            first.pads  # noqa: B018
        with self.assertRaises(KeyError):
            self.library.footprint("Missing")
        with self.assertRaises(InvalidFootprintError):
            self.library.footprint("Broken")
        with self.assertRaises(UnsupportedOperationError):
            self.library.footprint("Future")
        with self.assertRaises(ValueError):
            self.library.footprint("../R_0603")

    def test_open_then_close_writes_nothing(self) -> None:
        before = {
            p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.path.iterdir()
        }
        library = FootprintLibrary.open(self.path)
        self.assertIs(library, self.library)
        library.footprint("R_0603")
        library.footprint("Legacy")
        library.close()
        library.close()
        self.assertTrue(library.is_closed)
        after = {
            p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.path.iterdir()
        }
        self.assertEqual(after, before)
        with self.assertRaises(FootprintLifecycleError):
            library.summaries  # noqa: B018


class RefreshTests(FootprintCase):
    def test_refresh_sees_external_add_change_rename_and_delete(self) -> None:
        live = self.library.footprint("R_0603")
        original = self.read("R_0603")
        (self.path / "Added.kicad_mod").write_bytes(
            original.replace(b'"R_0603"', b'"Added"')
        )
        changed = original.replace(b'(tags "resistor 0603")', b'(tags "changed")')
        target = self.path / "R_0603.kicad_mod"
        target.write_bytes(changed)
        os.utime(target, ns=(0, target.stat().st_mtime_ns + 2_000_000_000))
        (self.path / "Legacy.kicad_mod").rename(self.path / "Renamed.kicad_mod")
        (self.path / "Mismatch.kicad_mod").unlink()
        (self.path / "Broken.kicad_mod").write_bytes(
            original.replace(b'"R_0603"', b'"Broken"')
        )
        self.assertEqual(tuple(s.name for s in self.library.summaries), VALID)
        self.library.refresh()
        self.assertEqual(
            tuple(s.name for s in self.library.summaries),
            (
                "Added",
                "Broken",
                "Connector_1x02_MP",
                "Ganged_A1_B12",
                "MountingHole_3.2mm_M3",
                "R_0603",
                "Renamed",
            ),
        )
        self.assertEqual(self.library.summary("R_0603").tags, "changed")
        self.assertEqual(self.library.summary("Renamed").declared_name, "Legacy")
        self.assertEqual([f.name for f in self.library.failures], ["Future"])
        # The live footprint keeps its open-time record.
        self.assertIs(self.library.footprint("R_0603"), live)
        self.assertEqual(live.tags, "resistor 0603")
        self.assertEqual(live.to_bytes(), original)

    def test_refresh_reparses_only_changed_files(self) -> None:
        untouched = self.library.summary("Ganged_A1_B12")
        hole = self.path / "MountingHole_3.2mm_M3.kicad_mod"
        hole.write_bytes(hole.read_bytes().replace(b"no annular", b"edited"))
        os.utime(hole, ns=(0, hole.stat().st_mtime_ns + 2_000_000_000))
        self.library.refresh()
        self.assertIs(self.library.summary("Ganged_A1_B12"), untouched)
        self.assertIn(
            "edited", self.library.summary("MountingHole_3.2mm_M3").description
        )


class DirectoryOperationTests(FootprintCase):
    def test_create_writes_a_minimal_footprint_now(self) -> None:
        self.library.create("Fresh")
        path = self.path / "Fresh.kicad_mod"
        self.assertTrue(path.is_file())
        summary = self.library.summary("Fresh")
        self.assertEqual(summary.declared_name, "Fresh")
        self.assertEqual(summary.version, 20260206)
        self.assertEqual(summary.attribute("Value").value, "Fresh")
        self.assertEqual(summary.attribute("Reference").value, "REF**")
        self.assertEqual((summary.pad_count, summary.unique_pad_count), (0, 0))
        self.assertEqual(self.library.footprint("Fresh").to_bytes(), path.read_bytes())
        with self.assertRaises(FileExistsError):
            self.library.create("Fresh")
        with self.assertRaises(FileExistsError):
            self.library.create("Broken")
        for bad in ("", " x", "a/b", "a:b", "..", "a\x00"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.library.create(bad)
        self.assertFalse(any(p.suffix == ".tmp" for p in self.path.iterdir()))

    def test_copy_rewrites_name_and_matching_value_only(self) -> None:
        self.library.copy("R_0603", "R_0603_Copy")
        original = self.read("R_0603")
        copied = self.read("R_0603_Copy")
        self.assertEqual(
            copied,
            original.replace(
                b'(footprint "R_0603"', b'(footprint "R_0603_Copy"'
            ).replace(
                b'(property "Value" "R_0603"', b'(property "Value" "R_0603_Copy"'
            ),
        )
        self.assertEqual(
            self.library.summary("R_0603_Copy").declared_name, "R_0603_Copy"
        )
        self.assertEqual(self.read("R_0603"), original)
        # A Value that differs from the name is left alone.
        self.library.copy("Mismatch", "Mismatch2")
        self.assertEqual(
            self.read("Mismatch2"),
            self.read("Mismatch").replace(
                b'(footprint "InternalName"', b'(footprint "Mismatch2"'
            ),
        )
        with self.assertRaises(KeyError):
            self.library.copy("Missing", "X")
        with self.assertRaises(FileExistsError):
            self.library.copy("R_0603", "Legacy")
        with self.assertRaises(InvalidFootprintError):
            self.library.copy("Broken", "BrokenCopy")
        self.assertFalse((self.path / "BrokenCopy.kicad_mod").exists())

    def test_copy_from_another_open_library(self) -> None:
        other_path = self.root / "Other.pretty"
        other_path.mkdir()
        other = FootprintLibrary.open(other_path)
        self.addCleanup(other.discard)
        self.assertEqual(other.summaries, ())
        other.copy_from(self.library, "Ganged_A1_B12", "Imported")
        self.assertEqual([s.name for s in other.summaries], ["Imported"])
        self.assertEqual(other.summary("Imported").unique_pad_count, 2)
        self.assertIn(
            b'(footprint "Imported"', (other_path / "Imported.kicad_mod").read_bytes()
        )
        with self.assertRaises(TypeError):
            other.copy_from(self.path, "R_0603", "X")  # type: ignore[arg-type]
        closed = FootprintLibrary.open(self.root)
        closed.discard()
        with self.assertRaises(FootprintLifecycleError):
            other.copy_from(closed, "R_0603", "X")

    def test_delete_removes_the_file_and_invalidates_an_open_handle(self) -> None:
        live = self.library.footprint("Legacy")
        self.library.delete("Legacy")
        self.assertFalse((self.path / "Legacy.kicad_mod").exists())
        self.assertNotIn("Legacy", [s.name for s in self.library.summaries])
        self.assertTrue(live.is_closed)
        with self.assertRaises(FootprintLifecycleError):
            live.to_bytes()
        with self.assertRaises(KeyError):
            self.library.footprint("Legacy")
        with self.assertRaises(KeyError):
            self.library.delete("Legacy")
        self.library.delete("Broken")
        self.assertEqual([f.name for f in self.library.failures], ["Future"])

    def test_rename_follows_kicad_and_rebinds_an_open_handle(self) -> None:
        original = self.read("R_0603")
        live = self.library.footprint("R_0603")
        live.set_attribute("Note", "pending")
        pending = live.to_bytes()
        self.library.rename("R_0603", "R_0603_New")
        self.assertFalse((self.path / "R_0603.kicad_mod").exists())
        expected = original.replace(
            b'(footprint "R_0603"', b'(footprint "R_0603_New"'
        ).replace(b'(property "Value" "R_0603"', b'(property "Value" "R_0603_New"')
        self.assertEqual(self.read("R_0603_New"), expected)
        self.assertEqual([s.name for s in self.library.summaries][-1], "R_0603_New")
        self.assertIs(self.library.footprint("R_0603_New"), live)
        self.assertEqual(live.name, "R_0603_New")
        self.assertEqual(live.declared_name, "R_0603_New")
        self.assertEqual(live.attribute("Value").value, "R_0603_New")
        self.assertEqual(live.attribute("Note").value, "pending")
        self.assertTrue(live.is_modified)
        self.assertEqual(
            live.to_bytes(),
            pending.replace(b'(footprint "R_0603"', b'(footprint "R_0603_New"').replace(
                b'(property "Value" "R_0603"', b'(property "Value" "R_0603_New"'
            ),
        )
        live.save()
        self.assertIn(b'"Note" "pending"', self.read("R_0603_New"))
        self.library.rename("Mismatch", "Mismatch_New")
        self.assertEqual(
            self.library.summary("Mismatch_New").attribute("Value").value,
            "InternalName",
        )
        self.library.rename("Mismatch_New", "Mismatch_New")
        with self.assertRaises(KeyError):
            self.library.rename("Missing", "X")
        with self.assertRaises(FileExistsError):
            self.library.rename("Legacy", "Ganged_A1_B12")
        self.assertTrue((self.path / "Legacy.kicad_mod").exists())


class OpenTests(unittest.TestCase):
    def test_open_by_nickname_and_path_is_the_same_object(self) -> None:
        with TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            config_home = root / "10.0"
            config_home.mkdir()
            path = root / "Fixture.pretty"
            shutil.copytree(FIXTURE, path)
            (config_home / "fp-lib-table").write_text(
                "(fp_lib_table\n  (version 7)\n"
                f'  (lib (name "Fixture") (type "KiCad") (uri "{path}")'
                ' (options "") (descr ""))\n)\n',
                encoding="utf-8",
            )
            tables = LibraryTables.open(config_home=config_home)
            library = FootprintLibrary.open("Fixture", tables=tables, on_close="raise")
            self.assertEqual(library.path, path)
            self.assertEqual(library.on_close, "raise")
            self.assertIs(FootprintLibrary.open(path), library)
            self.assertIs(FootprintLibrary.open(str(path), tables=tables), library)
            library.discard()
            reopened = FootprintLibrary.open(path)
            self.assertIsNot(reopened, library)
            self.assertEqual(reopened.on_close, "save")
            reopened.close()
            with self.assertRaises(NotADirectoryError):
                FootprintLibrary.open(root / "Missing.pretty")
            with self.assertRaises(ValueError):
                FootprintLibrary.open(path, on_close="ask")  # type: ignore[arg-type]
            self.assertIsInstance(
                FootprintLibrary.open(path).footprint("R_0603"), Footprint
            )
            FootprintLibrary.open(path).discard()


if __name__ == "__main__":
    unittest.main()
