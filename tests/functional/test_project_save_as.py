"""Bounded Project save-as through public artifact and lifecycle seams."""

import json
import os
import shutil
import stat
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.projects import (
    InvalidProjectError,
    Project,
    ProjectLifecycleError,
    ProjectWriteBlockedError,
)

_ROOT = "00000000-0000-4000-8000-000000000001"
_PLACED = "00000000-0000-4000-8000-000000000002"
_FOREIGN = "00000000-0000-4000-8000-000000000003"
_CHILD = "00000000-0000-4000-8000-000000000004"
_CHILD_SYMBOL = "00000000-0000-4000-8000-000000000005"
_EDGE = "00000000-0000-4000-8000-000000000006"
_JSON = (
    b'{\r\n  "meta": { "filename" : "Old.kicad_pro", "version": 1 },\r\n'
    b'  "opaque": "Old Old.kicad_pro", "text_variables": {}\r\n}\r\n'
)
_SOURCE = f'''(kicad_sch (version 20260306) (generator eeschema) (uuid "{_ROOT}")
  (future "Old" "Old.kicad_sch")
  (symbol (lib_id "Device:R") (at 50 50 0) (uuid "{_PLACED}")
    (property "Reference" "R1") (property "Value" "10K")
    (instances
      (project "Old" (path "/{_ROOT}" (reference "R1") (unit 1)))
      (project "Foreign" (path "/{_FOREIGN}" (reference "Z9") (unit 1)))
    )
  )
)
'''.encode()


class ProjectSaveAsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.pro = self.source / "Old.kicad_pro"
        self.sch = self.source / "Old.kicad_sch"
        self.pro.write_bytes(_JSON)
        self.sch.write_bytes(_SOURCE)
        self.destination = self.root / "destination"
        self.config = self.root / "config"
        self.config.mkdir()
        environment = patch.dict(os.environ, {"KICAD_CONFIG_HOME": str(self.config)})
        environment.start()
        self.addCleanup(environment.stop)

    def verifier(self) -> Path:
        """Supply fixed full electrical evidence for metadata-preservation cases."""
        path = self.root / "proof-cli"
        path.write_text(
            "#!/usr/bin/env python3\nimport pathlib,sys\n"
            "pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text("
            "'(export (version E) (components (comp (ref R1) "
            "(libsource (lib Device) (part R)))) "
            "(libparts (libpart (lib Device) (part R) "
            "(pins (pin (num 1) (name ~) (type passive))))) "
            '(nets (net (name "signal") (node (ref R1) (pin 1) '
            "(pinfunction ~) (pintype passive)))))')\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def hierarchy(self, filename: str = "sub/child.kicad_sch") -> Path:
        """Create explicit owned and foreign instance paths for a child file."""
        self.sch.write_bytes(
            _SOURCE.replace(
                b'(future "Old" "Old.kicad_sch")',
                f'''(future "Old" "Old.kicad_sch")
  (sheet (at 0 0) (size 1 1) (uuid "{_EDGE}")
    (property "Sheetname" "Child") (property "Sheetfile" "{filename}")
    (instances (project "Old" (path "/{_ROOT}" (page "2")))))'''.encode(),
            )
        )
        path = self.source / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            _SOURCE.replace(
                f'(uuid "{_ROOT}")'.encode(), f'(uuid "{_CHILD}")'.encode(), 1
            )
            .replace(_PLACED.encode(), _CHILD_SYMBOL.encode())
            .replace(b'"R1"', b'"R2"')
            .replace(f'(path "/{_ROOT}"'.encode(), f'(path "/{_ROOT}/{_EDGE}"'.encode())
        )
        return path

    def test_save_as_preserves_originals_scopes_metadata_and_rebinds_same_handles(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic().files[0]
        placed = schematic.symbol("R1")
        placed.set_attribute("Value", "22K")
        original = {p: (p.read_bytes(), p.stat().st_ino) for p in (self.pro, self.sch)}
        expected_pro = _JSON.replace(
            b'"filename" : "Old.kicad_pro"', b'"filename" : "New.kicad_pro"'
        )
        expected_sch = _SOURCE.replace(b'"10K"', b'"22K"').replace(
            f'(project "Old" (path "/{_ROOT}"'.encode(),
            f'(project "New" (path "/{_ROOT}"'.encode(),
        )
        project.save_as(self.destination, "New", kicad_cli=self.verifier())
        self.assertEqual(
            {p: (p.read_bytes(), p.stat().st_ino) for p in original}, original
        )
        self.assertEqual(project.directory, self.destination)
        self.assertEqual(project.project_file, self.destination / "New.kicad_pro")
        self.assertEqual(project.schematic_file, self.destination / "New.kicad_sch")
        self.assertIs(project.schematic().files[0], schematic)
        self.assertIs(schematic.symbol("R1"), placed)
        self.assertEqual(schematic.path, project.schematic_file)
        self.assertEqual(placed.path, project.schematic_file)
        self.assertEqual(project.project_file.read_bytes(), expected_pro)
        self.assertEqual(schematic.to_bytes(), expected_sch)
        self.assertEqual(project.schematic_file.read_bytes(), expected_sch)
        self.assertFalse(project.is_modified)
        archives = tuple((self.destination / "New-backups").glob("New-*.zip"))
        self.assertEqual(len(archives), 1)
        with zipfile.ZipFile(archives[0]) as archive:
            self.assertEqual(
                set(archive.namelist()), {"New.kicad_pro", "New.kicad_sch"}
            )
            self.assertEqual(archive.read("New.kicad_pro"), expected_pro)
            self.assertEqual(archive.read("New.kicad_sch"), expected_sch)
        project.close()

    def test_local_context_closure_preserves_raw_rows_libraries_rules_and_worksheets(
        self,
    ) -> None:
        from kicad_primitives.tables import LibraryTables

        (self.source / "frames").mkdir()
        worksheet = self.source / "frames/form.kicad_wks"
        worksheet.write_bytes(b'(page_layout (setup) (tbtext "Old" (name "old")))')
        (self.source / "sim").mkdir()
        workbook = self.source / "sim/session.wbk"
        workbook.write_bytes(b"opaque workbook Old")
        (self.source / "assets").mkdir()
        library = self.source / "assets/Local.kicad_sym"
        library.write_bytes(
            b'(kicad_symbol_lib (version 20251024) (symbol "Old" (property "Note" "Old")))'
        )
        (self.source / "packages/Foot.pretty").mkdir(parents=True)
        footprint = self.source / "packages/Foot.pretty/Part.kicad_mod"
        footprint.write_bytes(
            b'(footprint "Old" (version 20260206) (property "note" "Old"))'
        )
        (self.source / "tables").mkdir()
        nested = self.source / "tables/sym-lib-table"
        nested_raw = (
            "(sym_lib_table (version 7)\r\n"
            f' (lib (name "Local") (type "KiCad") (uri {json.dumps(str(library))}) '
            '(options "") (descr "Old") (hidden) (disabled) (future (keep 001.00))))\r\n'
        ).encode()
        nested.write_bytes(nested_raw)
        (self.source / "sym-lib-table").write_bytes(
            b'(sym_lib_table (version 7) (lib (name "Bundle") (type "Table") '
            b'(uri "${KIPRJMOD}/tables/sym-lib-table") (options "") (descr "Old")))'
        )
        (self.source / "fp-lib-table").write_bytes(
            b'(fp_lib_table (version 7) (lib (name "Foot") (type "KiCad") '
            b'(uri "packages/Foot.pretty") (options "") (descr "Old")))'
        )
        (self.source / "design-block-lib-table").write_bytes(
            b"(design_block_lib_table (version 1))"
        )
        rule = self.source / "Old.kicad_dru"
        rule.write_bytes(
            b'(version 1)\n(rule "Old" (constraint clearance (min 0.2)))\n'
        )
        prl = self.source / "Old.kicad_prl"
        prl.write_bytes(b'{"meta":{"filename":"Old.kicad_prl"},"opaque":"Old"}')
        self.pro.write_text(
            json.dumps(
                {
                    "meta": {"filename": "Old.kicad_pro"},
                    "schematic": {
                        "page_layout_descr_file": str(worksheet),
                        "ngspice": {"workbook_filename": "${KIPRJMOD}/sim/session.wbk"},
                        "top_level_sheets": [
                            {"filename": "Old.kicad_sch", "uuid": _ROOT, "name": "Root"}
                        ],
                    },
                    "pcbnew": {
                        "page_layout_descr_file": "${KIPRJMOD}/frames/form.kicad_wks"
                    },
                    "opaque": "Old Old.kicad_pro",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        original = {
            path: (path.read_bytes(), path.stat().st_ino)
            for path in self.source.rglob("*")
            if path.is_file()
        }
        project = Project.open(self.pro)
        project.save_as(self.destination, "New", kicad_cli=self.verifier())
        self.assertEqual(
            {p: (p.read_bytes(), p.stat().st_ino) for p in original}, original
        )
        for path in (worksheet, workbook, library, footprint):
            self.assertEqual(
                (self.destination / path.relative_to(self.source)).read_bytes(),
                original[path][0],
            )
        self.assertEqual(
            (self.destination / "New.kicad_dru").read_bytes(), rule.read_bytes()
        )
        self.assertEqual(
            (self.destination / "New.kicad_prl").read_bytes(),
            prl.read_bytes().replace(b'"Old.kicad_prl"', b'"New.kicad_prl"'),
        )
        self.assertEqual(
            (self.destination / "tables/sym-lib-table").read_bytes(),
            nested_raw.replace(
                json.dumps(str(library)).encode(),
                b'"${KIPRJMOD}/assets/Local.kicad_sym"',
            ),
        )
        tables = LibraryTables.open(
            config_home=self.config, project_directory=self.destination
        )
        self.assertEqual(
            tables.resolve("Local", library_type="symbol").resolved_path,
            self.destination / "assets/Local.kicad_sym",
        )
        self.assertEqual(
            tables.resolve("Foot", library_type="footprint").resolved_path,
            self.destination / "packages/Foot.pretty",
        )
        data = json.loads(project.project_file.read_bytes())
        self.assertEqual(
            data["schematic"]["top_level_sheets"][0]["filename"], "New.kicad_sch"
        )
        self.assertEqual(
            data["schematic"]["page_layout_descr_file"], "frames/form.kicad_wks"
        )
        self.assertEqual(data["opaque"], "Old Old.kicad_pro")

    def test_readonly_original_tree_can_clone_without_permission_or_byte_changes(
        self,
    ) -> None:
        project = Project.open(self.pro)
        project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        for path in (self.pro, self.sch):
            path.chmod(0o444)
        self.source.chmod(0o555)
        self.addCleanup(self.source.chmod, 0o755)
        project.save_as(self.destination, "New", kicad_cli=self.verifier())
        self.assertEqual(self.pro.read_bytes(), _JSON)
        self.assertEqual(self.sch.read_bytes(), _SOURCE)
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o555)
        self.assertEqual(stat.S_IMODE(self.pro.stat().st_mode), 0o444)
        self.assertEqual(stat.S_IMODE(self.sch.stat().st_mode), 0o444)
        self.assertIn(b'"22K"', project.schematic_file.read_bytes())
        project.close()

    def test_child_layout_foreign_groups_and_retained_child_handles_follow_rebind(
        self,
    ) -> None:
        child_path = self.hierarchy()
        project = Project.open(self.pro)
        root = project.schematic().files[0]
        child = project.schematic().file(child_path)
        placed = child.symbol("R2")
        root_raw, child_raw = root.to_bytes(), child.to_bytes()
        project.save_as(self.destination, "New", kicad_cli=self.verifier())
        self.assertIs(
            project.schematic().file(self.destination / "sub/child.kicad_sch"), child
        )
        self.assertIs(child.symbol("R2"), placed)
        self.assertEqual(placed.path, self.destination / "sub/child.kicad_sch")
        self.assertEqual(
            root.to_bytes(), root_raw.replace(b'(project "Old"', b'(project "New"')
        )
        self.assertEqual(
            child.to_bytes(), child_raw.replace(b'(project "Old"', b'(project "New"')
        )
        self.assertIn(b'(project "Foreign"', child.to_bytes())
        self.assertEqual(child_path.read_bytes(), child_raw)
        self.assertEqual(self.sch.read_bytes(), root_raw)

    def test_missing_meta_members_and_bom_crlf_are_localized_not_whole_json_dumps(
        self,
    ) -> None:
        cases = (
            (b"{}", b'{"meta": {"filename": "New.kicad_pro"}}'),
            (
                b'{"meta":{},"opaque":"Old"}',
                b'{"meta":{"filename": "New.kicad_pro"},"opaque":"Old"}',
            ),
            (
                b"\xef\xbb\xbf" + _JSON,
                b"\xef\xbb\xbf"
                + _JSON.replace(b'"Old.kicad_pro"', b'"New.kicad_pro"', 1),
            ),
        )
        for index, (raw, expected) in enumerate(cases):
            with self.subTest(raw=raw):
                self.pro.write_bytes(raw)
                target = self.root / f"json-{index}"
                Project.open(self.pro).save_as(target, "New", kicad_cli=self.verifier())
                self.assertEqual((target / "New.kicad_pro").read_bytes(), expected)
                self.assertEqual(self.pro.read_bytes(), raw)

    def test_ambiguous_known_json_members_or_additional_roots_fail_before_destination(
        self,
    ) -> None:
        (self.source / "Other.kicad_sch").write_bytes(
            (self.source / "Old.kicad_sch").read_bytes()
        )
        for raw in (
            b'{"meta":{"filename":"Old.kicad_pro","filename":"Other.kicad_pro"}}',
            b'{"meta":{},"meta":{}}',
            b'{"meta":{"filename":12}}',
            b'{"schematic":{"top_level_sheets":[{"filename":"Old.kicad_sch"},{"filename":"Other.kicad_sch"}]}}',
            b'{"schematic":{"top_level_sheets":[{"filename":"Other.kicad_sch"}]}}',
        ):
            with self.subTest(raw=raw):
                self.pro.write_bytes(raw)
                project = Project.open(self.pro)
                with self.assertRaises((ValueError, OSError)):
                    project.save_as(self.destination, "New", kicad_cli=self.verifier())
                self.assertFalse(self.destination.exists())
                self.assertEqual(project.directory, self.source)
                self.assertEqual(self.pro.read_bytes(), raw)
                project.close()
                self.assertEqual(self.pro.read_bytes(), raw)

    def test_root_child_filename_collision_is_rejected_before_any_destination(
        self,
    ) -> None:
        self.hierarchy("New.kicad_sch")
        project = Project.open(self.pro)
        with self.assertRaises((ValueError, OSError)):
            project.save_as(self.destination, "New", kicad_cli=self.verifier())
        self.assertFalse(self.destination.exists())
        self.assertEqual(project.directory, self.source)

    def test_existing_destination_invalid_stem_overlap_and_closed_roots_never_publish(
        self,
    ) -> None:
        project = Project.open(self.pro)
        for name in (
            "",
            ".",
            "..",
            "bad/name",
            "bad\\name",
            "C:bad",
            "CON",
            "bad?",
            "New.kicad_pro",
        ):
            with self.subTest(name=name), self.assertRaises((ValueError, OSError)):
                project.save_as(self.destination, name, kicad_cli=self.verifier())
            self.assertFalse(self.destination.exists())
        self.destination.mkdir()
        sentinel = self.destination / "keep"
        sentinel.write_bytes(b"foreign data")
        with self.assertRaises(FileExistsError):
            project.save_as(self.destination, "New")
        self.assertEqual(sentinel.read_bytes(), b"foreign data")
        nested = self.source / "nested-destination"
        with self.assertRaises(InvalidProjectError):
            project.save_as(nested, "New")
        self.assertFalse(nested.exists())
        project.discard()
        with self.assertRaises(ProjectLifecycleError):
            project.save_as(self.root / "closed-target", "New")
        self.assertFalse((self.root / "closed-target").exists())

    def test_native_source_peer_lock_blocks_clone_before_destination_even_if_readonly_copy(
        self,
    ) -> None:
        project = Project.open(self.pro)
        project.lock_file.write_bytes(b"native peer")
        with self.assertRaises(ProjectWriteBlockedError):
            project.save_as(self.destination, "New", kicad_cli=self.verifier())
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.pro.read_bytes(), _JSON)

    def test_unknown_mixed_owned_and_foreign_group_does_not_partially_rename(
        self,
    ) -> None:
        raw = _SOURCE.replace(
            f'(path "/{_ROOT}" (reference "R1") (unit 1))'.encode(),
            f'(path "/{_ROOT}" (reference "R1") (unit 1)) (path "/{_FOREIGN}" (reference "X9") (unit 1))'.encode(),
        )
        self.sch.write_bytes(raw)
        with self.assertRaises(InvalidProjectError):
            Project.open(self.pro).save_as(
                self.destination, "New", kicad_cli=self.verifier()
            )
        self.assertEqual(self.sch.read_bytes(), raw)
        self.assertFalse(self.destination.exists())

    def test_late_io_failure_retains_original_identity_pending_edits_and_partial_destination(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic().files[0]
        placed = schematic.symbol("R1")
        placed.set_attribute("Value", "22K")
        real_link = os.link

        def fail_profile(source: Path, target: Path) -> None:
            if target == self.destination / "New.kicad_pro":
                (self.destination / "foreign-note").write_bytes(b"do not remove")
                raise OSError("destination profile failed")
            real_link(source, target)

        with (
            patch("kicad_primitives._symbol_persist.os.link", side_effect=fail_profile),
            self.assertRaises(OSError),
        ):
            project.save_as(self.destination, "New", kicad_cli=self.verifier())
        self.assertEqual(project.directory, self.source)
        self.assertIs(project.schematic().files[0], schematic)
        self.assertEqual(placed.path, self.sch)
        self.assertTrue(project.is_modified)
        self.assertEqual(self.pro.read_bytes(), _JSON)
        self.assertEqual(self.sch.read_bytes(), _SOURCE)
        self.assertEqual(
            (self.destination / "foreign-note").read_bytes(), b"do not remove"
        )
        project.discard()
        self.assertEqual(self.sch.read_bytes(), _SOURCE)

    def test_destination_link_replacement_during_zip_publication_cannot_rebind_root(
        self,
    ) -> None:
        project = Project.open(self.pro)
        schematic = project.schematic().files[0]
        schematic.symbol("R1").set_attribute("Value", "22K")
        real_link = os.link
        changed = False

        def replace_destination_after_zip(source: Path, target: Path) -> None:
            nonlocal changed
            real_link(source, target)
            if target.suffix == ".zip" and not changed:
                changed = True
                output = self.destination / "New.kicad_sch"
                moved = self.destination / ".foreign-moved.kicad_sch"
                output.rename(moved)
                output.symlink_to(moved)

        with (
            patch(
                "kicad_primitives._symbol_persist.os.link",
                side_effect=replace_destination_after_zip,
            ),
            self.assertRaises((ValueError, OSError)),
        ):
            project.save_as(self.destination, "New", kicad_cli=self.verifier())
        self.assertTrue(changed)
        self.assertEqual(project.directory, self.source)
        self.assertIs(project.schematic().files[0], schematic)
        self.assertTrue(project.is_modified)
        self.assertEqual(self.sch.read_bytes(), _SOURCE)
        self.assertTrue((self.destination / ".foreign-moved.kicad_sch").is_file())

    def test_late_edit_during_final_destination_validation_keeps_original_binding_and_pending_state(
        self,
    ) -> None:
        fixture = (
            Path(__file__).resolve().parents[1] / "fixtures/projects/rename-native"
        )
        source = self.root / "native-source"
        source.mkdir()
        for path in fixture.glob("*.kicad_*"):
            shutil.copyfile(path, source / path.name)
        original = {
            path: (path.read_bytes(), path.stat().st_ino) for path in source.iterdir()
        }
        pro = source / "issue23403.kicad_pro"
        project = Project.open(pro)
        schematic = project.schematic().files[0]
        placed = schematic.symbol("C0")
        destination = self.root / "native-clone"
        output = destination / "Renamed.kicad_sch"
        real_read = Path.read_bytes
        changed = False

        def late_edit_on_final_output_read(path: Path) -> bytes:
            nonlocal changed
            raw = real_read(path)
            if (
                path == output
                and not changed
                and tuple((destination / "Renamed-backups").glob("*.zip"))
            ):
                changed = True
                placed.set_attribute("Value", "LATE-PENDING-EDIT")
            return raw

        with (
            patch("kicad_primitives._project_relocate._prove", return_value=None),
            patch("pathlib.Path.read_bytes", new=late_edit_on_final_output_read),
            self.assertRaises(ProjectLifecycleError),
        ):
            project.save_as(destination, "Renamed")
        self.assertTrue(changed)
        self.assertEqual(project.directory, source)
        self.assertEqual(project.project_file, pro)
        self.assertIs(project.schematic().files[0], schematic)
        self.assertEqual(placed.path, source / "issue23403.kicad_sch")
        self.assertEqual(placed.value, "LATE-PENDING-EDIT")
        self.assertTrue(project.is_modified)
        project.discard()
        self.assertEqual(
            {path: (path.read_bytes(), path.stat().st_ino) for path in original},
            original,
        )
        self.assertTrue(output.is_file())
        self.assertNotIn(b"LATE-PENDING-EDIT", output.read_bytes())
        self.assertEqual(len(tuple((destination / "Renamed-backups").glob("*.zip"))), 1)
