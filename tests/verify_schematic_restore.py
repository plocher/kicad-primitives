"""Opt-in real KiCad restore proof using independently authored expected pin types."""

import argparse
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.netlist import obtain_netlist
from kicad_primitives.projects import Project
from kicad_primitives.symbols import SymbolLibrary


def main() -> None:
    """Prove intended output/input-to-passive corrections without source replay."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-cli", type=Path)
    args = parser.parse_args()
    fixtures = Path(__file__).parent / "fixtures/schematics"
    with TemporaryDirectory(prefix="kp-native-restore-") as temp:
        root = Path(temp)
        for path in (fixtures / "embedded-restore").glob("*.kicad_*"):
            shutil.copyfile(path, root / path.name)
        project = Project.open(root / "cpNode-IOX.kicad_pro")
        schematic = project.schematic()
        parent = SymbolLibrary.open(root / "parent.kicad_sym")
        original = schematic.to_bytes()
        before = obtain_netlist(schematic.path, kicad_cli=args.kicad_cli)
        expected_before = {
            (reference, number): typ
            for reference in ("R3", "R9", "R12")
            for number, typ in (("1", "output"), ("2", "input"))
        }
        assert {
            (n.reference, n.pin): n.pintype for net in before.nets for n in net.nodes
        } == expected_before
        handle = schematic.embedded_symbol("SPCoast:R")
        placed = schematic.symbol("R3")
        handle.restore_from(parent, "R")
        expected_source = (
            fixtures / "attribute-edit/cpNode-IOX.kicad_sch"
        ).read_bytes()
        assert schematic.to_bytes() == expected_source
        assert schematic.path.read_bytes() == original
        parent.set_pin("R", 1, 0, "1", electrical_type="input")
        project.save(kicad_cli=args.kicad_cli)
        after = obtain_netlist(schematic.path, kicad_cli=args.kicad_cli)
        expected_after = {key: "passive" for key in expected_before}
        assert {
            (n.reference, n.pin): n.pintype for net in after.nets for n in net.nodes
        } == expected_after
        assert sorted(
            (net.name, tuple((n.reference, n.pin, n.pinfunction) for n in net.nodes))
            for net in before.nets
        ) == sorted(
            (net.name, tuple((n.reference, n.pin, n.pinfunction) for n in net.nodes))
            for net in after.nets
        )
        assert schematic.path.read_bytes() == expected_source
        assert schematic.symbol("R3") is placed
        assert schematic.embedded_symbol("SPCoast:R") is handle
        assert not project.is_modified
        inode = schematic.path.stat().st_ino
        schematic.save(kicad_cli=args.kicad_cli)
        assert schematic.path.stat().st_ino == inode
        print(
            "Native restore passed: exact cache/complement, three placements, six output/input-to-passive pin effects, parent capture, explicit save."
        )


if __name__ == "__main__":
    main()
