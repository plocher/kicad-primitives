"""Optimistic single-file persistence, not a lock/session or transaction system."""

import os
import stat
import tempfile
from pathlib import Path

from ._symbol_types import FileConflictError, UnsupportedOperationError


def _check_baseline(path: Path, baseline: bytes) -> os.stat_result:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise UnsupportedOperationError(
                "Save requires a regular, non-symlink, singly linked file"
            )
        if path.read_bytes() != baseline:
            raise FileConflictError(f"Library changed on disk: {path}")
    except FileNotFoundError as exc:
        raise FileConflictError(f"Library no longer exists: {path}") from exc
    return info


def save_source(path: Path, baseline: bytes, output: bytes) -> None:
    info = _check_baseline(path, baseline)
    if output == baseline:
        return
    if not stat.S_IMODE(info.st_mode) & 0o222:
        raise PermissionError(f"Library has no write permission bits: {path}")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(output)
            stream.flush()
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            os.fsync(stream.fileno())
        final_info = _check_baseline(path, baseline)
        if (final_info.st_dev, final_info.st_ino, final_info.st_mode) != (
            info.st_dev,
            info.st_ino,
            info.st_mode,
        ):
            raise FileConflictError(
                f"Library identity or permissions changed during save: {path}"
            )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
