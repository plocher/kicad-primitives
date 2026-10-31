"""Read-only contained file facts for original-safe Project relocation."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from . import _symbol_persist
from .projects import InvalidProjectError
from .schematics import SchematicConflictError


@dataclass(frozen=True)
class _Input:
    path: Path
    raw: bytes
    info: os.stat_result


def read(
    root: Path, path: Path, *, baseline: _symbol_persist.Baseline | None = None
) -> _Input:
    """Capture one contained regular source without requiring overwrite permissions."""
    if not path.is_relative_to(root) or path.resolve() != path:
        raise InvalidProjectError(
            f"Relocation requires contained non-symlink sources: {path}"
        )
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise InvalidProjectError(f"Relocation source is not a regular file: {path}")
    if not stat.S_IMODE(info.st_mode) & 0o444 or not os.access(path, os.R_OK):
        raise PermissionError(f"Relocation source is unreadable: {path}")
    raw = path.read_bytes()
    if _symbol_persist._file_version(info) != _symbol_persist._file_version(
        path.lstat()
    ):
        raise SchematicConflictError(f"Relocation source changed during read: {path}")
    if baseline is not None and not _symbol_persist._matches(baseline, raw):
        raise SchematicConflictError(f"Relocation source changed since capture: {path}")
    return _Input(path, raw, info)


def check(root: Path, inputs: tuple[_Input, ...]) -> None:
    """Recheck exact source versions without refreshing or overwriting captured facts."""
    for captured in inputs:
        current = read(root, captured.path, baseline=captured.raw)
        if _symbol_persist._file_version(current.info) != _symbol_persist._file_version(
            captured.info
        ):
            raise SchematicConflictError(
                f"Relocation source identity changed: {captured.path}"
            )
