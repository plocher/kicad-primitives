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
        schematic = project.schematic().files[0]
        original = schematic.to_bytes()
        before = obtain_netlist(schematic.path, kicad_cli=args.kicad_cli)
        project_before = project.netlist(kicad_cli=args.kicad_cli)
        symbol = schematic.symbol("R3")
        symbol.set_attribute("Value", "22K")
        symbol.set_attribute("MPN", 'résistor "A"\\B')
        # jBOM alias normalization: set canonical Power, delete alias W.
        symbol.set_attribute("Power", symbol.attribute("W").value)
        symbol.delete_attribute("W")
        assert b'"W" "100mW"' in original
        assert schematic.path.read_bytes() == original
        pending = project.netlist(kicad_cli=args.kicad_cli)
        assert pending.component("R3").value == "22K"
        assert pending.component("R3").fields["Power"] == "100mW"
        assert "W" not in pending.component("R3").fields
        assert pending.provenance is not None
        assert [d.is_modified for d in pending.provenance.documents] == [True]
        assert schematic.path.read_bytes() == original and project.is_modified
        # ADR 0011: the client checks connectivity; save itself runs no KiCad.
        assert pending == project_before
        project.save()
        after = obtain_netlist(schematic.path, kicad_cli=args.kicad_cli)
        assert after.component("R3").value == "22K"
        assert after.component("R3").fields["MPN"] == 'résistor "A"\\B'
        assert after.component("R3").fields["Power"] == "100mW"
        assert "W" not in after.component("R3").fields
        assert before.component("R3").fields["W"] == "100mW"
        expected = sorted(
            (net.name, sorted((node.reference, node.pin) for node in net.nodes))
            for net in before.nets
        )
        observed = sorted(
            (net.name, sorted((node.reference, node.pin) for node in net.nodes))
            for net in after.nets
        )
        assert expected == observed
        assert expected == sorted(
            (net.name, sorted((node.reference, node.pin) for node in net.nodes))
            for net in pending.nets
        )
        assert len(after.nets) == 6
        assert all(len(net.nodes) == 1 for net in after.nets)
        assert not project.is_modified
        inode = schematic.path.stat().st_ino
        schematic.save()
        assert schematic.path.stat().st_ino == inode
        print(
            "Native KiCad gate passed: Value, inserted escaped Unicode MPN, "
            "W->Power alias deletion, pending Project.netlist equal to before, "
            "six singleton nets, explicit save, exact no-op."
        )


if __name__ == "__main__":
    main()
