"""Project ERC report contracts ported from kproj without application policy."""

import copy
import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.projects import Project
from kicad_primitives.schematics import (
    ErcAcquisitionError,
    ErcContextError,
    UnsupportedSchematicOperationError,
)
from tests.functional.test_schematic_editing import SOURCE

ROOT_UUID = "11111111-1111-4111-8111-111111111111"
SHEET_UUID = "22222222-2222-4222-8222-222222222222"
CHILD_UUID = "33333333-3333-4333-8333-333333333333"
REPORT = {
    "$schema": "https://schemas.kicad.org/erc.v1.json",
    "source": "board.kicad_sch",
    "date": "2026-10-27T12:00:00Z",
    "kicad_version": "10.0.1",
    "coordinate_units": "mm",
    "included_severities": ["error", "warning", "exclusion"],
    "ignored_checks": [{"key": "ignored_check", "description": "Ignored by project"}],
    "sheets": [
        {
            "path": "/",
            "uuid_path": f"/{ROOT_UUID}",
            "violations": [
                {
                    "type": "pin_conflict",
                    "description": "Original finding",
                    "severity": "error",
                    "excluded": True,
                    "exclusion_comment": "Accepted intentionally",
                    "items": [
                        {
                            "uuid": ROOT_UUID,
                            "description": "First",
                            "pos": {"x": 1.25, "y": -2},
                        },
                        {
                            "uuid": CHILD_UUID,
                            "description": "Second",
                            "pos": {"x": 3, "y": 4.5},
                        },
                    ],
                }
            ],
        },
        {
            "path": "/Human child/",
            "uuid_path": f"/{ROOT_UUID}/{SHEET_UUID}",
            "violations": [],
        },
        {"path": "/not-a-filename/", "uuid_path": f"/{CHILD_UUID}", "violations": []},
    ],
}


class ProjectErcTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.config = self.directory / "config"
        self.config.mkdir()
        self.environment = patch.dict(
            os.environ, {"KICAD_CONFIG_HOME": str(self.config)}
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.pro = self.directory / "board.kicad_pro"
        self.pro.write_text(
            '{"text_variables":{"SELECTED":"captured"}}', encoding="utf-8"
        )
        self.path = self.directory / "board.kicad_sch"
        root_source = SOURCE.replace(
            b"(generator eeschema)",
            (
                f'(generator eeschema) (uuid "{ROOT_UUID}")'
                f' (sheet (uuid "{SHEET_UUID}") (at 0 0) (size 10 10)'
                ' (property "Sheetfile" "sub/child.kicad_sch"))'
            ).encode(),
        )
        self.path.write_bytes(root_source)
        self.child_path = self.directory / "sub/child.kicad_sch"
        self.child_path.parent.mkdir()
        self.child_path.write_bytes(
            SOURCE.replace(
                b"(generator eeschema)",
                f'(generator eeschema) (uuid "{CHILD_UUID}")'.encode(),
            ).replace(b"R1", b"R2")
        )
        self.project = Project.open(self.pro)
        self.cli = self.directory / "fake-cli"

    def verifier(
        self,
        payload: object = REPORT,
        *,
        status: int = 0,
        missing: bool = False,
        stage_assertions: str = "",
    ) -> Path:
        self.cli.write_text(
            "#!/usr/bin/env python3\nimport json,pathlib,sys\n"
            "assert sys.argv[1:3] == ['sch','erc']\n"
            "assert '--refill-zones' not in sys.argv and '--exit-code-violations' not in sys.argv\n"
            "assert sys.argv[sys.argv.index('--units')+1] == 'mm'\n"
            "assert '--severity-all' in sys.argv\n"
            f"payload = json.loads({json.dumps(payload)!r})\n"
            + stage_assertions
            + (
                "root = pathlib.Path(sys.argv[-1])\n"
                "payload['sheets'][0]['violations'][0]['description'] = "
                "('root pending' if 'root pending' in root.read_text() else 'root baseline')"
                "+'|'+('child pending' if 'child pending' in (root.parent/'sub/child.kicad_sch').read_text() else 'child baseline')\n"
                if payload == REPORT
                else ""
            )
            + (
                ""
                if missing
                else "pathlib.Path(sys.argv[sys.argv.index('--output')+1]).write_text(json.dumps(payload))\n"
            )
            + "print('Fontconfig harmless diagnostic', file=sys.stderr)\n"
            + f"sys.exit({status})\n",
            encoding="utf-8",
        )
        self.cli.chmod(0o755)
        return self.cli

    def test_report_preserves_grouping_details_and_uses_pending_locked_readonly_sources(
        self,
    ) -> None:
        root, child = self.project.schematics()
        original = {p: p.read_bytes() for p in (self.path, self.child_path, self.pro)}
        root.symbol("R1").set_attribute("Value", "root pending")
        child.symbol("R2").set_attribute("Value", "child pending")
        (self.directory / "~board.kicad_pro.lck").touch()
        for path in original:
            path.chmod(0o444)
            self.addCleanup(path.chmod, 0o644)
        report = self.project.erc(kicad_cli=self.verifier())
        self.assertEqual(report.source_path, self.path)
        self.assertEqual(report.source, "board.kicad_sch")
        self.assertEqual(report.schema, REPORT["$schema"])
        self.assertEqual(report.coordinate_units, "mm")
        self.assertEqual(report.kicad_version, "10.0.1")
        self.assertEqual(report.ignored_checks[0].key, "ignored_check")
        self.assertEqual(report.sheets[0].source_path, self.path)
        self.assertEqual(report.sheets[1].source_path, self.child_path)
        self.assertIsNone(report.sheets[2].source_path)
        finding = report.sheets[0].violations[0]
        self.assertEqual(finding.description, "root pending|child pending")
        self.assertEqual(finding.severity, "error")
        self.assertTrue(finding.excluded)
        self.assertEqual(finding.exclusion_comment, "Accepted intentionally")
        self.assertEqual(len(finding.items), 2)
        self.assertEqual(finding.items[0].position.x, 1.25)
        self.assertEqual(finding.items[0].position.y, -2.0)
        self.assertEqual(finding.items[1].uuid, CHILD_UUID)
        self.assertEqual(
            report.snapshot.documents[0].sha256,
            hashlib.sha256(root.to_bytes()).hexdigest(),
        )
        self.assertTrue(report.snapshot.documents[1].is_modified)
        self.assertIn("Fontconfig", report.stderr)
        self.assertTrue(self.project.is_modified)
        for path, raw in original.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_library_snapshot_preserves_raw_winners_flags_and_original_variable_context(
        self,
    ) -> None:
        global_table = self.config / "sym-lib-table"
        global_table.write_text(
            '(sym_lib_table (lib (name "Same") (type "KiCad") (uri "global-old.kicad_sym"))'
            ' (lib (name "Missing") (type "KiCad") (uri "fallback.kicad_sym"))'
            ' (lib (name "Global") (type "KiCad") (uri "${GLOBALROOT}/global.kicad_sym")))',
            encoding="utf-8",
        )
        (self.config / "kicad_common.json").write_text(
            json.dumps(
                {
                    "environment": {
                        "vars": {"GLOBALROOT": str(self.directory / "global")}
                    }
                }
            ),
            encoding="utf-8",
        )
        nested = self.directory / "nested/table"
        nested.parent.mkdir()
        nested.write_text(
            '(sym_lib_table (lib (name "NestedOnly") (type "KiCad") (uri "parts/nested.kicad_sym") (hidden)))',
            encoding="utf-8",
        )
        winner = '(lib (name "Same") (type "KiCad") (uri "${SELECTED}/last.kicad_sym") (options "opaque=1") (descr "café") (disabled) (hidden) (future_flag yes))'
        table = self.directory / "sym-lib-table"
        table.write_text(
            '(sym_lib_table (lib (name "Nested") (type "Table") (uri "nested/table"))'
            ' (lib (name "Same") (type "KiCad") (uri "first.kicad_sym"))'
            + winner
            + ' (lib (name "Missing") (type "KiCad") (uri "${KIPRJMOD}/not-present.kicad_sym")))',
            encoding="utf-8",
        )
        # An unrelated preferred-name project must not replace the selected captured context.
        (self.directory / f"{self.directory.name}.kicad_pro").write_text(
            '{"text_variables":{"SELECTED":"wrong-profile"}}', encoding="utf-8"
        )
        self.pro.write_text(
            '{"text_variables":{"SELECTED":"disk-changed"}}', encoding="utf-8"
        )
        expected = winner.replace("${SELECTED}", str(self.directory / "captured"))
        paths = {
            "global": str(self.directory / "global/global.kicad_sym"),
            "nested": str(self.directory / "parts/nested.kicad_sym"),
            "missing": str(self.directory / "not-present.kicad_sym"),
        }
        original = {p: p.read_bytes() for p in (table, nested, global_table)}
        assertions = (
            "table = (pathlib.Path(sys.argv[-1]).parent/'sym-lib-table').read_text()\n"
            "assert json.loads(pathlib.Path(sys.argv[-1]).with_suffix('.kicad_pro').read_text())['text_variables']['SELECTED'] == 'captured'\n"
            f"assert {expected!r} in table\n"
            "assert table.count('(name \"Same\")') == 1\n"
            "assert 'fallback.kicad_sym' not in table and 'first.kicad_sym' not in table\n"
            + "".join(f"assert {p!r} in table\n" for p in paths.values())
        )
        report = self.project.erc(kicad_cli=self.verifier(stage_assertions=assertions))
        self.assertEqual(report.snapshot.config_home, self.config)
        for path, raw in original.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_indeterminate_or_unsupported_table_context_fails_before_cli(self) -> None:
        table = self.directory / "sym-lib-table"
        for row in (
            '(lib (name "Nested") (type "Table") (uri "missing-table"))',
            '(lib (name "Loop") (type "Table") (uri "sym-lib-table"))',
            '(lib (name "Unknown") (type "KiCad") (uri "${UNKNOWN_ROOT}/a.kicad_sym"))',
            '(lib (name "Remote") (type "KiCad") (uri "https://example.invalid/a.kicad_sym"))',
            '(lib (name "DB") (type "Database") (uri "database.kicad_dbl"))',
            '(lib (name "Empty") (type "KiCad") (uri ""))',
            '(lib (name "BadOptions") (type "KiCad") (uri "valid.kicad_sym") (options))',
            "(version 7) (version 7)",
        ):
            with self.subTest(row=row):
                table.write_text(f"(sym_lib_table {row})", encoding="utf-8")
                with self.assertRaises(ErcContextError):
                    self.project.erc(kicad_cli=self.directory / "must-not-run")

    def test_nonzero_status_never_becomes_findings_even_with_valid_report(self) -> None:
        for status in (1, 2, 5, 139):
            with self.subTest(status=status), self.assertRaises(ErcAcquisitionError):
                self.project.erc(kicad_cli=self.verifier(status=status))

    def test_missing_malformed_and_incomplete_reports_fail_not_empty_success(
        self,
    ) -> None:
        with self.assertRaises(ErcAcquisitionError):
            self.project.erc(kicad_cli=self.verifier(missing=True))
        self.cli.write_text(
            "#!/usr/bin/env python3\nimport pathlib,sys\n"
            "pathlib.Path(sys.argv[sys.argv.index('--output')+1]).write_text('{bad json')\n",
            encoding="utf-8",
        )
        with self.assertRaises(ErcAcquisitionError):
            self.project.erc(kicad_cli=self.cli)
        for key in REPORT:
            with self.subTest(missing=key):
                payload = copy.deepcopy(REPORT)
                del payload[key]
                with self.assertRaises(ErcAcquisitionError):
                    self.project.erc(kicad_cli=self.verifier(payload))
        payload = copy.deepcopy(REPORT)
        payload["sheets"] = []
        with self.assertRaises(ErcAcquisitionError):
            self.project.erc(kicad_cli=self.verifier(payload))

    def test_invalid_coordinates_or_exclusions_are_not_stringified_or_downgraded(
        self,
    ) -> None:
        for coordinate in ("1.2", True, None, float("nan"), 10**400):
            with self.subTest(coordinate=coordinate):
                payload = copy.deepcopy(REPORT)
                payload["sheets"][0]["violations"][0]["items"][0]["pos"]["x"] = (
                    coordinate
                )
                with self.assertRaises(ErcAcquisitionError):
                    self.project.erc(kicad_cli=self.verifier(payload))
        payload = copy.deepcopy(REPORT)
        payload["sheets"][0]["violations"][0]["excluded"] = None
        with self.assertRaises(ErcAcquisitionError):
            self.project.erc(kicad_cli=self.verifier(payload))

    def test_unknown_severity_and_empty_item_list_remain_legitimate_findings(
        self,
    ) -> None:
        payload = copy.deepcopy(REPORT)
        payload["sheets"][0]["violations"][0]["severity"] = "future-severity"
        payload["sheets"][0]["violations"][0]["items"] = []
        report = self.project.erc(kicad_cli=self.verifier(payload))
        finding = report.sheets[0].violations[0]
        self.assertEqual(finding.severity, "future-severity")
        self.assertTrue(finding.excluded)
        self.assertEqual(finding.items, ())

    def test_report_missing_a_proved_hierarchy_sheet_is_incomplete(self) -> None:
        payload = copy.deepcopy(REPORT)
        payload["sheets"].pop(1)
        with self.assertRaises(ErcAcquisitionError):
            self.project.erc(kicad_cli=self.verifier(payload))

    def test_document_scope_is_explicitly_unsupported_before_cli(self) -> None:
        for document in self.project.schematics():
            with self.assertRaises(UnsupportedSchematicOperationError):
                document.erc(kicad_cli=self.directory / "must-not-run")

    def test_severity_all_requires_native_coverage_without_losing_future_tokens(
        self,
    ) -> None:
        document = self.project.schematic()
        original = self.path.read_bytes()
        document.symbol("R1").set_attribute("Value", "pending")
        pending = document.to_bytes()
        for coverage in (
            [],
            ["exclusion"],
            ["error", "exclusion"],
            ["error", "warning"],
        ):
            with self.subTest(coverage=coverage):
                payload = copy.deepcopy(REPORT)
                for sheet in payload["sheets"]:
                    sheet["violations"] = []
                payload["included_severities"] = coverage
                with self.assertRaises(ErcAcquisitionError):
                    self.project.erc(kicad_cli=self.verifier(payload))
                self.assertEqual(document.to_bytes(), pending)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertTrue(self.project.is_modified)
        payload = copy.deepcopy(REPORT)
        payload["included_severities"].append("future-severity")
        report = self.project.erc(kicad_cli=self.verifier(payload))
        self.assertEqual(report.included_severities[-1], "future-severity")

    def test_footprint_shadow_and_missing_local_winner_keep_original_context(
        self,
    ) -> None:
        (self.config / "fp-lib-table").write_text(
            '(fp_lib_table (lib (name "Foot") (type "KiCad") (uri "global-old.pretty")))',
            encoding="utf-8",
        )
        row = '(lib (name "Foot") (type "KiCad") (uri "${KIPRJMOD}/original.pretty") (options "keep=1") (disabled) (hidden))'
        missing = '(lib (name "MissingFoot") (type "KiCad") (uri "${KIPRJMOD}/missing.pretty") (future yes))'
        table = self.directory / "fp-lib-table"
        original = f"(fp_lib_table {row} {missing})".encode()
        table.write_bytes(original)
        expected = row.replace("${KIPRJMOD}", str(self.directory))
        expected_missing = missing.replace("${KIPRJMOD}", str(self.directory))
        assertions = (
            "fp = (pathlib.Path(sys.argv[-1]).parent/'fp-lib-table').read_text()\n"
            f"assert {expected!r} in fp and {expected_missing!r} in fp\n"
            "assert 'global-old.pretty' not in fp\n"
            "assert fp.count('(name \"Foot\")') == 1\n"
        )
        report = self.project.erc(kicad_cli=self.verifier(stage_assertions=assertions))
        self.assertTrue(report.snapshot.footprint_table_sha256)
        self.assertEqual(table.read_bytes(), original)

    def test_repeated_nested_dag_include_reapplies_after_an_intervening_override(
        self,
    ) -> None:
        nested = self.directory / "nested/table"
        nested.parent.mkdir()
        nested.write_text(
            '(sym_lib_table (lib (name "SPCoast") (type "KiCad")'
            f' (uri "{self.directory / "local.kicad_sym"}") (descr "nested winner")))',
            encoding="utf-8",
        )
        (self.directory / "sym-lib-table").write_text(
            "(sym_lib_table"
            ' (lib (name "First") (type "Table") (uri "nested/table"))'
            ' (lib (name "SPCoast") (type "KiCad") (uri "missing.kicad_sym"))'
            ' (lib (name "Again") (type "Table") (uri "nested/table")))',
            encoding="utf-8",
        )
        assertions = (
            "table = (pathlib.Path(sys.argv[-1]).parent/'sym-lib-table').read_text()\n"
            f"assert {str(self.directory / 'local.kicad_sym')!r} in table\n"
            "assert 'missing.kicad_sym' not in table\n"
            "assert '(descr \"nested winner\")' in table\n"
            "assert table.count('(name \"SPCoast\")') == 1\n"
        )
        report = self.project.erc(kicad_cli=self.verifier(stage_assertions=assertions))
        self.assertEqual(report.source_path, self.path)

    def test_relative_nested_include_and_leaf_use_original_project_cwd(self) -> None:
        nested = self.directory / "nested/first-table"
        nested.parent.mkdir()
        nested.write_text(
            '(sym_lib_table (lib (name "Second") (type "Table") (uri "second-table")))',
            encoding="utf-8",
        )
        second = self.directory / "second-table"
        second.write_text(
            '(sym_lib_table (lib (name "SPCoast") (type "KiCad") (uri "local.kicad_sym")))',
            encoding="utf-8",
        )
        (self.directory / "sym-lib-table").write_text(
            f'(sym_lib_table (lib (name "First") (type "Table") (uri "{nested}")))',
            encoding="utf-8",
        )
        assertions = (
            f"assert pathlib.Path.cwd() == pathlib.Path({str(self.directory)!r})\n"
            "table = (pathlib.Path(sys.argv[-1]).parent/'sym-lib-table').read_text()\n"
            f"assert {str(self.directory / 'local.kicad_sym')!r} in table\n"
            f"assert {str(nested.parent / 'local.kicad_sym')!r} not in table\n"
        )
        original_cwd = Path.cwd()
        report = self.project.erc(kicad_cli=self.verifier(stage_assertions=assertions))
        self.assertEqual(report.source_path, self.path)
        self.assertEqual(Path.cwd(), original_cwd)

    def test_duplicate_report_keys_are_acquisition_errors(self) -> None:
        raw = json.dumps(REPORT).replace(
            '"source": "board.kicad_sch"',
            '"source": "wrong.kicad_sch", "source": "board.kicad_sch"',
        )
        self.cli.write_text(
            "#!/usr/bin/env python3\nimport pathlib,sys\n"
            f"pathlib.Path(sys.argv[sys.argv.index('--output')+1]).write_text({raw!r})\n",
            encoding="utf-8",
        )
        self.cli.chmod(0o755)
        with self.assertRaises(ErcAcquisitionError):
            self.project.erc(kicad_cli=self.cli)
