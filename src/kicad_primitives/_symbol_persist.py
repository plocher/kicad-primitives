"""Optimistic single-file persistence, not a lock/session or transaction system."""

import os
import stat
import tempfile
from pathlib import Path

from ._symbol_types import FileConflictError, UnsupportedOperationError


def _check_new_destination(
    path: Path, *, unsupported_error: type[Exception] = UnsupportedOperationError
) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Destination already exists: {path}")
    for parent in (path.parent, *path.parent.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise unsupported_error(
                f"Destination requires existing non-symlink directories: {parent}"
            )
    mode = stat.S_IMODE(path.parent.stat().st_mode)
    if (
        not mode & 0o222
        or not mode & 0o111
        or not os.access(path.parent, os.W_OK | os.X_OK)
    ):
        raise PermissionError(f"Destination directory is not writable: {path.parent}")


def save_new_source(
    path: Path,
    output: bytes,
    *,
    mode: int = 0o600,
    unsupported_error: type[Exception] = UnsupportedOperationError,
) -> None:
    """Create one new file without overwrite, symlink traversal, or implicit parents."""
    path = path.absolute()
    _check_new_destination(path, unsupported_error=unsupported_error)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(output)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        _check_new_destination(path, unsupported_error=unsupported_error)
        # Linking a staged regular file is atomic and refuses a racing destination.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _check_read_baseline(
    path: Path,
    baseline: bytes,
    *,
    conflict_error: type[Exception] = FileConflictError,
    label: str = "Library",
) -> os.stat_result:
    """Check source freshness for copying, without requiring overwrite permissions."""
    try:
        info = path.stat()
        if path.read_bytes() != baseline:
            raise conflict_error(f"{label} changed on disk: {path}")
    except FileNotFoundError as exc:
        raise conflict_error(f"{label} no longer exists: {path}") from exc
    return info


def _check_baseline(
    path: Path,
    baseline: bytes,
    *,
    conflict_error: type[Exception] = FileConflictError,
    unsupported_error: type[Exception] = UnsupportedOperationError,
    label: str = "Library",
) -> os.stat_result:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise unsupported_error(
                "Save requires a regular, non-symlink, singly linked file"
            )
        if path.read_bytes() != baseline:
            raise conflict_error(f"{label} changed on disk: {path}")
    except FileNotFoundError as exc:
        raise conflict_error(f"{label} no longer exists: {path}") from exc
    return info


def save_source(
    path: Path,
    baseline: bytes,
    output: bytes,
    *,
    conflict_error: type[Exception] = FileConflictError,
    unsupported_error: type[Exception] = UnsupportedOperationError,
    label: str = "Library",
) -> None:
    info = _check_baseline(
        path,
        baseline,
        conflict_error=conflict_error,
        unsupported_error=unsupported_error,
        label=label,
    )
    if output == baseline:
        return
    if not stat.S_IMODE(info.st_mode) & 0o222:
        raise PermissionError(f"{label} has no write permission bits: {path}")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(output)
            stream.flush()
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            os.fsync(stream.fileno())
        final_info = _check_baseline(
            path,
            baseline,
            conflict_error=conflict_error,
            unsupported_error=unsupported_error,
            label=label,
        )
        if (final_info.st_dev, final_info.st_ino, final_info.st_mode) != (
            info.st_dev,
            info.st_ino,
            info.st_mode,
        ):
            raise conflict_error(
                f"{label} identity or permissions changed during save: {path}"
            )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
