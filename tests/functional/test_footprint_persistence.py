"""Footprint edits and persistence under the ADR 0009 write promises.

Edits replace only the nodes they mean to. ``validate()`` runs no KiCad and
writes nothing. ``save()`` refuses a changed file unless ``overwrite=True``,
writes no partial file, no stray KiCad file, and no backup.
"""

import os
import shutil
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.footprints import (
    AmbiguousFootprintAttributeError,
    FootprintConflictError,
    FootprintLibrary,
    FootprintLifecycleError,
    UnsupportedOperationError,
)

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "footprints" / "Fixture.pretty"
)


class PersistenceCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "Fixture.pretty"
        shutil.copytree(FIXTURE, self.path)
        self.library = FootprintLibrary.open(self.path)
        self.addCleanup(self.library.discard)
        self.file = self.path / "R_0603.kicad_mod"
        self.original = self.file.read_bytes()

    def listing(self) -> set[str]:
        return {p.name for p in self.path.iterdir()}


class AttributeEditTests(PersistenceCase):
    def test_set_attribute_replaces_only_the_value_atom(self) -> None:
        footprint = self.library.footprint("R_0603")
        value = 'Résumé "quoted" \\ path\nline'
        footprint.set_attribute("Value", value)
        expected = self.original.replace(
            b'(property "Value" "R_0603"',
            '(property "Value" "Résumé \\"quoted\\" \\\\ path\\nline"'.encode(),
            1,
        )
        self.assertEqual(footprint.to_bytes(), expected)
        self.assertEqual(footprint.attribute("Value").value, value)
        self.assertTrue(footprint.is_modified)
        self.assertTrue(self.library.is_modified)
        self.assertEqual(self.file.read_bytes(), self.original)
        self.assertEqual(
            self.library.summary("R_0603").attribute("Value").value, "R_0603"
        )
        self.assertEqual(footprint.summary.attribute("Value").value, value)

    def test_equal_value_is_a_lexical_no_op(self) -> None:
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("value", "R_0603")
        footprint.set_attribute("KiLib_Generator", "SMD_2terminal_chip_molded")
        self.assertFalse(footprint.is_modified)
        self.assertEqual(footprint.to_bytes(), self.original)
        footprint.save()
        self.assertEqual(self.file.read_bytes(), self.original)

    def test_set_attribute_creates_a_missing_attribute_in_file_style(self) -> None:
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("MPN", "RC0603FR-0710KL")
        inserted = (
            b'\n\t(property "MPN" "RC0603FR-0710KL"\n'
            b"\t\t(at 0 0 0)\n"
            b'\t\t(layer "F.Fab")\n'
            b"\t\t(hide yes)\n"
            b"\t\t(effects\n"
            b"\t\t\t(font\n"
            b"\t\t\t\t(size 1 1)\n"
            b"\t\t\t\t(thickness 0.15)\n"
            b"\t\t\t)\n"
            b"\t\t)\n"
            b"\t)"
        )
        anchor = b'(property "KiLib_Generator" "SMD_2terminal_chip_molded"'
        start = self.original.index(anchor)
        end = self.original.index(b"\n\t)", start) + len(b"\n\t)")
        expected = self.original[:end] + inserted + self.original[end:]
        self.assertEqual(footprint.to_bytes(), expected)
        self.assertEqual(footprint.attribute("MPN").hidden, True)
        self.assertEqual(footprint.attribute("MPN").layer, "F.Fab")
        self.assertEqual([a.name for a in footprint.attributes][-1], "MPN")

    def test_add_and_delete_attribute_are_exact_deltas(self) -> None:
        footprint = self.library.footprint("R_0603")
        with self.assertRaises(UnsupportedOperationError):
            footprint.add_attribute("Value", "dup")
        with self.assertRaises(UnsupportedOperationError):
            footprint.add_attribute("value", "dup")
        footprint.delete_attribute("KiLib_Generator")
        start = self.original.index(b'\n\t(property "KiLib_Generator"')
        end = self.original.index(b"\n\t)", start) + len(b"\n\t)")
        expected = self.original[:start] + self.original[end:]
        self.assertEqual(footprint.to_bytes(), expected)
        self.assertEqual([a.name for a in footprint.attributes], ["Reference", "Value"])
        with self.assertRaises(KeyError):
            footprint.delete_attribute("KiLib_Generator")
        footprint.add_attribute("KiLib_Generator", "back")
        self.assertEqual(footprint.attribute("KiLib_Generator").value, "back")
        self.assertTrue(footprint.is_modified)

    def test_compact_single_line_file_stays_single_line(self) -> None:
        compact = (
            b'(footprint "Compact" (version 20260206) (generator "x") (layer "F.Cu")'
            b' (property "Reference" "REF**" (at 0 0 0)))'
        )
        (self.path / "Compact.kicad_mod").write_bytes(compact)
        footprint = self.library.footprint("Compact")
        footprint.set_attribute("Note", "n")
        self.assertEqual(
            footprint.to_bytes(),
            compact.replace(
                b"(at 0 0 0))",
                b'(at 0 0 0)) (property "Note" "n" (at 0 0 0) (layer "F.Fab")'
                b" (hide yes) (effects (font (size 1 1) (thickness 0.15))))",
            ),
        )
        footprint.delete_attribute("Note")
        self.assertEqual(footprint.to_bytes(), compact)

    def test_bad_requests_fail_without_edits(self) -> None:
        duplicated = self.original.replace(
            b'(property "Value" "R_0603"', b'(property "Value" "R_0603"', 1
        )
        twice = self.path / "Twice.kicad_mod"
        marker = b'\t(property "KiLib_Generator"'
        twice.write_bytes(
            duplicated.replace(
                marker, b'\t(property "value" "again" (at 0 0 0))\n' + marker, 1
            )
        )
        twice_fp = self.library.footprint("Twice")
        with self.assertRaises(AmbiguousFootprintAttributeError):
            twice_fp.set_attribute("Value", "x")
        footprint = self.library.footprint("R_0603")
        for action, error in (
            (lambda: footprint.set_attribute("", "x"), ValueError),
            (lambda: footprint.set_attribute("Value", "a\x00b"), ValueError),
            (lambda: footprint.set_attribute("Value", 3), TypeError),  # type: ignore[arg-type]
            (lambda: footprint.add_attribute("\x00", "x"), ValueError),
        ):
            with self.subTest(error=error), self.assertRaises(error):
                action()
        self.assertEqual(footprint.to_bytes(), self.original)
        self.assertFalse(footprint.is_modified)

    def test_unsupported_formats_refuse_edits_validate_and_writes(self) -> None:
        legacy = self.library.footprint("Legacy")
        raw = legacy.to_bytes()
        for action in (
            lambda: legacy.set_attribute("Value", "x"),
            lambda: legacy.add_attribute("Note", "x"),
            lambda: legacy.delete_attribute("Value"),
            legacy.validate,
            legacy.save,
            lambda: legacy.save_as(self.path / "LegacyCopy.kicad_mod"),
        ):
            with self.assertRaises(UnsupportedOperationError):
                action()
        self.assertEqual(legacy.to_bytes(), raw)
        self.assertFalse(legacy.is_modified)
        self.assertFalse((self.path / "LegacyCopy.kicad_mod").exists())
        legacy.close()  # clean close of a read-only file writes nothing
        self.assertEqual((self.path / "Legacy.kicad_mod").read_bytes(), raw)


