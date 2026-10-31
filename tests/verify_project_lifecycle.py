"""Opt-in native Project save/close/backup checks on disposable data only (ADR 0011)."""

import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives._kicad_cli import resolve_kicad_cli
from kicad_primitives.projects import Project, ProjectLifecycleError

# Independently authored empty native data header, not KiCad implementation code.
# KiCad 10.0.1 SEXPR_BOARD_FILE_VERSION=20260206. The 79-byte native QA data at
# qa/data/eeschema/issue23403/issue23403.kicad_pcb establishes this minimal shape.
_EMPTY_BOARD = b'(kicad_pcb (version 20260206) (generator "pcbnew") (generator_version "10.0")\n)\n'


def main() -> None:
    """Prove clean close, a client netlist check, a plain save, and an exact backup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kicad-cli", type=Path)
    args = parser.parse_args()
    cli = resolve_kicad_cli(args.kicad_cli)
    fixture = Path(__file__).parent / "fixtures/schematics/attribute-edit"
    with TemporaryDirectory(prefix="kp-native-project-") as temporary:
        root = Path(temporary).resolve()
        for path in fixture.glob("*.kicad_*"):
            shutil.copyfile(path, root / path.name)
        pro = root / "cpNode-IOX.kicad_pro"
        sch = pro.with_suffix(".kicad_sch")
        pcb = pro.with_suffix(".kicad_pcb")
        pcb.write_bytes(_EMPTY_BOARD)
        subprocess.run(
            [
                str(cli),
                "pcb",
                "export",
                "pos",
                "--format",
                "csv",
                "--output",
                str(root / "native-pos.csv"),
                str(pcb),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        # Native PCB opening creates .kicad_prl in this disposable directory.
        prl = pro.with_suffix(".kicad_prl")
        assert prl.is_file()
        originals = {p: (p.read_bytes(), p.stat().st_ino) for p in (pro, sch, pcb, prl)}
        probe = Project.open(pro)
        probe.schematic().files[0].symbol("R3")
        probe.close()
        assert {p: (p.read_bytes(), p.stat().st_ino) for p in originals} == originals
        project = Project.open(pro, on_close="raise")
        archive_path = project.backup(project.backup_directory)
        with zipfile.ZipFile(archive_path) as archive:
            assert set(archive.namelist()) == {pro.name, sch.name, pcb.name, prl.name}
            for path, (raw, _inode) in originals.items():
                assert archive.read(path.name) == raw
        before = project.netlist(kicad_cli=cli)
        schematic = project.schematic().files[0]
        placed = schematic.symbol("R3")
        placed.set_attribute("Value", "22K")
        pending = schematic.to_bytes()
        assert project.netlist(kicad_cli=cli) == before
        lock = sch.with_name(f"~{sch.name}.lck")
        lock.write_bytes(b"controlled native peer lock")
        assert project.is_locked  # A query only; the client decides.
        lock.unlink()
        project.save()
        assert sch.read_bytes() == pending
        for path in (pro, pcb, prl):
            assert (path.read_bytes(), path.stat().st_ino) == originals[path]
        assert project.schematic().files[0] is schematic
        assert schematic.symbol("R3") is placed
        project.close()
        try:
            placed.set_attribute("Value", "late")
        except ProjectLifecycleError:
            pass
        else:
            raise AssertionError("An exited Project retained an editable placement")
        second = Project.open(pro, on_close="discard")
        second.schematic().files[0].symbol("R3").set_attribute("Value", "33K")
        second.close()
        assert sch.read_bytes() == pending
        print(
            "Native Project lifecycle passed: clean close without writes, exact backup "
            "of disk state, equal netlist after an attribute edit, plain save of the "
            "changed sheet only, lock as a query, stable/dead handles, discard close."
        )


if __name__ == "__main__":
    main()
