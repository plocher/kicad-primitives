"""Library tables resolve/write gates from EagleLib2KiCad and nested-table demand.

Donor anchors (behavior only):
- EagleLib2KiCad/tests/unit/test_kicad_environment_service.py
- kDoctor nested ``type \"Table\"`` expansion in symbol_lineage_service

Package locks documented here:
- Project text_variables override kicad_common vars; env KICAD* wins later.
- Project-scope nicknames shadow global on resolve().
- Nested Table URIs expand to leaf libraries; cycles stop.
- Add/remove/rename mutate only the targeted direct rows (source-local).
"""

from __future__ import annotations

import json
import os
import unittest
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.tables import (
    LibraryTables,
    MissingLibraryError,
)


class TablesCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="kp_tables_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative: str, contents: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def write_table(
        self,
        relative: str,
        *,
        root_name: str,
        rows: list[tuple[str, str, str]],
        indent: str = "  ",
    ) -> Path:
        lines = [f"({root_name}", f"{indent}(version 7)"]
        for nickname, entry_type, uri in rows:
            lines.append(
                f'{indent}(lib (name "{nickname}") (type "{entry_type}") '
                f'(uri "{uri}") (options "") (descr ""))'
            )
        lines.append(")")
        return self.write(relative, "\n".join(lines) + "\n")

    def write_kicad_common(self, config_home: Path, variables: dict[str, str]) -> Path:
        path = config_home / "kicad_common.json"
        path.write_text(
            json.dumps({"environment": {"vars": variables}}, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def write_project(
        self, project_directory: Path, text_variables: dict[str, str]
    ) -> Path:
        path = project_directory / f"{project_directory.name}.kicad_pro"
        path.write_text(
            json.dumps(
                {"meta": {"version": 1}, "text_variables": text_variables}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        return path


class ResolveTests(TablesCase):
    def test_symbol_uri_resolves_using_kicad_common_variables(self) -> None:
        config_home = self.root / "9.0"
        config_home.mkdir()
        self.write_table(
            "9.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[
                ("Device", "KiCad", "${KICAD9_SYMBOL_DIR}/Device.kicad_sym"),
            ],
        )
        self.write_kicad_common(
            config_home, {"KICAD9_SYMBOL_DIR": "/opt/kicad/symbols"}
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KICAD9_SYMBOL_DIR", None)
            tables = LibraryTables.open(config_home=config_home)
        libs = tables.libraries("symbol")
        self.assertEqual(len(libs), 1)
        self.assertEqual(
            libs[0].resolved_path, Path("/opt/kicad/symbols/Device.kicad_sym")
        )
        resolved = tables.resolve("Device", library_type="symbol")
        self.assertEqual(resolved.nickname, "Device")
        self.assertEqual(resolved.scope, "global")

    def test_project_text_variables_override_global_variables(self) -> None:
        config_home = self.root / "9.0"
        project = self.root / "example-project"
        config_home.mkdir()
        project.mkdir()
        self.write_table(
            "example-project/sym-lib-table",
            root_name="sym_lib_table",
            rows=[
                ("Custom", "KiCad", "${KICAD_USER_LIB}/symbols/Custom.kicad_sym"),
            ],
        )
        self.write_kicad_common(config_home, {"KICAD_USER_LIB": "/global/libs"})
        self.write_project(project, {"KICAD_USER_LIB": "/project/libs"})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KICAD_USER_LIB", None)
            tables = LibraryTables.open(
                config_home=config_home, project_directory=project
            )
        resolved = tables.resolve("Custom", library_type="symbol")
        self.assertEqual(
            resolved.resolved_path, Path("/project/libs/symbols/Custom.kicad_sym")
        )
        self.assertEqual(resolved.scope, "project")

    def test_versioned_footprint_dir_derived_from_model_dir(self) -> None:
        config_home = self.root / "9.0"
        config_home.mkdir()
        self.write_table(
            "9.0/fp-lib-table",
            root_name="fp_lib_table",
            rows=[("BuiltInFootprints", "KiCad", "${KICAD9_FOOTPRINT_DIR}")],
        )
        self.write_kicad_common(
            config_home, {"KICAD8_MODEL_DIR": "/opt/kicad/share/3dmodels"}
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KICAD9_FOOTPRINT_DIR", None)
            tables = LibraryTables.open(config_home=config_home)
        resolved = tables.resolve("BuiltInFootprints", library_type="footprint")
        self.assertEqual(resolved.resolved_path, Path("/opt/kicad/share/footprints"))

    def test_project_nickname_shadows_global(self) -> None:
        config_home = self.root / "10.0"
        project = self.root / "board"
        config_home.mkdir()
        project.mkdir()
        self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[("Shared", "KiCad", "/global/Shared.kicad_sym")],
            indent="\t",
        )
        self.write_table(
            "board/sym-lib-table",
            root_name="sym_lib_table",
            rows=[("Shared", "KiCad", "/project/Shared.kicad_sym")],
            indent="\t",
        )
        tables = LibraryTables.open(config_home=config_home, project_directory=project)
        resolved = tables.resolve("Shared", library_type="symbol")
        self.assertEqual(resolved.resolved_path, Path("/project/Shared.kicad_sym"))
        self.assertEqual(resolved.scope, "project")
        nicknames = [entry.nickname for entry in tables.libraries("symbol")]
        self.assertEqual(nicknames.count("Shared"), 2)

    def test_nested_table_expands_leaf_libraries(self) -> None:
        config_home = self.root / "10.0"
        nested_dir = self.root / "nested"
        config_home.mkdir()
        nested_dir.mkdir()
        nested = self.write_table(
            "nested/extra-sym-lib-table",
            root_name="sym_lib_table",
            rows=[
                ("NestedLib", "KiCad", "NestedLib.kicad_sym"),
                ("AbsNested", "KiCad", "/abs/Abs.kicad_sym"),
            ],
            indent="\t",
        )
        self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[
                ("Top", "KiCad", "/top/Top.kicad_sym"),
                ("Bundle", "Table", str(nested)),
            ],
            indent="\t",
        )
        tables = LibraryTables.open(config_home=config_home)
        nicknames = {entry.nickname: entry for entry in tables.libraries("symbol")}
        self.assertIn("Top", nicknames)
        self.assertIn("NestedLib", nicknames)
        self.assertIn("AbsNested", nicknames)
        self.assertNotIn("Bundle", nicknames)
        self.assertEqual(
            nicknames["NestedLib"].resolved_path,
            (Path.cwd() / "NestedLib.kicad_sym").resolve(),
        )
        self.assertEqual(
            nicknames["AbsNested"].resolved_path, Path("/abs/Abs.kicad_sym")
        )

    def test_nested_table_cycle_does_not_loop(self) -> None:
        config_home = self.root / "10.0"
        config_home.mkdir()
        a = config_home / "a-table"
        b = config_home / "b-table"
        a.write_text(
            f'(sym_lib_table\n  (version 7)\n  (lib (name "A") (type "Table") '
            f'(uri "{b}") (options "") (descr ""))\n)\n',
            encoding="utf-8",
        )
        b.write_text(
            f'(sym_lib_table\n  (version 7)\n  (lib (name "B") (type "Table") '
            f'(uri "{a}") (options "") (descr ""))\n  (lib (name "Leaf") '
            f'(type "KiCad") (uri "/leaf.kicad_sym") (options "") (descr ""))\n)\n',
            encoding="utf-8",
        )
        self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[("Root", "Table", str(a))],
        )
        tables = LibraryTables.open(config_home=config_home)
        nicknames = [entry.nickname for entry in tables.libraries("symbol")]
        self.assertEqual(nicknames, ["Leaf"])

    def test_repeated_dag_replays_leaves_after_intervening_shadow(self) -> None:
        config_home = self.root / "10.0"
        nested = self.write_table(
            "nested/shared-table",
            root_name="sym_lib_table",
            rows=[("Shared", "KiCad", "/winner.kicad_sym")],
        )
        self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[
                ("First", "Table", str(nested)),
                ("Shared", "KiCad", "/missing.kicad_sym"),
                ("Again", "Table", str(nested)),
            ],
        )
        tables = LibraryTables.open(config_home=config_home)
        self.assertEqual(
            [entry.resolved_path for entry in tables.libraries("symbol")],
            [
                Path("/winner.kicad_sym"),
                Path("/missing.kicad_sym"),
                Path("/winner.kicad_sym"),
            ],
        )
        self.assertEqual(
            tables.resolve("Shared", library_type="symbol").resolved_path,
            Path("/winner.kicad_sym"),
        )

    def test_relative_includes_and_leaves_use_one_captured_context_base(self) -> None:
        config_home = self.root / "10.0"
        project = self.root / "project"
        project.mkdir()
        self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[("First", "Table", "nested/first-table")],
        )
        first = self.write_table(
            "project/nested/first-table",
            root_name="sym_lib_table",
            rows=[("Second", "Table", "second-table")],
        )
        second = self.write_table(
            "project/second-table",
            root_name="sym_lib_table",
            rows=[
                ("Leaf", "KiCad", "local.kicad_sym"),
                ("Cycle", "Table", str(first)),
            ],
        )
        source = {path: path.read_bytes() for path in (first, second)}
        with chdir(project):
            captured = LibraryTables.open(config_home=config_home)
        explicit = LibraryTables.open(config_home=config_home, base_directory=project)
        owned = LibraryTables.open(config_home=config_home, project_directory=project)
        for tables in (captured, explicit, owned):
            with self.subTest(tables=tables):
                self.assertEqual(tables.base_directory, project.resolve())
                self.assertEqual(
                    tables.resolve("Leaf", library_type="symbol").resolved_path,
                    (project / "local.kicad_sym").resolve(),
                )
                self.assertEqual(len(tables.libraries("symbol")), 1)
        self.assertEqual({p: p.read_bytes() for p in source}, source)

    def test_cycle_cut_does_not_suppress_a_later_completed_branch(self) -> None:
        config_home = self.root / "10.0"
        a = config_home / "a"
        b = config_home / "b"
        self.write_table(
            "10.0/a",
            root_name="sym_lib_table",
            rows=[("B", "Table", str(b)), ("Leaf", "KiCad", "/leaf.kicad_sym")],
        )
        self.write_table(
            "10.0/b",
            root_name="sym_lib_table",
            rows=[("A", "Table", str(a))],
        )
        self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[("First", "Table", str(a)), ("Again", "Table", str(b))],
        )
        tables = LibraryTables.open(config_home=config_home)
        self.assertEqual(
            [e.nickname for e in tables.libraries("symbol")], ["Leaf", "Leaf"]
        )

    def test_missing_winning_path_is_not_replaced_by_an_existing_loser(self) -> None:
        present = self.write("exists.kicad_sym", "")
        self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[
                ("Shared", "KiCad", str(present)),
                ("Shared", "KiCad", "/genuinely-missing.kicad_sym"),
            ],
        )
        tables = LibraryTables.open(config_home=self.root / "10.0")
        self.assertEqual(
            tables.resolve("Shared", library_type="symbol").resolved_path,
            Path("/genuinely-missing.kicad_sym"),
        )

    def test_missing_nickname_raises(self) -> None:
        config_home = self.root / "10.0"
        config_home.mkdir()
        self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[("Only", "KiCad", "/only.kicad_sym")],
        )
        tables = LibraryTables.open(config_home=config_home)
        with self.assertRaises(MissingLibraryError):
            tables.resolve("Missing", library_type="symbol")

    def test_kiprjmod_expands_for_project_relative_uri(self) -> None:
        config_home = self.root / "10.0"
        project = self.root / "proj"
        config_home.mkdir()
        project.mkdir()
        self.write_table(
            "proj/sym-lib-table",
            root_name="sym_lib_table",
            rows=[("Local", "KiCad", "${KIPRJMOD}/libs/Local.kicad_sym")],
        )
        tables = LibraryTables.open(config_home=config_home, project_directory=project)
        resolved = tables.resolve("Local", library_type="symbol")
        self.assertEqual(
            resolved.resolved_path, (project / "libs" / "Local.kicad_sym").resolve()
        )