class SaveTests(PersistenceCase):
    def test_validate_reports_without_writing(self) -> None:
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "pending")
        footprint.validate()
        footprint.validate(self.path / "Elsewhere.kicad_mod")
        with self.assertRaises(NotADirectoryError):
            footprint.validate(self.root / "missing" / "X.kicad_mod")
        with self.assertRaises(IsADirectoryError):
            footprint.validate(self.root)
        self.assertEqual(self.file.read_bytes(), self.original)
        self.assertTrue(footprint.is_modified)
        self.assertEqual(self.listing(), {p.name for p in FIXTURE.iterdir()})

    def test_save_writes_exactly_the_preview_and_clears_the_mark(self) -> None:
        self.file.chmod(0o640)
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "saved")
        pending = footprint.to_bytes()
        footprint.save()
        self.assertEqual(self.file.read_bytes(), pending)
        self.assertFalse(footprint.is_modified)
        self.assertFalse(self.library.is_modified)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o640)
        self.assertEqual(self.listing(), {p.name for p in FIXTURE.iterdir()})
        self.assertFalse(self.file.with_suffix(".bak").exists())
        self.assertFalse(self.path.joinpath("R_0603.kicad_mod.bak").exists())
        # The library's own summary sees the new file only after refresh.
        self.assertEqual(
            self.library.summary("R_0603").attribute("Value").value, "R_0603"
        )
        self.library.refresh()
        self.assertEqual(
            self.library.summary("R_0603").attribute("Value").value, "saved"
        )
        inode = self.file.stat().st_ino
        footprint.save()
        self.assertEqual(self.file.stat().st_ino, inode)

    def test_external_change_conflicts_and_overwrite_is_the_way_through(self) -> None:
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "mine")
        foreign = self.original.replace(b'(tags "resistor 0603")', b'(tags "theirs")')
        self.file.write_bytes(foreign)
        with self.assertRaises(FootprintConflictError) as raised:
            footprint.save()
        self.assertIn(str(self.file), str(raised.exception))
        self.assertEqual(self.file.read_bytes(), foreign)
        self.assertTrue(footprint.is_modified)
        with self.assertRaises(FootprintConflictError):
            footprint.close()
        self.assertFalse(footprint.is_closed)
        footprint.save(overwrite=True)
        self.assertEqual(self.file.read_bytes(), footprint.to_bytes())
        self.assertIn(b'"Value" "mine"', self.file.read_bytes())
        self.assertNotIn(b"theirs", self.file.read_bytes())
        self.assertFalse(footprint.is_modified)
        footprint.set_attribute("Value", "again")
        footprint.save()  # the overwrite advanced the fingerprint

    def test_deleted_file_conflicts_and_overwrite_recreates(self) -> None:
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "mine")
        self.file.unlink()
        with self.assertRaises(FootprintConflictError):
            footprint.save()
        self.assertFalse(self.file.exists())
        footprint.save(overwrite=True)
        self.assertEqual(self.file.read_bytes(), footprint.to_bytes())

    def test_failed_write_leaves_original_and_no_stray_files(self) -> None:
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "pending")
        pending = footprint.to_bytes()
        for target in ("os.replace", "os.fsync"):
            with self.subTest(target=target):
                with (
                    patch(
                        f"kicad_primitives._symbol_persist.{target}",
                        side_effect=OSError("failed"),
                    ),
                    self.assertRaises(OSError),
                ):
                    footprint.save()
                self.assertEqual(self.file.read_bytes(), self.original)
                self.assertEqual(footprint.to_bytes(), pending)
                self.assertTrue(footprint.is_modified)
                self.assertEqual(self.listing(), {p.name for p in FIXTURE.iterdir()})

    def test_links_and_readonly_files_are_refused_not_bypassed(self) -> None:
        link = self.path / "Link.kicad_mod"
        link.symlink_to(self.file)
        self.library.refresh()
        linked = self.library.footprint("Link")
        linked.set_attribute("Value", "x")
        with self.assertRaises(UnsupportedOperationError):
            linked.save()
        self.assertEqual(self.file.read_bytes(), self.original)
        self.file.chmod(0o444)
        self.addCleanup(self.file.chmod, 0o644)
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "x")
        with self.assertRaises(PermissionError):
            footprint.save()
        self.assertEqual(self.file.read_bytes(), self.original)


