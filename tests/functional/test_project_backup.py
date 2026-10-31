"""project.backup(): archive the files on disk now (ADR 0011 D7).

No save first, no unsaved edits, no settings. Destination and size limit are
explicit. KiCad's naming conventions are constants.
"""

import os
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kicad_primitives.projects import Project, ProjectLifecycleError
from tests.functional.test_schematic_editing import SOURCE


class ProjectBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "board"
        self.root.mkdir()
        self.pro = self.root / "board.kicad_pro"
        self.pro.write_bytes(b'{"meta":{"filename":"board.kicad_pro"}}')
        self.sch = self.root / "board.kicad_sch"
        self.sch.write_bytes(SOURCE)

    def archives(self, directory: Path | None = None) -> tuple[Path, ...]:
        folder = directory or self.root / "board-backups"
        return tuple(sorted(folder.glob("board-*.zip")))

    def members(self, archive: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(archive) as opened:
            return {name: opened.read(name) for name in opened.namelist()}

    def test_backup_archives_disk_state_without_saving(self) -> None:
        project = Project.open(self.root)
        project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
        inode = self.sch.stat().st_ino
        archive = project.backup(project.backup_directory)
        self.assertEqual(archive.parent, self.root / "board-backups")
        self.assertRegex(archive.name, r"^board-\d{4}-\d{2}-\d{2}_\d{6}\.zip$")
        self.assertEqual(
            self.members(archive),
            {"board.kicad_pro": self.pro.read_bytes(), "board.kicad_sch": SOURCE},
        )
        self.assertTrue(project.is_modified)
        self.assertEqual(
            (self.sch.read_bytes(), self.sch.stat().st_ino), (SOURCE, inode)
        )

    def test_complete_allowlist_and_omissions(self) -> None:
        expected = {"board.kicad_pro": self.pro.read_bytes(), "board.kicad_sch": SOURCE}
        for extension in (
            "kicad_prl",
            "kicad_sym",
            "kicad_pcb",
            "kicad_mod",
            "kicad_dru",
            "kicad_wks",
            "kicad_jobset",
            "json",
            "wbk",
        ):
            name = f"asset.{extension}"
            (self.root / name).write_bytes(name.encode())
            expected[name] = name.encode()
        for name in ("fp-lib-table", "sym-lib-table", "design-block-lib-table"):
            (self.root / name).write_bytes(b"rows")
            expected[name] = b"rows"
        (self.root / "legit-backups").mkdir()
        (self.root / "legit-backups/asset.json").write_bytes(b"local data")
        expected["legit-backups/asset.json"] = b"local data"
        for name in (".history", ".git", ".hidden", "board-backups"):
            (self.root / name).mkdir()
            (self.root / name / "omit.json").write_bytes(b"omit")
        (self.root / "unrelated.txt").write_bytes(b"omit")
        project = Project.open(self.root)
        self.assertEqual(
            self.members(project.backup(project.backup_directory)), expected
        )
        # A destination inside the project is never archived into itself.
        (self.root / "archives").mkdir()
        (self.root / "archives/omit.json").write_bytes(b"omit")
        archive = project.backup(self.root / "archives")
        self.assertEqual(self.members(archive), expected)

    def test_destination_outside_the_project_and_created_when_missing(self) -> None:
        outside = self.root.parent / "elsewhere"
        archive = Project.open(self.root).backup(outside)
        self.assertEqual(archive.parent, outside)
        self.assertIn("board.kicad_sch", self.members(archive))
        with self.assertRaises(FileNotFoundError):
            Project.open(self.root).backup(self.root.parent / "missing/parent")

    def test_same_second_backups_never_overwrite(self) -> None:
        project = Project.open(self.root)
        with patch("kicad_primitives._project_backup.datetime") as clock:
            clock.now.return_value.strftime.return_value = "2026-10-27_010203"
            for _ in range(3):
                project.backup(project.backup_directory)
        self.assertEqual(
            {p.name for p in self.archives()},
            {
                "board-2026-10-27_010203.zip",
                "board-2026-10-27_010203-001.zip",
                "board-2026-10-27_010203-002.zip",
            },
        )

    def test_size_limit_prunes_oldest_and_keeps_the_new_archive(self) -> None:
        project = Project.open(self.root)
        with patch("kicad_primitives._project_backup.datetime") as clock:
            clock.now.return_value.strftime.return_value = "2026-10-27_010203"
            project.backup(project.backup_directory)
            size = self.archives()[0].stat().st_size
            project.backup(project.backup_directory)
            project.backup(project.backup_directory, size_limit_bytes=size * 2)
            self.assertEqual(
                {p.name for p in self.archives()},
                {"board-2026-10-27_010203-001.zip", "board-2026-10-27_010203-002.zip"},
            )
            project.backup(project.backup_directory, size_limit_bytes=1)
        self.assertEqual(
            [p.name for p in self.archives()], ["board-2026-10-27_010203-003.zip"]
        )
        unrelated = self.root / "board-backups/other-2026-10-27_010203.zip"
        unrelated.write_bytes(b"not ours")
        project.backup(project.backup_directory, size_limit_bytes=1)
        self.assertTrue(unrelated.exists())

    def test_invalid_size_limits_fail_before_writing(self) -> None:
        project = Project.open(self.root)
        for value in (0, -1, True, "100"):
            with (
                self.subTest(value=value),
                self.assertRaises(ValueError),
            ):
                project.backup(project.backup_directory, size_limit_bytes=value)  # type: ignore[arg-type]
        self.assertFalse((self.root / "board-backups").exists())

    def test_unsafe_members_fail_without_an_archive(self) -> None:
        for kind in ("unreadable", "symlink", "hardlink", "reserved", "wildcard"):
            with self.subTest(kind=kind):
                path = self.root / {
                    "reserved": "CON.json",
                    "wildcard": "bad?.json",
                }.get(kind, "asset.json")
                if kind == "symlink":
                    path.symlink_to(self.pro)
                elif kind == "hardlink":
                    os.link(self.pro, path)
                else:
                    path.write_bytes(b"asset")
                    if kind == "unreadable":
                        path.chmod(0o000)
                try:
                    project = Project.open(self.root)
                    with self.assertRaises((OSError, ValueError)):
                        project.backup(project.backup_directory)
                    self.assertFalse(self.archives())
                finally:
                    path.unlink()

    def test_closed_project_cannot_back_up(self) -> None:
        project = Project.open(self.root)
        project.discard()
        with self.assertRaises(ProjectLifecycleError):
            project.backup(self.root / "board-backups")


if __name__ == "__main__":
    unittest.main()
