"""Shared open: a nickname or a path opens the same library to the same object.

ADR 0009 accepted a process-wide registry keyed by resolved real path. The
registry keeps one live object per library and makes no workflow decision.
"""

import os
import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.symbols import SymbolLibrary
from kicad_primitives.tables import LibraryTables

ORIGINAL = b'(kicad_symbol_lib (version 20251024) (symbol "A" (property "Note" "old")))'


class SymbolOpenRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config_home = self.root / "10.0"
        self.config_home.mkdir()
        self.libs = self.root / "libs"
        self.libs.mkdir()
        self.path = self.libs / "Parts.kicad_sym"
        self.path.write_bytes(ORIGINAL)
        (self.config_home / "sym-lib-table").write_text(
            "(sym_lib_table\n  (version 7)\n"
            f'  (lib (name "Parts") (type "KiCad") (uri "{self.path}")'
            ' (options "") (descr ""))\n)\n',
            encoding="utf-8",
        )
        self.tables = LibraryTables.open(config_home=self.config_home)

    def test_nickname_and_path_open_the_same_object(self) -> None:
        by_nickname = SymbolLibrary.open("Parts", tables=self.tables)
        self.addCleanup(by_nickname.discard)
        self.assertEqual(by_nickname.path, self.path)
        self.assertIs(SymbolLibrary.open(self.path), by_nickname)
        self.assertIs(
            SymbolLibrary.open(str(self.path), tables=self.tables), by_nickname
        )
        relative = Path(os.path.relpath(self.path, Path.cwd()))
        self.assertIs(SymbolLibrary.open(relative), by_nickname)

    def test_unregistered_string_is_a_path(self) -> None:
        library = SymbolLibrary.open(str(self.path), tables=self.tables)
        self.addCleanup(library.discard)
        self.assertEqual(library.path, self.path)
        with self.assertRaises(FileNotFoundError):
            SymbolLibrary.open("NoSuchNickname", tables=self.tables)
        with self.assertRaises(ValueError):
            SymbolLibrary.open("   ", tables=self.tables)

    def test_default_tables_context_resolves_nicknames(self) -> None:
        environment = dict(os.environ)
        os.environ["KICAD_CONFIG_HOME"] = str(self.config_home)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(environment)))
        library = SymbolLibrary.open("Parts")
        self.addCleanup(library.discard)
        self.assertEqual(library.path, self.path)

    def test_default_context_prefers_an_existing_path_and_survives_bad_tables(
        self,
    ) -> None:
        broken_home = self.root / "broken"
        broken_home.mkdir()
        (broken_home / "sym-lib-table").write_text(
            "(sym_lib_table (lib", encoding="utf-8"
        )
        environment = dict(os.environ)
        os.environ["KICAD_CONFIG_HOME"] = str(broken_home)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(environment)))
        # An existing path string never consults the tables.
        library = SymbolLibrary.open(str(self.path))
        self.addCleanup(library.discard)
        self.assertEqual(library.path, self.path)
        # A malformed default table falls back to the string as a path.
        with self.assertRaises(FileNotFoundError):
            SymbolLibrary.open("NoSuchNickname")
        # An explicit table context is still nickname-first.
        self.assertIs(SymbolLibrary.open("Parts", tables=self.tables), library)
        with self.assertRaises(FileNotFoundError):
            SymbolLibrary.open("Missing", tables=self.tables)

    def test_existing_relative_path_wins_over_a_stale_nickname(self) -> None:
        environment = dict(os.environ)
        os.environ["KICAD_CONFIG_HOME"] = str(self.config_home)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(environment)))
        shadow = self.root / "cwd" / "Parts"
        shadow.mkdir(parents=True)
        local = shadow / "Parts.kicad_sym"
        local.write_bytes(ORIGINAL)
        with chdir(shadow):
            by_relative = SymbolLibrary.open("Parts.kicad_sym")
            self.addCleanup(by_relative.discard)
            self.assertEqual(by_relative.path, local)
            by_nickname = SymbolLibrary.open("Parts")  # no such relative file
            self.addCleanup(by_nickname.discard)
            self.assertEqual(by_nickname.path, self.path)

    def test_pending_edits_are_visible_through_a_second_open(self) -> None:
        first = SymbolLibrary.open(self.path)
        first.symbol("A").set_attribute("Note", "pending")
        second = SymbolLibrary.open("Parts", tables=self.tables)
        self.assertIs(second, first)
        self.assertEqual(second.symbol("A").attribute("Note").value, "pending")
        first.discard()

    def test_close_and_discard_remove_the_entry(self) -> None:
        for exit_name in ("close", "discard"):
            with self.subTest(exit=exit_name):
                library = SymbolLibrary.open(self.path)
                getattr(library, exit_name)()
                reopened = SymbolLibrary.open(self.path)
                self.assertIsNot(reopened, library)
                self.assertFalse(reopened.is_closed)
                reopened.discard()

    def test_link_to_an_open_library_resolves_to_the_same_object(self) -> None:
        library = SymbolLibrary.open(self.path)
        self.addCleanup(library.discard)
        link = self.libs / "Alias.kicad_sym"
        link.symlink_to(self.path)
        self.assertIs(SymbolLibrary.open(link), library)
        self.assertEqual(library.path, self.path)

    def test_save_as_rebinds_the_registry_entry(self) -> None:
        library = SymbolLibrary.open(self.path)
        self.addCleanup(library.discard)
        destination = self.libs / "Moved.kicad_sym"
        library.save_as(destination)
        self.assertIs(SymbolLibrary.open(destination), library)
        original = SymbolLibrary.open(self.path)
        self.addCleanup(original.discard)
        self.assertIsNot(original, library)


if __name__ == "__main__":
    unittest.main()
