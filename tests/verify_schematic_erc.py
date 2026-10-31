"""Opt-in real KiCad ERC report/context/read-only pending-snapshot contract."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives._kicad_cli import resolve_kicad_cli
from kicad_primitives.projects import Project
from kicad_primitives.schematics import ErcReport, UnsupportedSchematicOperationError
from kicad_primitives.tables import LibraryTables


def main() -> None:
    """Check real JSON metadata/findings without saving any original source."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-cli", type=Path)
    args = parser.parse_args()
    fixtures = Path(__file__).parent / "fixtures/schematics"
    with TemporaryDirectory(prefix="kp-native-erc-") as temporary:
        root = Path(temporary).resolve()
        for folder in ("attribute-edit", "erc-context"):
            for path in (fixtures / folder).iterdir():
                if path.name != "PROVENANCE.txt":
                    shutil.copyfile(path, root / path.name)
        config = root / "config"
        config.mkdir()
        with patch.dict(os.environ, {"KICAD_CONFIG_HOME": str(config)}):
            project = Project.open(root / "cpNode-IOX.kicad_pro")
            schematic = project.schematic().files[0]
            baseline = project.erc(kicad_cli=args.kicad_cli)
            assert isinstance(baseline, ErcReport)
            # Native Table links and leaves both resolve against process CWD.
            second = root / "second-table"
            original_table = (root / "sym-lib-table").read_bytes()
            physical = LibraryTables.open(
                config_home=config, project_directory=root
            ).table("symbol", "project")
            for entry in physical.entries:
                entry.set_uri("local.kicad_sym")
            assert (root / "sym-lib-table").read_bytes() == original_table
            physical.save_as(second)
            assert second.read_bytes() == original_table.replace(
                b"${KIPRJMOD}/local.kicad_sym", b"local.kicad_sym"
            )
            physical.close()
            first = root / "nested/first-table"
            first.parent.mkdir()
            first.write_text(
                '(sym_lib_table (lib (name "Second") (type "Table") (uri "second-table")))',
                encoding="utf-8",
            )
            (root / "sym-lib-table").write_text(
                f'(sym_lib_table (lib (name "First") (type "Table") (uri "{first}")))',
                encoding="utf-8",
            )
            with TemporaryDirectory(prefix="kp-native-erc-control-") as control:
                raw_report = Path(control) / "native.json"
                native = subprocess.run(
                    [
                        str(resolve_kicad_cli(args.kicad_cli)),
                        "sch",
                        "erc",
                        "--format",
                        "json",
                        "--units",
                        "mm",
                        "--severity-all",
                        "--output",
                        str(raw_report),
                        str(schematic.path),
                    ],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=120,
                )
                assert native.returncode == 0, native.stderr
                raw = json.loads(raw_report.read_bytes())
                assert not any(
                    v["type"] == "lib_symbol_issues"
                    for s in raw["sheets"]
                    for v in s["violations"]
                )
                assert {"error", "warning", "exclusion"}.issubset(
                    raw["included_severities"]
                )
            relative_report = project.erc(kicad_cli=args.kicad_cli)
            resolved = LibraryTables.open(
                config_home=config, project_directory=root
            ).resolve("SPCoast", library_type="symbol")
            assert resolved.resolved_path == root / "local.kicad_sym"
            assert not any(
                finding.type == "lib_symbol_issues"
                for sheet in relative_report.sheets
                for finding in sheet.violations
            )
            assert (
                relative_report.snapshot.symbol_table_sha256
                == baseline.snapshot.symbol_table_sha256
            )
            # Independently test ordered DAG projection with absolute leaf URIs.
            # Native repeated loaders can emit duplicate/load-status artifacts;
            # those are not a golden finding count for the flattened winners.
            dag = root / "dag-table"
            dag.write_bytes(
                second.read_bytes().replace(
                    b'"local.kicad_sym"',
                    json.dumps(str(root / "local.kicad_sym")).encode(),
                )
            )
            (root / "sym-lib-table").write_text(
                f'(sym_lib_table (lib (name "First") (type "Table") (uri "{dag}"))'
                ' (lib (name "SPCoast") (type "KiCad") (uri "missing.kicad_sym"))'
                f' (lib (name "Again") (type "Table") (uri "{dag}")))',
                encoding="utf-8",
            )
            tables = LibraryTables.open(config_home=config, project_directory=root)
            assert (
                tables.resolve("SPCoast", library_type="symbol").resolved_path
                == root / "local.kicad_sym"
            )
            assert [e.nickname for e in tables.libraries("symbol")] == [
                "SPCoast",
                "power",
                "SPCoast",
                "SPCoast",
                "power",
            ]
            schematic.symbol("R3").set_attribute("Value", "22K")
            original = {
                p: (p.read_bytes(), p.stat().st_ino)
                for p in (*root.iterdir(), first)
                if p.is_file()
            }
            (root / "~cpNode-IOX.kicad_pro.lck").touch()
            assert project.is_locked
            for path in original:
                path.chmod(0o444)
            root.chmod(0o555)
            try:
                report = project.erc(kicad_cli=args.kicad_cli)
                rerun = project.erc(kicad_cli=args.kicad_cli)
                assert rerun.snapshot.symbol_table_sha256 == (
                    report.snapshot.symbol_table_sha256
                )
                assert report.schema == "https://schemas.kicad.org/erc.v1.json"
                assert report.kicad_version.startswith("10.")
                assert report.coordinate_units == "mm"
                assert report.source == "cpNode-IOX.kicad_sch"
                assert report.source_path == schematic.path
                assert report.sheets[0].source_path == schematic.path
                findings = tuple(v for sheet in report.sheets for v in sheet.violations)
                assert any(v.type == "pin_not_connected" for v in findings)
                assert any(v.type == "power_pin_not_driven" for v in findings)
                assert not any(v.type == "lib_symbol_issues" for v in findings)
                assert any(v.items and v.items[0].uuid for v in findings)
                assert all(
                    isinstance(i.position.x, float) for v in findings for i in v.items
                )
                assert (
                    report.snapshot.project.documents[0].sha256
                    == hashlib.sha256(schematic.to_bytes()).hexdigest()
                )
                assert report.snapshot.project.documents[0].is_modified
                assert (
                    report.snapshot.symbol_table_sha256
                    == baseline.snapshot.symbol_table_sha256
                )
                assert project.is_modified
                for path, (raw, inode) in original.items():
                    assert path.read_bytes() == raw and path.stat().st_ino == inode
                try:
                    schematic.erc(kicad_cli=args.kicad_cli)
                except UnsupportedSchematicOperationError:
                    pass
                else:
                    raise AssertionError("Document-only scope was not rejected")
                print(
                    f"Native ERC passed: KiCad {report.kicad_version}, {len(findings)} preserved findings, repeated DAG/common-CWD URI control, typed items, locked/read-only pending snapshot."
                )
            finally:
                root.chmod(0o755)
                for path in original:
                    path.chmod(0o644)


if __name__ == "__main__":
    main()
