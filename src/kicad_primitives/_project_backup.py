"""Bounded explicit-save ZIP snapshots; no scheduler, Git, or transactions."""

from __future__ import annotations

import io
import os
import re
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from . import _symbol_persist
from .projects import ProjectBackupError

if TYPE_CHECKING:
    from .projects import Project

_EXTENSIONS = frozenset(
    {
        ".kicad_pro",
        ".kicad_prl",
        ".kicad_sch",
        ".kicad_sym",
        ".kicad_pcb",
        ".kicad_mod",
        ".kicad_dru",
        ".kicad_wks",
        ".kicad_jobset",
        ".json",
        ".wbk",
    }
)
_BARE_NAMES = frozenset({"fp-lib-table", "sym-lib-table", "design-block-lib-table"})


@dataclass(frozen=True)
class _Member:
    path: Path
    name: str
    raw: bytes
    output: bytes
    info: os.stat_result


@dataclass(frozen=True)
class _Snapshot:
    members: tuple[_Member, ...]
    archive: bytes


def _safe_name(name: str) -> None:
    parts = PurePosixPath(name).parts
    normalized = PurePosixPath(name).as_posix()
    reserved = {"con", "prn", "aux", "nul"} | {
        f"{prefix}{index}" for prefix in ("com", "lpt") for index in range(1, 10)
    }
    if (
        not parts
        or PurePosixPath(name).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or name not in {normalized, normalized + "/"}
        or any(ord(c) < 32 or c in '\\:<>"|?*' for c in name)
        or any(
            part.endswith((".", " ")) or part.split(".")[0].casefold() in reserved
            for part in parts
        )
    ):
        raise ProjectBackupError(f"Unsafe ZIP member name: {name!r}")


def _safe_path(project: Project, path: Path) -> None:
    if not path.is_relative_to(project.directory) or path.resolve() != path:
        raise ProjectBackupError(
            f"Snapshot requires contained non-symlink paths: {path}"
        )


