"""Opt-in native KiCad electrical/save gate; all writes are disposable copies."""

import argparse
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives.netlist import obtain_netlist
from kicad_primitives.projects import Project


def main() -> None:
    """Exercise current public editing and persistence against real KiCad."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-cli", type=Path)
    args = parser.parse_args()
    fixture = Path(__file__).parent / "fixtures/schematics/attribute-edit"
    with TemporaryDirectory(prefix="kp-native-schematic-") as temp:
        root = Path(temp)
        for path in fixture.glob("*.kicad_*"):
            shutil.copyfile(path, root / path.name)
        project = Project.open(root)
        schematic = project.schematic()
        original = schematic.to_bytes()
        before = obtain_netlist(schematic.path, kicad_cli=args.kicad_cli)
        symbol = schematic.symbol("R3")
        symbol.set_attribute("Value", "22K")
        symbol.set_attribute("MPN", 'résistor "A"\\B')
        assert schematic.path.read_bytes() == original
        project.save(kicad_cli=args.kicad_cli)
        after = obtain_netlist(schematic.path, kicad_cli=args.kicad_cli)
        assert after.component("R3").value == "22K"
        assert after.component("R3").fields["MPN"] == 'résistor "A"\\B'
        expected = sorted(
            (net.name, sorted((node.reference, node.pin) for node in net.nodes))
            for net in before.nets
        )
        observed = sorted(
            (net.name, sorted((node.reference, node.pin) for node in net.nodes))
            for net in after.nets
        )
        assert expected == observed
        assert len(after.nets) == 6
        assert all(len(net.nodes) == 1 for net in after.nets)
        assert not project.is_modified
        inode = schematic.path.stat().st_ino
        schematic.save(kicad_cli=args.kicad_cli)
        assert schematic.path.stat().st_ino == inode
        print(
            "Native KiCad gate passed: Value, inserted escaped Unicode MPN, six singleton nets, explicit save, exact no-op."
        )


if __name__ == "__main__":
    main()
