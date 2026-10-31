"""Project context behavior from jBOM donors, with corrected sheet resolution.

Donor anchors (behavior only; jBOM product UX and stderr chatter stay behind):
- jBOM/tests/test_project_discovery.py
- jBOM/tests/test_project_context.py
- jBOM/tests/unit/test_project_variables_reader.py

Package policy improvements locked here:
- Sheetfile paths resolve relative to the parent sheet directory, not the project root.
- Opening accepts a project directory or the path of any file in it; the
  directory must hold exactly one .kicad_pro (jBOM rule, ADR 0011 D2).
- Root sheet files come from top_level_sheets, else <name>.kicad_sch, and must exist.
- text_variables absent/empty/null is a normal empty map, not an error.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType

from kicad_primitives.projects import InvalidProjectError, Project


class ProjectCase(unittest.TestCase):
    """Disposable project trees without donor checkout dependence."""

    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="kp_project_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, relative: str, contents: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def write_json(self, relative: str, payload: object) -> Path:
        return self.write(relative, json.dumps(payload))


class OpenAndDiscoveryTests(ProjectCase):
    def test_open_directory_discovers_matching_trio(self) -> None:
        pro = self.write_json("board.kicad_pro", {"meta": {"version": 1}})
        sch = self.write("board.kicad_sch", "(kicad_sch (version 20250114))")
        pcb = self.write("board.kicad_pcb", "(kicad_pcb (version 20241229))")

        project = Project.open(self.root)

        self.assertEqual(project.directory, self.root.resolve())
        self.assertEqual(project.project_file, pro.resolve())
        self.assertEqual(project.schematic_file, sch.resolve())
        self.assertEqual(project.pcb_file, pcb.resolve())
        self.assertEqual(project.base_name, "board")

    def test_open_explicit_project_file(self) -> None:
        pro = self.write_json("nested/board.kicad_pro", {"meta": {"version": 1}})
        sch = self.write("nested/board.kicad_sch", "(kicad_sch (version 20250114))")

        project = Project.open(pro)

        self.assertEqual(project.directory, pro.parent.resolve())
        self.assertEqual(project.project_file, pro.resolve())
        self.assertEqual(project.schematic_file, sch.resolve())
        self.assertIsNone(project.pcb_file)
        self.assertEqual(project.base_name, "board")

    def test_empty_directory_requires_project_file(self) -> None:
        with self.assertRaises(InvalidProjectError) as cm:
            Project.open(self.root)
        self.assertIn("Not a KiCad project", str(cm.exception))

    def test_multiple_projects_are_ambiguous_even_with_an_explicit_file(
        self,
    ) -> None:
        alpha = self.write_json("alpha.kicad_pro", {"meta": {"version": 1}})
        self.write_json("beta.kicad_pro", {"meta": {"version": 1}})
        self.write("alpha.kicad_sch", "(kicad_sch (version 20250114))")
        for reference in (self.root, alpha):
            with self.subTest(reference=reference):
                with self.assertRaises(InvalidProjectError) as cm:
                    Project.open(reference)
                self.assertIn("Ambiguous", str(cm.exception))

    def test_any_file_in_the_directory_is_a_project_reference(self) -> None:
        pro = self.write_json("board.kicad_pro", {"meta": {"version": 1}})
        sch = self.write("board.kicad_sch", "(kicad_sch (version 20250114))")
        notes = self.write("notes.txt", "not KiCad")
        for reference in (sch, notes):
            with self.subTest(reference=reference):
                self.assertEqual(Project.open(reference).project_file, pro.resolve())

    def test_top_level_sheets_select_the_root_sheet_files(self) -> None:
        self.write_json(
            "board.kicad_pro",
            {
                "schematic": {
                    "top_level_sheets": [
                        {"filename": "a.kicad_sch", "name": "A", "uuid": "u-a"},
                        {"filename": "b.kicad_sch", "name": "B", "uuid": "u-b"},
                    ]
                }
            },
        )
        a = self.write("a.kicad_sch", "(kicad_sch (version 20250114))")
        b = self.write("b.kicad_sch", "(kicad_sch (version 20250114))")
        project = Project.open(self.root)
        self.assertEqual(project.root_sheet_files, (a.resolve(), b.resolve()))
        self.assertEqual(
            [f.path for f in project.schematic().root_files],
            [a.resolve(), b.resolve()],
        )

    def test_missing_root_sheet_file_is_not_a_valid_project(self) -> None:
        self.write_json("board.kicad_pro", {"meta": {"version": 1}})
        with self.assertRaises(InvalidProjectError):
            Project.open(self.root)
        self.write_json(
            "board.kicad_pro",
            {"schematic": {"top_level_sheets": [{"filename": "gone.kicad_sch"}]}},
        )
        self.write("board.kicad_sch", "(kicad_sch (version 20250114))")
        with self.assertRaises(InvalidProjectError):
            Project.open(self.root)

    def test_schematic_prefers_project_stem_over_other_names(self) -> None:
        self.write_json("board.kicad_pro", {"meta": {"version": 1}})
        matching = self.write("board.kicad_sch", "(kicad_sch (version 20250114))")
        self.write("zzz.kicad_sch", "(kicad_sch (version 20250114))")

        project = Project.open(self.root)

        self.assertEqual(project.schematic_file, matching.resolve())

    def test_prefer_normal_schematic_over_autosave(self) -> None:
        self.write_json("board.kicad_pro", {"meta": {"version": 1}})
        normal = self.write("board.kicad_sch", "(kicad_sch (version 20250114))")
        self.write("_autosave-board.kicad_sch", "(kicad_sch (version 20250114))")

        project = Project.open(self.root)

        self.assertEqual(project.schematic_file, normal.resolve())

    def test_autosave_schematic_is_not_a_root_sheet_file(self) -> None:
        self.write_json("board.kicad_pro", {"meta": {"version": 1}})
        self.write("_autosave-board.kicad_sch", "(kicad_sch (version 20250114))")

        with self.assertRaises(InvalidProjectError):
            Project.open(self.root)


class HierarchyTests(ProjectCase):
    def test_flat_hierarchy_lists_root_and_children(self) -> None:
        self.write_json("main.kicad_pro", {"meta": {"version": 1}})
        main = self.write(
            "main.kicad_sch",
            """(kicad_sch (version 20250114)
  (sheet (at 50 50) (size 30 20)
    (property "Sheetname" "Power Supply")
    (property "Sheetfile" "power.kicad_sch")
  )
  (sheet (at 50 80) (size 30 20)
    (property "Sheetname" "MCU")
    (property "Sheetfile" "mcu.kicad_sch")
  )
)""",
        )
        power = self.write("power.kicad_sch", "(kicad_sch (version 20250114))")
        mcu = self.write("mcu.kicad_sch", "(kicad_sch (version 20250114))")

        files = Project.open(self.root).schematic_files()

        self.assertEqual(files, (main.resolve(), power.resolve(), mcu.resolve()))

    def test_sheetfile_resolves_relative_to_parent_sheet_directory(self) -> None:
        """Donor defect: jBOM joined Sheetfile to the project directory only."""
        self.write_json("main.kicad_pro", {"meta": {"version": 1}})
        main = self.write(
            "main.kicad_sch",
            """(kicad_sch (version 20250114)
  (sheet (at 1 1) (size 10 10)
    (property "Sheetname" "Nested")
    (property "Sheetfile" "blocks/child.kicad_sch")
  )
)""",
        )
        child = self.write(
            "blocks/child.kicad_sch",
            """(kicad_sch (version 20250114)
  (sheet (at 2 2) (size 10 10)
    (property "Sheetname" "Leaf")
    (property "Sheetfile" "leaf.kicad_sch")
  )
)""",
        )
        leaf = self.write("blocks/leaf.kicad_sch", "(kicad_sch (version 20250114))")
        # Trap: same basename under the project root must not win.
        self.write("leaf.kicad_sch", "(kicad_sch (version 20250114) (uuid wrong))")

        files = Project.open(self.root).schematic_files()

        self.assertEqual(files, (main.resolve(), child.resolve(), leaf.resolve()))
        self.assertNotIn((self.root / "leaf.kicad_sch").resolve(), files)

    def test_missing_child_sheet_is_skipped_without_aborting(self) -> None:
        self.write_json("main.kicad_pro", {"meta": {"version": 1}})
        main = self.write(
            "main.kicad_sch",
            """(kicad_sch (version 20250114)
  (sheet (at 1 1) (size 10 10)
    (property "Sheetname" "Gone")
    (property "Sheetfile" "missing.kicad_sch")
  )
  (sheet (at 2 2) (size 10 10)
    (property "Sheetname" "Present")
    (property "Sheetfile" "present.kicad_sch")
  )
)""",
        )
        present = self.write("present.kicad_sch", "(kicad_sch (version 20250114))")

        files = Project.open(self.root).schematic_files()

        self.assertEqual(files, (main.resolve(), present.resolve()))

    def test_escaped_unicode_sheetfile_uses_structure_without_geometry_read(
        self,
    ) -> None:
        self.write_json("board.kicad_pro", {})
        name = 'blocks/quo"té sheet.kicad_sch'
        main = self.write(
            "board.kicad_sch",
            f'(kicad_sch (version 20260306) (sheet (property "Sheetfile" {json.dumps(name, ensure_ascii=False)})))',
        )
        child = self.write(name, "(kicad_sch (version 20260306))")
        self.assertEqual(
            Project.open(self.root).schematic_files(),
            (main.resolve(), child.resolve()),
        )


class TextVariablesTests(ProjectCase):
    def test_returns_text_variables_verbatim(self) -> None:
        self.write_json(
            "demo.kicad_pro",
            {
                "meta": {"filename": "demo.kicad_pro", "version": 1},
                "text_variables": {
                    "DESIGNER": "John Plocher",
                    "STATUS": "released",
                    "NOTE": "  spaced  with\ttabs  ",
                },
            },
        )
        self.write("demo.kicad_sch", "(kicad_sch (version 20250114))")

        project = Project.open(self.root)

        self.assertEqual(
            dict(project.text_variables),
            {
                "DESIGNER": "John Plocher",
                "STATUS": "released",
                "NOTE": "  spaced  with\ttabs  ",
            },
        )
        self.assertIsInstance(project.text_variables, MappingProxyType)

    def test_absent_empty_or_null_text_variables_are_empty_maps(self) -> None:
        for payload in (
            {"meta": {"version": 1}},
            {"text_variables": {}},
            {"text_variables": None},
        ):
            with self.subTest(payload=payload):
                case = TemporaryDirectory(prefix="kp_vars_")
                self.addCleanup(case.cleanup)
                root = Path(case.name)
                (root / "demo.kicad_pro").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
                (root / "demo.kicad_sch").write_text("(kicad_sch (version 20250114))")
                project = Project.open(root)
                self.assertEqual(dict(project.text_variables), {})

    def test_non_string_entries_are_skipped(self) -> None:
        self.write_json(
            "demo.kicad_pro",
            {"text_variables": {"OK": "yes", "BAD": 3, "ALSO": ["no"]}},
        )
        self.write("demo.kicad_sch", "(kicad_sch (version 20250114))")
        project = Project.open(self.root)
        self.assertEqual(dict(project.text_variables), {"OK": "yes"})

    def test_malformed_project_json_raises(self) -> None:
        self.write("demo.kicad_pro", "{not-json")
        with self.assertRaises(InvalidProjectError):
            Project.open(self.root)

    def test_variables_mapping_is_read_only(self) -> None:
        self.write_json("demo.kicad_pro", {"text_variables": {"A": "1"}})
        self.write("demo.kicad_sch", "(kicad_sch (version 20250114))")
        project = Project.open(self.root)
        with self.assertRaises(TypeError):
            project.text_variables["B"] = "2"  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
