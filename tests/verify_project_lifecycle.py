"""Opt-in native Project save/ZIP/terminal-exit checks on disposable data only."""

import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from kicad_primitives._kicad_cli import resolve_kicad_cli
from kicad_primitives.projects import (
    Project,
    ProjectLifecycleError,
    ProjectWriteBlockedError,
)

# Independently authored empty native data header, not KiCad implementation code.
# KiCad 10.0.1 SEXPR_BOARD_FILE_VERSION=20260206. The 79-byte native QA data at
# qa/data/eeschema/issue23403/issue23403.kicad_pcb establishes this minimal shape.
_EMPTY_BOARD = b'(kicad_pcb (version 20260206) (generator "pcbnew") (generator_version "10.0")\n)\n'


def main() -> None:
    """Prove clean close, explicit saves, and exact post-save snapshot members natively."""
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
        originals = {p: (p.read_bytes(), p.stat().st_ino) for p in (pro, sch, pcb)}
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
        assert {p: (p.read_bytes(), p.stat().st_ino) for p in originals} == originals
        # Native PCB opening creates .kicad_prl in this disposable directory.
        prl = pro.with_suffix(".kicad_prl")
        assert prl.is_file()
        originals[prl] = (prl.read_bytes(), prl.stat().st_ino)
        probe = Project.open(pro)
        probe.schematic().symbol("R3")
        probe.close(kicad_cli=root / "must-not-run")
        assert probe.is_closed
        assert {p: (p.read_bytes(), p.stat().st_ino) for p in originals} == originals
        assert not (root / "cpNode-IOX-backups").exists()
        project = Project.open(pro)
        schematic = project.schematic()
        placed = schematic.symbol("R3")
        placed.set_attribute("Value", "22K")
        pending = schematic.to_bytes()
        for path in (pro, sch, pcb):
            lock = path.with_name(f"~{path.name}.lck")
            lock.write_bytes(b"controlled native peer lock")
            try:
                assert project.is_locked
                assert schematic.to_bytes() == pending
                try:
                    project.save(kicad_cli=root / "must-not-run")
                except ProjectWriteBlockedError:
                    pass
                else:
                    raise AssertionError(f"Native peer lock did not block save: {lock}")
                assert {
                    p: (p.read_bytes(), p.stat().st_ino) for p in originals
                } == originals
                assert not (root / "cpNode-IOX-backups").exists()
            finally:
                lock.unlink()
        project.save(kicad_cli=cli)
        archives = tuple((root / "cpNode-IOX-backups").glob("cpNode-IOX-*.zip"))
        assert len(archives) == 1
        with zipfile.ZipFile(archives[0]) as archive:
            assert set(archive.namelist()) == {pro.name, sch.name, pcb.name, prl.name}
            assert archive.read(pro.name) == originals[pro][0]
            assert archive.read(sch.name) == pending
            assert archive.read(pcb.name) == _EMPTY_BOARD
            assert archive.read(prl.name) == originals[prl][0]
        assert sch.read_bytes() == pending
        assert project.schematic() is schematic
        assert schematic.symbol("R3") is placed
        for path in (pro, pcb):
            assert (path.read_bytes(), path.stat().st_ino) == originals[path]
        project.close()
        try:
            placed.set_attribute("Value", "late")
        except ProjectLifecycleError:
            pass
        else:
            raise AssertionError("An exited Project retained an editable placement")
        second = Project.open(pro)
        second.schematic().symbol("R3").set_attribute("Value", "33K")
        saved = {p: (p.read_bytes(), p.stat().st_ino) for p in originals}
        second.discard()
        second.close()
        assert {p: (p.read_bytes(), p.stat().st_ino) for p in originals} == saved
        assert len(tuple(archives[0].parent.glob("*.zip"))) == 1
        clean = Project.open(pro)
        clean.save(kicad_cli=root / "not-needed")
        assert {p: (p.read_bytes(), p.stat().st_ino) for p in originals} == saved
        assert len(tuple(archives[0].parent.glob("*.zip"))) == 2
        clean.close()
        print(
            "Native Project lifecycle passed: clean close without writes, verified schematic "
            "save, native PCB acceptance, native peer-lock controls, exact full-file-set ZIP, "
            "unchanged JSON/PCB/no-op inodes, stable/dead handles, terminal discard."
        )


if __name__ == "__main__":
    main()