class SaveAsTests(PersistenceCase):
    def test_save_as_inside_the_library_rebinds_and_joins_the_library(self) -> None:
        self.file.chmod(0o640)
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "forked")
        destination = self.path / "R_0603_Fork.kicad_mod"
        footprint.save_as(destination)
        self.assertEqual(footprint.path, destination)
        self.assertEqual(footprint.name, "R_0603_Fork")
        self.assertEqual(footprint.declared_name, "R_0603")  # save-as copies content
        self.assertEqual(destination.read_bytes(), footprint.to_bytes())
        self.assertEqual(self.file.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o640)
        self.assertFalse(footprint.is_modified)
        self.assertIs(self.library.footprint("R_0603_Fork"), footprint)
        self.assertIs(footprint.library, self.library)
        self.assertIn("R_0603_Fork", [s.name for s in self.library.summaries])
        self.assertIsNot(self.library.footprint("R_0603"), footprint)
        with self.assertRaises(FileExistsError):
            footprint.save_as(self.file)
        footprint.set_attribute("Value", "over")
        footprint.save_as(self.file, overwrite=True)
        self.assertEqual(self.file.read_bytes(), footprint.to_bytes())
        self.assertEqual(footprint.path, self.file)

    def test_save_as_outside_detaches_from_the_library(self) -> None:
        footprint = self.library.footprint("R_0603")
        elsewhere = self.root / "Elsewhere.kicad_mod"
        footprint.save_as(elsewhere)
        self.assertIsNone(footprint.library)
        self.assertEqual(self.library.footprints, ())
        self.assertEqual(elsewhere.read_bytes(), self.original)
        footprint.set_attribute("Value", "detached")
        footprint.close()
        self.assertIn(b'"Value" "detached"', elsewhere.read_bytes())
        self.assertEqual(self.file.read_bytes(), self.original)

    def test_save_as_refuses_unsafe_destinations_and_keeps_identity(self) -> None:
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "pending")
        pending = footprint.to_bytes()
        linked_parent = self.root / "linked"
        linked_parent.symlink_to(self.path, target_is_directory=True)
        dangling = self.path / "Dangling.kicad_mod"
        dangling.symlink_to(self.root / "missing")
        for destination in (
            dangling,
            linked_parent / "New.kicad_mod",
            self.root / "absent" / "New.kicad_mod",
            self.root / "NotAFootprint.txt",
            self.path / "bad:name.kicad_mod",
        ):
            with self.subTest(destination=destination):
                with self.assertRaises((OSError, ValueError, RuntimeError)):
                    footprint.save_as(destination)
                self.assertEqual(footprint.path, self.file)
                self.assertEqual(footprint.to_bytes(), pending)
                self.assertTrue(footprint.is_modified)
        self.assertEqual(self.file.read_bytes(), self.original)