def _read_member(project: Project, path: Path) -> tuple[bytes, os.stat_result]:
    _safe_path(project, path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ProjectBackupError(
            f"Snapshot requires a regular singly linked member: {path}"
        )
    if not stat.S_IMODE(info.st_mode) & 0o444 or not os.access(path, os.R_OK):
        raise PermissionError(f"Snapshot member is not readable: {path}")
    raw = path.read_bytes()
    if _symbol_persist._file_version(info) != _symbol_persist._file_version(
        path.lstat()
    ):
        raise ProjectBackupError(f"Snapshot member changed during read: {path}")
    return raw, info


def _inventory(project: Project) -> tuple[Path, ...]:
    result: list[Path] = []
    history = project.directory / f"{project.base_name}-backups"

    def visit(directory: Path) -> None:
        _safe_path(project, directory)
        info = directory.lstat()
        if (
            not stat.S_IMODE(info.st_mode) & 0o444
            or not stat.S_IMODE(info.st_mode) & 0o111
        ):
            raise PermissionError(f"Snapshot directory is not readable: {directory}")
        for path in sorted(directory.iterdir()):
            if path.name.startswith(".") or path == history:
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ProjectBackupError(f"Snapshot cannot follow a link: {path}")
            if stat.S_ISDIR(info.st_mode):
                visit(path)
            elif path.suffix.lower() in _EXTENSIONS or path.name in _BARE_NAMES:
                _safe_name(path.relative_to(project.directory).as_posix())
                result.append(path)

    visit(project.directory)
    return tuple(result)


def _history_directory(project: Project, *, create: bool = False) -> Path:
    directory = project.directory / f"{project.base_name}-backups"
    _safe_path(project, directory)
    if directory.exists():
        if not directory.is_dir():
            raise ProjectBackupError(
                f"Backup destination is not a directory: {directory}"
            )
    else:
        _symbol_persist._check_new_destination(
            directory, unsupported_error=ProjectBackupError
        )
        if create:
            directory.mkdir()
    parent = directory if directory.exists() else directory.parent
    mode = stat.S_IMODE(parent.stat().st_mode)
    if not mode & 0o222 or not mode & 0o111 or not os.access(parent, os.W_OK | os.X_OK):
        raise PermissionError(f"Backup destination is not writable: {parent}")
    return directory


def _managed_archives(
    project: Project, directory: Path
) -> tuple[tuple[Path, os.stat_result], ...]:
    if not directory.exists():
        return ()
    pattern = re.compile(
        rf"{re.escape(project.base_name)}-(\d{{4}}-\d{{2}}-\d{{2}}_\d{{6}})(?:-(\d{{3,}}))?\.zip"
    )
    result: list[tuple[Path, os.stat_result]] = []
    for path in sorted(directory.iterdir()):
        if not pattern.fullmatch(path.name):
            continue
        _safe_path(project, path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ProjectBackupError(f"Unsafe managed archive: {path}")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or project.project_file.name not in names:
                raise ProjectBackupError(
                    f"Unrecognized managed archive contents: {path}"
                )
            for name in names:
                _safe_name(name)
        if _symbol_persist._file_version(info) != _symbol_persist._file_version(
            path.lstat()
        ):
            raise ProjectBackupError(
                f"Managed archive changed during inspection: {path}"
            )
        result.append((path, info))

    def chronology(item: tuple[Path, os.stat_result]) -> tuple[str, int]:
        match = pattern.fullmatch(item[0].name)
        assert match is not None
        return match.group(1), int(match.group(2) or "0")

    return tuple(sorted(result, key=chronology))


def prepare(
    project: Project, outputs: Mapping[Path, bytes], required: tuple[Path, ...]
) -> _Snapshot:
    """Freeze every included member and validate a complete post-save ZIP."""
    directory = _history_directory(project)
    _managed_archives(project, directory)
    paths = _inventory(project)
    if not set(required).issubset(paths):
        raise ProjectBackupError(
            "Required owned files were excluded from the snapshot inventory"
        )
    members: list[_Member] = []
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            raw, info = _read_member(project, path)
            name = path.relative_to(project.directory).as_posix()
            output = outputs.get(path, raw)
            members.append(_Member(path, name, raw, output, info))
            archive.writestr(name, output)
    snapshot = _Snapshot(tuple(members), stream.getvalue())
    with zipfile.ZipFile(io.BytesIO(snapshot.archive)) as archive:
        if archive.testzip() is not None or archive.namelist() != [
            m.name for m in members
        ]:
            raise ProjectBackupError(
                "ZIP staging did not preserve its complete member inventory"
            )
        for member in members:
            if archive.read(member.name) != member.output:
                raise ProjectBackupError(
                    "ZIP staging changed a member's requested bytes"
                )
    return snapshot


def check_fresh(
    project: Project, snapshot: _Snapshot, written: Mapping[Path, os.stat_result]
) -> None:
    """Check inventory and exact input/output versions without refreshing the snapshot."""
    if _inventory(project) != tuple(m.path for m in snapshot.members):
        raise ProjectBackupError("Project snapshot membership changed during save")
    for member in snapshot.members:
        raw, info = _read_member(project, member.path)
        expected = written.get(member.path)
        if expected is None:
            matches = _symbol_persist._file_version(
                info
            ) == _symbol_persist._file_version(member.info)
        else:
            matches = (
                info.st_dev,
                info.st_ino,
                info.st_mode,
                info.st_size,
                info.st_mtime_ns,
            ) == (
                expected.st_dev,
                expected.st_ino,
                expected.st_mode,
                expected.st_size,
                expected.st_mtime_ns,
            )
        if not matches or raw != (
            member.output if expected is not None else member.raw
        ):
            raise ProjectBackupError(
                f"Snapshot member changed during save: {member.path}"
            )


def publish(project: Project, snapshot: _Snapshot) -> Path:
    """Publish one complete unique archive, then prune old recognized snapshots."""
    directory = _history_directory(project, create=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    index = 0
    while True:
        suffix = "" if index == 0 else f"-{index:03d}"
        path = directory / f"{project.base_name}-{stamp}{suffix}.zip"
        try:
            installed = _symbol_persist.save_new_source(
                path, snapshot.archive, unsupported_error=ProjectBackupError
            )
            break
        except FileExistsError:
            if not path.exists() and not path.is_symlink():
                raise
            index += 1
    info = _symbol_persist._check_baseline(
        path,
        snapshot.archive,
        conflict_error=ProjectBackupError,
        unsupported_error=ProjectBackupError,
        label="Published Project backup",
    )
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
        installed.st_dev,
        installed.st_ino,
        installed.st_size,
        installed.st_mtime_ns,
    ):
        raise ProjectBackupError("Published archive changed during save")
    archives = _managed_archives(project, directory)
    own_index = next(
        (index for index, (candidate, _) in enumerate(archives) if candidate == path),
        None,
    )
    if own_index is None:
        raise ProjectBackupError("Published archive disappeared before retention")
    limit = project.backup_size_limit_bytes
    total = sum(info.st_size for _, info in archives)
    for old, before in archives[:own_index]:
        if limit == 0 or total <= limit:
            break
        current = old.lstat()
        if _symbol_persist._file_version(current) != _symbol_persist._file_version(
            before
        ):
            raise ProjectBackupError(f"Managed archive changed before pruning: {old}")
        old.unlink()
        total -= before.st_size
    return path
