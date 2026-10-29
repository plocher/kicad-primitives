"""Library discovery under explicit roots and portable ``${VAR}`` URI spelling.

ADR 0009: discovery roots and URI style are client policy. The package
offers two read-only primitives and leaves registration to ``add_entry``.
"""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.tables import LibraryTables


class FindLibrariesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "a" / "Alpha.pretty").mkdir(parents=True)
        (self.root / "a" / "Alpha.pretty" / "Nested.pretty").mkdir()
        (self.root / "a" / "Alpha.pretty" / "Part.kicad_mod").write_text("")
        (self.root / "a" / "Alpha.pretty" / "Inside.kicad_sym").write_text("")
        (self.root / "b" / "deep").mkdir(parents=True)
        (self.root / "b" / "deep" / "Beta.pretty").mkdir()
        (self.root / "b" / "deep" / "Beta.kicad_sym").write_text("")
        (self.root / "b" / "Gamma.kicad_sym").write_text("")
        (self.root / "b" / "NotALib.kicad_sym").mkdir()
        (self.root / "b" / "readme.txt").write_text("")

    def test_footprint_candidates_are_pretty_directories_not_descended(self) -> None:
        found = LibraryTables.find_libraries("footprint", [self.root])
        self.assertEqual(
            found,
            (
                self.root / "a" / "Alpha.pretty",
                self.root / "b" / "deep" / "Beta.pretty",
            ),
        )

    def test_symbol_candidates_are_files_under_all_roots_deduplicated(self) -> None:
        found = LibraryTables.find_libraries(
            "symbol", [self.root / "b", str(self.root / "b" / "deep"), self.root / "b"]
        )
        self.assertEqual(
            found,
            (
                self.root / "b" / "Gamma.kicad_sym",
                self.root / "b" / "deep" / "Beta.kicad_sym",
            ),
        )

    def test_pattern_filters_on_stem(self) -> None:
        self.assertEqual(
            LibraryTables.find_libraries("symbol", [self.root], "G*"),
            (self.root / "b" / "Gamma.kicad_sym",),
        )
        self.assertEqual(LibraryTables.find_libraries("symbol", [self.root], "g*"), ())

    def test_bad_inputs_fail_before_walking(self) -> None:
        with self.assertRaises(NotADirectoryError):
            LibraryTables.find_libraries("symbol", [self.root / "missing"])
        with self.assertRaises(NotADirectoryError):
            LibraryTables.find_libraries("symbol", [self.root / "b" / "readme.txt"])
        with self.assertRaises(ValueError):
            LibraryTables.find_libraries("schematic", [self.root])  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            LibraryTables.find_libraries("symbol", [self.root], "")
        self.assertEqual(LibraryTables.find_libraries("symbol", []), ())


class PortableUriTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config_home = self.root / "10.0"
        self.config_home.mkdir()
        self.project = self.root / "board"
        self.project.mkdir()
        self.share = self.root / "share"
        (self.share / "footprints").mkdir(parents=True)
        (self.share / "symbols").mkdir()
        (self.config_home / "kicad_common.json").write_text(
            json.dumps(
                {
                    "environment": {
                        "vars": {
                            "KICAD10_MODEL_DIR": str(self.share / "3dmodels"),
                            "KICAD_USER_LIB": str(self.root / "user"),
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (self.project / "board.kicad_pro").write_text("{}", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("KICAD") or key == "KIPRJMOD":
                    del os.environ[key]
            self.tables = LibraryTables.open(
                config_home=self.config_home, project_directory=self.project
            )
            self.standalone = LibraryTables.open(config_home=self.config_home)

    def test_project_paths_use_kiprjmod(self) -> None:
        self.assertEqual(
            self.tables.portable_uri(self.project / "libs" / "Local.pretty"),
            "${KIPRJMOD}/libs/Local.pretty",
        )
        self.assertEqual(self.tables.portable_uri(self.project), "${KIPRJMOD}")
        self.assertEqual(
            self.tables.portable_uri(str(self.project / "Local.kicad_sym")),
            "${KIPRJMOD}/Local.kicad_sym",
        )

    def test_share_paths_prefer_the_versioned_alias(self) -> None:
        self.assertEqual(
            self.tables.portable_uri(self.share / "footprints" / "Resistor_SMD.pretty"),
            "${KICAD10_FOOTPRINT_DIR}/Resistor_SMD.pretty",
        )
        self.assertEqual(
            self.standalone.portable_uri(self.share / "symbols" / "Device.kicad_sym"),
            "${KICAD10_SYMBOL_DIR}/Device.kicad_sym",
        )
        self.assertEqual(
            self.standalone.portable_uri(self.root / "user" / "X.pretty"),
            "${KICAD_USER_LIB}/X.pretty",
        )

    def test_unmatched_and_relative_paths_become_absolute(self) -> None:
        elsewhere = self.root / "elsewhere" / "Lib.pretty"
        self.assertEqual(self.tables.portable_uri(elsewhere), elsewhere.as_posix())
        self.assertEqual(
            self.standalone.portable_uri(self.project / "Local.pretty"),
            (self.project / "Local.pretty").as_posix(),
        )
        self.assertEqual(
            self.tables.portable_uri(self.project / ".." / "board" / "L.pretty"),
            "${KIPRJMOD}/L.pretty",
        )

    def test_registration_stays_a_client_choice(self) -> None:
        library = self.project / "Local.pretty"
        library.mkdir()
        table = self.tables.table("footprint", "project")
        entry = table.add_entry("Local", self.tables.portable_uri(library))
        self.assertEqual(entry.uri, "${KIPRJMOD}/Local.pretty")
        self.assertEqual(entry.resolved_path, library)
        self.assertFalse(table.path.exists())
        table.discard()


if __name__ == "__main__":
    unittest.main()