class CloseTests(PersistenceCase):
    def test_footprint_close_and_with_follow_the_lifecycle(self) -> None:
        with self.library.footprint("R_0603") as footprint:
            footprint.set_attribute("Value", "with-saved")
        self.assertTrue(footprint.is_closed)
        self.assertIn(b'"Value" "with-saved"', self.file.read_bytes())
        saved = self.file.read_bytes()
        with self.assertRaises(KeyError), self.library.footprint("R_0603") as footprint:
            footprint.set_attribute("Value", "abandoned")
            raise KeyError("client failure")
        self.assertTrue(footprint.is_closed)
        self.assertEqual(self.file.read_bytes(), saved)
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "discarded")
        footprint.discard()
        footprint.close()
        self.assertEqual(self.file.read_bytes(), saved)
        for action in (
            footprint.to_bytes,
            footprint.save,
            lambda: footprint.set_attribute("Value", "x"),
        ):
            with self.assertRaises(FootprintLifecycleError):
                action()

    def test_library_close_save_saves_modified_open_footprints_only(self) -> None:
        a = self.library.footprint("R_0603")
        b = self.library.footprint("Ganged_A1_B12")
        c = self.library.footprint("Legacy")  # read-only, clean
        a.set_attribute("Value", "a")
        b_bytes = b.to_bytes()
        b_mtime = b.path.stat().st_mtime_ns
        self.library.close()
        self.assertTrue(self.library.is_closed)
        self.assertTrue(a.is_closed and b.is_closed and c.is_closed)
        self.assertIn(b'"Value" "a"', self.file.read_bytes())
        self.assertEqual(b.path.read_bytes(), b_bytes)
        self.assertEqual(b.path.stat().st_mtime_ns, b_mtime)

    def test_library_close_save_failure_keeps_library_open(self) -> None:
        a = self.library.footprint("R_0603")
        a.set_attribute("Value", "a")
        self.file.write_bytes(self.original.replace(b"resistor", b"foreign"))
        with self.assertRaises(FootprintConflictError):
            self.library.close()
        self.assertFalse(self.library.is_closed)
        self.assertFalse(a.is_closed)
        self.assertTrue(a.is_modified)
        a.save(overwrite=True)
        self.library.close()
        self.assertTrue(self.library.is_closed)

    def test_library_on_close_discard_and_raise(self) -> None:
        self.library.discard()
        library = FootprintLibrary.open(self.path, on_close="discard")
        edited = library.footprint("R_0603")
        edited.set_attribute("Value", "lost")
        library.close()
        self.assertTrue(library.is_closed and edited.is_closed)
        self.assertEqual(self.file.read_bytes(), self.original)

        library = FootprintLibrary.open(self.path, on_close="raise")
        self.assertEqual(library.on_close, "raise")
        one = library.footprint("R_0603")
        two = library.footprint("Ganged_A1_B12")
        one.set_attribute("Value", "one")
        two.set_attribute("Value", "two")
        library.footprint("Legacy")
        with self.assertRaises(FootprintLifecycleError) as raised:
            library.close()
        self.assertIn("Ganged_A1_B12", str(raised.exception))
        self.assertIn("R_0603", str(raised.exception))
        self.assertFalse(library.is_closed)
        one.save()
        two.discard()
        library.close()
        self.assertTrue(library.is_closed)
        self.assertIn(b'"Value" "one"', self.file.read_bytes())
        self.assertNotIn(
            b'"Value" "two"', (self.path / "Ganged_A1_B12.kicad_mod").read_bytes()
        )

    def test_library_with_block_applies_on_close_and_discards_on_exception(
        self,
    ) -> None:
        self.library.discard()
        with FootprintLibrary.open(self.path) as library:
            library.footprint("R_0603").set_attribute("Value", "block")
        self.assertTrue(library.is_closed)
        self.assertIn(b'"Value" "block"', self.file.read_bytes())
        saved = self.file.read_bytes()
        with self.assertRaises(KeyError), FootprintLibrary.open(self.path) as library:
            library.footprint("R_0603").set_attribute("Value", "abandoned")
            raise KeyError("client failure")
        self.assertTrue(library.is_closed)
        self.assertEqual(self.file.read_bytes(), saved)
        self.assertEqual(
            {p.name for p in self.path.iterdir()}, {p.name for p in FIXTURE.iterdir()}
        )

    def test_no_temporary_files_survive_any_path(self) -> None:
        footprint = self.library.footprint("R_0603")
        footprint.set_attribute("Value", "x")
        footprint.save()
        self.library.create("New")
        self.library.copy("New", "New2")
        self.library.rename("New2", "New3")
        self.library.delete("New3")
        names = {p.name for p in self.path.iterdir()}
        self.assertFalse({n for n in names if n.startswith(".") or n.endswith(".tmp")})
        self.assertEqual(names, {p.name for p in FIXTURE.iterdir()} | {"New.kicad_mod"})
        os.utime(self.file)


if __name__ == "__main__":
    unittest.main()
