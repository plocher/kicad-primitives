"""Native save-as proof for the documented current-format derived hierarchy."""

import argparse
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from lossless_sexpr import ListNode, parse

from kicad_primitives._kicad_cli import resolve_kicad_cli
from kicad_primitives.netlist import Netlist, export_netlist
from kicad_primitives.projects import Project


def _pin_inventory(path: Path) -> tuple[object, ...]:
    root = parse(path.read_bytes().decode("utf-8")).roots()[0]
    assert isinstance(root, ListNode)
    parts = root.child_lists("libparts")[0]
    result: list[object] = []
    for part in parts.child_lists("libpart"):
        library = part.child_lists("lib")[0].atom(1)
        name = part.child_lists("part")[0].atom(1)
        assert library is not None and name is not None
        pins = tuple(
            tuple(
                pin.child_lists(key)[0].atom(1).value for key in ("num", "name", "type")
            )
            for pin in part.child_lists("pins")[0].child_lists("pin")
        )
        result.append((library.value, name.value, pins))
    return tuple(result)


def main() -> None:
    """Check explicit identity deltas, full named endpoints/pins, originals, and handles."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-cli", type=Path)
    args = parser.parse_args()
    cli = resolve_kicad_cli(args.kicad_cli)
    fixture = Path(__file__).parent / "fixtures/projects/rename-native"
    with TemporaryDirectory(prefix="kp-native-save-as-") as temporary:
        root = Path(temporary).resolve()
        source = root / "source"
        source.mkdir()
        for path in fixture.glob("*.kicad_*"):
            shutil.copyfile(path, source / path.name)
        originals = {
            path: (path.read_bytes(), path.stat().st_ino) for path in source.iterdir()
        }
        pro = source / "issue23403.kicad_pro"
        sch = pro.with_suffix(".kicad_sch")
        child_path = source / "shared1.kicad_sch"
        pcb = pro.with_suffix(".kicad_pcb")
        before_path = export_netlist(sch, root / "before.net", kicad_cli=cli)
        before = Netlist.open(before_path)
        endpoints = tuple(
            sorted(
                (
                    net.name,
                    tuple(
                        sorted(
                            (n.reference, n.pin, n.pinfunction, n.pintype)
                            for n in net.nodes
                        )
                    ),
                )
                for net in before.nets
            )
        )
        assert {(n.reference, n.pin) for net in before.nets for n in net.nodes} == {
            ("C0", "1"),
            ("C0", "2"),
            ("C1", "1"),
            ("C1", "2"),
        }
        project = Project.open(pro)
        document = project.schematic()
        child = project.schematic(child_path)
        placed = document.symbol("C0")
        cache_id = child.symbol("C1").lib_id
        embedded = child.embedded_symbol(cache_id)
        destination = root / "clone"
        project.save_as(destination, "Renamed", kicad_cli=cli)
        expected_root = originals[sch][0].replace(
            b'(project "issue23403"', b'(project "Renamed"'
        )
        expected_child = originals[child_path][0].replace(
            b'(project "issue23403"', b'(project "Renamed"'
        )
        expected_pcb = originals[pcb][0].replace(
            b'(sheetfile "issue23403.kicad_sch")', b'(sheetfile "Renamed.kicad_sch")'
        )
        assert project.schematic() is document and document.symbol("C0") is placed
        assert project.schematic(destination / child_path.name) is child
        assert child.embedded_symbol(cache_id) is embedded
        assert placed.path == destination / "Renamed.kicad_sch"
        assert (
            document.to_bytes() == expected_root and child.to_bytes() == expected_child
        )
        assert (
            project.pcb_file is not None
            and project.pcb_file.read_bytes() == expected_pcb
        )
        expected_pro = (
            originals[pro][0]
            .replace(
                b'"filename": "issue23403.kicad_pro"',
                b'"filename": "Renamed.kicad_pro"',
            )
            .replace(
                b'"filename": "issue23403.kicad_sch"',
                b'"filename": "Renamed.kicad_sch"',
            )
        )
        assert project.project_file.read_bytes() == expected_pro
        assert json.loads(expected_pro)["owner_note"] == "issue23403 literal remains"
        assert b'(project "Foreign"' in child.to_bytes()
        after_path = export_netlist(
            project.schematic_file, root / "after.net", kicad_cli=cli
        )
        after = Netlist.open(after_path)
        assert (
            tuple(
                sorted(
                    (
                        net.name,
                        tuple(
                            sorted(
                                (n.reference, n.pin, n.pinfunction, n.pintype)
                                for n in net.nodes
                            )
                        ),
                    )
                    for net in after.nets
                )
            )
            == endpoints
        )
        assert tuple(
            sorted(
                (c.reference, c.value, c.lib, c.part, c.sheetpath)
                for c in before.components.values()
            )
        ) == tuple(
            sorted(
                (c.reference, c.value, c.lib, c.part, c.sheetpath)
                for c in after.components.values()
            )
        )
        assert _pin_inventory(before_path) == _pin_inventory(after_path)
        # Load a copy of the published board; native .prl side effects stay out of the clone.
        board_check = root / "pcb-check"
        board_check.mkdir()
        board_path = board_check / "Renamed.kicad_pcb"
        board_path.write_bytes(expected_pcb)
        subprocess.run(
            [
                str(cli),
                "pcb",
                "export",
                "pos",
                "--format",
                "csv",
                "--output",
                str(board_check / "native-pos.csv"),
                str(board_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert board_path.read_bytes() == expected_pcb
        archives = tuple((destination / "Renamed-backups").glob("*.zip"))
        assert len(archives) == 1
        with zipfile.ZipFile(archives[0]) as archive:
            assert archive.read("Renamed.kicad_sch") == expected_root
            assert archive.read("shared1.kicad_sch") == expected_child
            assert archive.read("Renamed.kicad_pcb") == expected_pcb
            assert archive.read("Renamed.kicad_pro") == expected_pro
        assert {p: (p.read_bytes(), p.stat().st_ino) for p in originals} == originals
        assert not project.is_modified
        project.close()
        print(
            "Native Project save-as passed: exact root/child/JSON/PCB identity deltas, foreign groups, stable handles, named endpoints/full pins, original bytes/inodes, destination ZIP."
        )


if __name__ == "__main__":
    main()
