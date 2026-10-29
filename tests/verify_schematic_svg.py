"""Opt-in native KiCad gate for Project.export_svgs; all writes are disposable copies."""

import argparse
import shutil
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.projects import Project

TOKEN = "KP_PENDING_SVG_VALUE"


def main() -> None:
    """Export a pending two-sheet hierarchy to SVG with real KiCad."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-cli", type=Path)
    args = parser.parse_args()
    fixture = Path(__file__).parent / "fixtures/projects/rename-native"
    with TemporaryDirectory(prefix="kp-native-svg-") as temp:
        base = Path(temp).resolve()
        root = base / "project"
        root.mkdir()
        for path in fixture.glob("*.kicad_*"):
            shutil.copyfile(path, root / path.name)
        project = Project.open(root)
        schematic, child = project.schematics()
        originals = {p: p.read_bytes() for p in (schematic.path, child.path)}
        reference = schematic.symbols[0].reference
        schematic.symbol(reference).set_attribute("Value", TOKEN)
        output = base / "svg"
        result = project.export_svgs(output, kicad_cli=args.kicad_cli)
        mapping = {f.path.name: (f.sheet_path, f.source_path) for f in result.files}
        assert mapping == {
            "issue23403.svg": ("/", schematic.path),
            "issue23403-shared1.svg": ("/shared1/", child.path),
        }, mapping
        assert sorted(p.name for p in output.iterdir()) == sorted(mapping)
        assert TOKEN in (output / "issue23403.svg").read_text(encoding="utf-8")
        assert TOKEN not in (output / "issue23403-shared1.svg").read_text(
            encoding="utf-8"
        )
        assert all(p.read_bytes() == raw for p, raw in originals.items())
        assert project.is_modified
        assert [d.is_modified for d in result.snapshot.documents] == [True, False]
        try:
            project.export_svgs(output, kicad_cli=args.kicad_cli)
        except FileExistsError:
            pass
        else:
            raise AssertionError("existing output directory was reused")

        # Non-ASCII and separator sheet names: KiCad writes the page itself.
        renamed = base / "renamed"
        renamed.mkdir()
        for path in fixture.glob("*.kicad_*"):
            shutil.copyfile(path, renamed / path.name)
        root_file = renamed / "issue23403.kicad_sch"
        source = root_file.read_bytes()
        assert source.count(b'"Sheetname" "shared1"') == 1
        root_file.write_bytes(
            source.replace(b'"Sheetname" "shared1"', '"Sheetname" "Ünï/x"'.encode())
        )
        renamed_project = Project.open(renamed)
        _root, renamed_child = renamed_project.schematics()
        result = renamed_project.export_svgs(
            base / "svg-renamed", kicad_cli=args.kicad_cli
        )
        mapping = {
            unicodedata.normalize("NFC", f.path.name): (f.sheet_path, f.source_path)
            for f in result.files
        }
        assert mapping["issue23403-Ünï_x.svg"] == ("/Ünï/x/", renamed_child.path), (
            mapping
        )
        assert len(mapping) == 2, mapping
        print(
            "Native SVG export passed: two-sheet hierarchy mapping, pending Value "
            "rendered, sources unchanged, existing output refused, non-ASCII and "
            "'/' sheet name mapped."
        )


if __name__ == "__main__":
    main()
