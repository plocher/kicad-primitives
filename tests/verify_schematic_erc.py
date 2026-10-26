"""Opt-in real KiCad ERC report/context/read-only pending-snapshot contract."""

import argparse
import hashlib
import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.projects import Project
from kicad_primitives.schematics import ErcReport, UnsupportedSchematicOperationError


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
            schematic = project.schematic()
            baseline = project.erc(kicad_cli=args.kicad_cli)
            assert isinstance(baseline, ErcReport)
            schematic.symbol("R3").set_attribute("Value", "22K")
            original = {
                p: (p.read_bytes(), p.stat().st_ino)
                for p in root.iterdir()
                if p.is_file()
            }
            (root / "cpNode-IOX.lck").touch()
            for path in original:
                path.chmod(0o444)
            root.chmod(0o555)
            try:
                report = project.erc(kicad_cli=args.kicad_cli)
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
                    report.snapshot.documents[0].sha256
                    == hashlib.sha256(schematic.to_bytes()).hexdigest()
                )
                assert report.snapshot.documents[0].is_modified
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
                    f"Native ERC passed: KiCad {report.kicad_version}, {len(findings)} preserved findings, original library URIs, typed items, locked/read-only pending snapshot."
                )
            finally:
                root.chmod(0o755)
                for path in original:
                    path.chmod(0o644)


if __name__ == "__main__":
    main()
