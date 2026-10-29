"""Optimistic single-file persistence, not a lock/session or transaction system."""

import os
import stat
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from ._symbol_types import FileConflictError, UnsupportedOperationError


@dataclass(frozen=True)
class Fingerprint:
    """What an artifact remembers about the file it read: size and content hash.

    ADR 0009 write promise: no silent overwrite, without keeping the original
    bytes in memory. The fingerprint stands in for the baseline bytes.
    """

    size: int
    digest: str

    @classmethod
    def of(cls, raw: bytes) -> "Fingerprint":
        """Fingerprint the given bytes."""
        return cls(len(raw), sha256(raw).hexdigest())

    def matches(self, raw: bytes) -> bool:
        """Whether *raw* is the content this fingerprint was taken from."""
        return len(raw) == self.size and sha256(raw).hexdigest() == self.digest


Baseline = bytes | Fingerprint


def _matches(baseline: Baseline, raw: bytes) -> bool:
    if isinstance(baseline, Fingerprint):
        return baseline.matches(raw)
    return raw == baseline


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
) -> os.stat_result:
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
            staged = os.fstat(stream.fileno())
        _check_new_destination(path, unsupported_error=unsupported_error)
        # Linking a staged regular file is atomic and refuses a racing destination.
        os.link(temporary, path)
        return staged
    finally:
        temporary.unlink(missing_ok=True)


def _file_version(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _backup_recovery(path: Path, raw: bytes, mode: int) -> Path:
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.recovery.", suffix=".tmp", dir=path.parent
    )
    recovery = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
    except BaseException:
        recovery.unlink(missing_ok=True)
        raise
    return recovery


def _recover_backup(
    path: Path,
    installed: os.stat_result,
    baseline: bytes,
    recovery: Path | None,
) -> None:
    """Restore only our installed backup, never a concurrent replacement/version."""
    try:
        info = _check_baseline(path, baseline, label="Library backup")
        if _file_version(info) != _file_version(installed):
            raise FileConflictError(
                f"Library backup changed during failed save: {path}"
            )
        if recovery is None:
            path.unlink()
        else:
            os.replace(recovery, path)
    except Exception as exc:
        retained = "" if recovery is None else f"; prior backup retained at {recovery}"
        raise FileConflictError(
            f"Cannot restore backup after failed save; concurrent backup left untouched: {path}{retained}"
        ) from exc


def save_library_source(path: Path, baseline: bytes, output: bytes) -> None:
    """Back up a changed library to native Foo.bak before replacing Foo.kicad_sym."""
    info = _check_baseline(path, baseline)
    if output == baseline:
        return
    if not stat.S_IMODE(info.st_mode) & 0o222:
        raise PermissionError(f"Library has no write permission bits: {path}")
    # Resolve directory aliases, not the final backup filename: do not follow links.
    backup = path.parent.resolve() / path.with_suffix(".bak").name
    if backup == path.resolve():
        raise UnsupportedOperationError("Library and backup destinations collide")
    parent_mode = stat.S_IMODE(backup.parent.stat().st_mode)
    if (
        not parent_mode & 0o222
        or not parent_mode & 0o111
        or not os.access(backup.parent, os.W_OK | os.X_OK)
    ):
        raise PermissionError(
            f"Library destination directory is not writable: {backup.parent}"
        )
    prior: bytes | None = None
    recovery: Path | None = None
    retain_recovery = False
    try:
        backup_info = backup.lstat()
    except FileNotFoundError:
        backup_info = None
    if backup_info is not None:
        if (backup_info.st_dev, backup_info.st_ino) == (info.st_dev, info.st_ino):
            raise UnsupportedOperationError("Library and backup destinations collide")
        if not stat.S_ISREG(backup_info.st_mode) or backup_info.st_nlink != 1:
            raise UnsupportedOperationError(
                "Backup requires a regular singly linked file"
            )
        if not stat.S_IMODE(backup_info.st_mode) & 0o222:
            raise PermissionError(f"Backup has no write permission bits: {backup}")
        prior = backup.read_bytes()
        _check_baseline(backup, prior, label="Library backup")
        recovery = _backup_recovery(backup, prior, stat.S_IMODE(backup_info.st_mode))
    try:
        try:
            if prior is None:
                expected = save_new_source(
                    backup, baseline, mode=stat.S_IMODE(info.st_mode)
                )
            else:
                expected = save_source(backup, prior, baseline, label="Library backup")
            installed = _check_baseline(
                backup, baseline, label="Installed library backup"
            )
            # Own rename/link operations can change ctime/nlink, not file data facts.
            if (
                installed.st_dev,
                installed.st_ino,
                installed.st_mode,
                installed.st_size,
                installed.st_mtime_ns,
            ) != (
                expected.st_dev,
                expected.st_ino,
                expected.st_mode,
                expected.st_size,
                expected.st_mtime_ns,
            ):
                raise FileConflictError("Installed backup was concurrently changed")
        except BaseException as exc:
            if recovery is not None and backup_info is not None:
                try:
                    current = _check_baseline(
                        backup, prior or b"", label="Library backup"
                    )
                    unchanged = _file_version(current) == _file_version(backup_info)
                except (OSError, FileConflictError, UnsupportedOperationError):
                    unchanged = False
                if not unchanged:
                    retain_recovery = True
                    raise FileConflictError(
                        f"Backup changed before source save; prior backup retained at {recovery}"
                    ) from exc
            raise
        try:
            save_source(path, baseline, output)
        except BaseException:
            try:
                _recover_backup(backup, installed, baseline, recovery)
            except FileConflictError:
                retain_recovery = recovery is not None
                raise
            raise
    finally:
        if recovery is not None and not retain_recovery:
            recovery.unlink(missing_ok=True)


def _check_read_baseline(
    path: Path,
    baseline: Baseline,
    *,
    conflict_error: type[Exception] = FileConflictError,
    label: str = "Library",
) -> os.stat_result:
    """Check source freshness for copying, without requiring overwrite permissions."""
    try:
        info = path.stat()
        if not _matches(baseline, path.read_bytes()):
            raise conflict_error(f"{label} changed on disk: {path}")
    except FileNotFoundError as exc:
        raise conflict_error(f"{label} no longer exists: {path}") from exc
    return info


def _check_baseline(
    path: Path,
    baseline: Baseline,
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
        if not _matches(baseline, path.read_bytes()):
            raise conflict_error(f"{label} changed on disk: {path}")
    except FileNotFoundError as exc:
        raise conflict_error(f"{label} no longer exists: {path}") from exc
    return info


def save_source(
    path: Path,
    baseline: Baseline,
    output: bytes,
    *,
    conflict_error: type[Exception] = FileConflictError,
    unsupported_error: type[Exception] = UnsupportedOperationError,
    label: str = "Library",
) -> os.stat_result:
    """Replace one existing file atomically after an optimistic baseline check.

    *baseline* is the bytes the artifact read, or their :class:`Fingerprint`.
    An output equal to the baseline replaces nothing. The temporary file is a
    same-directory dotfile with a ``.tmp`` suffix, never a KiCad file name.
    """
    info = _check_baseline(
        path,
        baseline,
        conflict_error=conflict_error,
        unsupported_error=unsupported_error,
        label=label,
    )
    if _matches(baseline, output):
        return info
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
            installed = os.fstat(stream.fileno())
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
        return installed
    finally:
        temporary.unlink(missing_ok=True)