class MutationTests(TablesCase):
    def test_add_remove_rename_preserve_untouched_rows(self) -> None:
        config_home = self.root / "10.0"
        config_home.mkdir()
        table_path = self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[
                ("Keep", "KiCad", "/keep/Keep.kicad_sym"),
                ("Old", "KiCad", "/old/Old.kicad_sym"),
            ],
            indent="\t",
        )
        # Marker comment is not valid sexpr — use descr field as preservation proxy
        # plus exact Keep row bytes after rename of another nickname.
        baseline = table_path.read_text(encoding="utf-8")
        self.assertIn('(name "Keep")', baseline)

        tables = LibraryTables.open(config_home=config_home)
        planned = tables.add_library(
            library_type="symbol",
            scope="global",
            nickname="New",
            uri="/new/New.kicad_sym",
            descr="fresh",
            apply=False,
        )
        self.assertFalse(planned.applied)
        self.assertEqual(table_path.read_text(encoding="utf-8"), baseline)

        added = tables.add_library(
            library_type="symbol",
            scope="global",
            nickname="New",
            uri="/new/New.kicad_sym",
            descr="fresh",
            apply=True,
        )
        self.assertTrue(added.applied)
        after_add = table_path.read_text(encoding="utf-8")
        self.assertIn('(name "Keep")', after_add)
        self.assertIn('(name "Old")', after_add)
        self.assertIn('(name "New")', after_add)
        self.assertIn('(uri "/new/New.kicad_sym")', after_add)

        renamed = tables.rename_library(
            library_type="symbol",
            scope="global",
            old_nickname="Old",
            new_nickname="Renamed",
            apply=True,
        )
        self.assertTrue(renamed.applied)
        after_rename = table_path.read_text(encoding="utf-8")
        self.assertIn('(name "Keep")', after_rename)
        self.assertIn('(name "Renamed")', after_rename)
        self.assertNotIn('(name "Old")', after_rename)
        # Keep URI spelling untouched.
        keep_index = after_rename.index('(name "Keep")')
        self.assertIn(
            "/keep/Keep.kicad_sym", after_rename[keep_index : keep_index + 80]
        )

        removed = tables.remove_library(
            library_type="symbol",
            scope="global",
            nickname="New",
            apply=True,
        )
        self.assertTrue(removed.applied)
        after_remove = table_path.read_text(encoding="utf-8")
        self.assertNotIn('(name "New")', after_remove)
        self.assertIn('(name "Keep")', after_remove)
        self.assertIn('(name "Renamed")', after_remove)

        resolved = tables.resolve("Renamed", library_type="symbol")
        self.assertEqual(resolved.resolved_path, Path("/old/Old.kicad_sym"))

    def test_add_creates_missing_global_table(self) -> None:
        config_home = self.root / "empty-home"
        config_home.mkdir()
        tables = LibraryTables.open(config_home=config_home)
        result = tables.add_library(
            library_type="footprint",
            scope="global",
            nickname="Mods",
            uri="${KIPRJMOD}/Mods.pretty",
            apply=True,
        )
        self.assertTrue(result.table_path.is_file())
        text = result.table_path.read_text(encoding="utf-8")
        self.assertIn("fp_lib_table", text)
        self.assertIn('(name "Mods")', text)

    def test_duplicate_add_fails_without_write(self) -> None:
        config_home = self.root / "10.0"
        config_home.mkdir()
        table_path = self.write_table(
            "10.0/sym-lib-table",
            root_name="sym_lib_table",
            rows=[("A", "KiCad", "/a.kicad_sym")],
        )
        baseline = table_path.read_bytes()
        tables = LibraryTables.open(config_home=config_home)
        with self.assertRaises(ValueError):
            tables.add_library(
                library_type="symbol",
                scope="global",
                nickname="A",
                uri="/other.kicad_sym",
                apply=True,
            )
        self.assertEqual(table_path.read_bytes(), baseline)


if __name__ == "__main__":
    unittest.main()
