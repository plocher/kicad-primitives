"""The layer-1 Schematic.save() policy over layer-0 SheetFile saves (ADR 0011 D3, D4).

Write set (D3): only sheet files with unsaved changes. Unchanged files are not
touched. Order: child sheet files before their parents.

Failure classes (D4):

- Content (validate) or target problems found before any write: write nothing.
- Permissions found before any write: write nothing.
- Conflict, before any write and again before each replace: never retry, never
  overwrite (unless the caller asks for overwrite); that sheet stays unsaved.
- Permission change during a write: report, no retry.
- Short-lived system error during a write: continue, then retry once at the end.
- Lasting or unknown system error during a write: stop at once.
"""

from __future__ import annotations

import errno
import os
import stat
import time
from typing import TYPE_CHECKING, Literal, NoReturn

from .schematics import (
    InvalidSchematicError,
    SchematicConflictError,
    SchematicSaveError,
    SheetSaveResult,
    UnsupportedSchematicOperationError,
)

if TYPE_CHECKING:
    from .schematics import Schematic, SheetFile

# Fixed internal retry bound (D4): one retry, after this wait in seconds.
_RETRY_DELAY = 0.25
_TRANSIENT = frozenset(
    {errno.EINTR, errno.EAGAIN, errno.EWOULDBLOCK, errno.EBUSY, errno.ETIMEDOUT}
)
_PERMISSION = frozenset({errno.EACCES, errno.EPERM})
_Kind = Literal["transient", "permission", "lasting"]


def _kind(exc: OSError) -> _Kind:
    """Classify a write error; an unknown error is lasting, so the save stops."""
    if isinstance(exc, PermissionError) or exc.errno in _PERMISSION:
        return "permission"
    if (
        isinstance(exc, (InterruptedError, BlockingIOError, TimeoutError))
        or exc.errno in _TRANSIENT
    ):
        return "transient"
    return "lasting"


def _target_problem(sheet: SheetFile) -> str | None:
    """Return why the file cannot be replaced in place, or None."""
    try:
        info = sheet.path.lstat()
    except FileNotFoundError:
        return None  # A missing file is a conflict, not a target problem.
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        return "not a regular, non-symlink, singly linked file"
    if not stat.S_IMODE(info.st_mode) & 0o222 or not os.access(sheet.path, os.W_OK):
        return "file is not writable"
    parent = sheet.path.parent
    mode = stat.S_IMODE(parent.stat().st_mode)
    if not mode & 0o222 or not mode & 0o111 or not os.access(parent, os.W_OK | os.X_OK):
        return f"directory is not writable: {parent}"
    return None


def _is_conflict(sheet: SheetFile) -> bool:
    try:
        raw = sheet.path.read_bytes()
    except FileNotFoundError:
        return True
    return sheet._fingerprint is not None and not sheet._fingerprint.matches(raw)


def _raise(
    message: str,
    changed: tuple[SheetFile, ...],
    results: dict[SheetFile, SheetSaveResult],
) -> NoReturn:
    ordered = tuple(
        results.get(sheet, SheetSaveResult(sheet.path, "unsaved", "not written"))
        for sheet in changed
    )
    raise SchematicSaveError(message, ordered)


def validate(schematic: Schematic) -> None:
    """Run the content checks on every changed sheet file; write nothing."""
    changed = tuple(f for f in schematic._write_order() if f._modified)
    failures: dict[SheetFile, SheetSaveResult] = {}
    for sheet in changed:
        try:
            sheet.validate()
        except (InvalidSchematicError, UnsupportedSchematicOperationError) as exc:
            failures[sheet] = SheetSaveResult(sheet.path, "failed", str(exc))
    if failures:
        _raise("Invalid content; nothing was written", changed, failures)


def save(schematic: Schematic, *, overwrite: bool) -> None:
    """Write every changed sheet file under the D4 failure policy."""
    changed = tuple(f for f in schematic._write_order() if f._modified)
    if not changed:
        return
    validate(schematic)
    blocked = {
        sheet: SheetSaveResult(sheet.path, "failed", problem)
        for sheet in changed
        if (problem := _target_problem(sheet)) is not None
    }
    if blocked:
        _raise("Cannot write some sheet files; nothing was written", changed, blocked)
    results: dict[SheetFile, SheetSaveResult] = {}
    if not overwrite:
        for sheet in changed:
            if _is_conflict(sheet):
                results[sheet] = SheetSaveResult(
                    sheet.path, "conflict", "the disk file is not the file read"
                )
    retry: list[SheetFile] = []
    for index, sheet in enumerate(changed):
        if sheet in results:
            continue
        outcome, kind = _write(sheet, overwrite=overwrite)
        results[sheet] = outcome
        if kind == "transient":
            retry.append(sheet)
        elif kind == "lasting":
            for later in changed[index + 1 :]:
                results.setdefault(
                    later,
                    SheetSaveResult(later.path, "unsaved", "save stopped early"),
                )
            _raise("A lasting error stopped the save", changed, results)
    if retry:
        time.sleep(_RETRY_DELAY)
        for sheet in retry:
            if not overwrite and _is_conflict(sheet):
                results[sheet] = SheetSaveResult(
                    sheet.path, "conflict", "the disk file is not the file read"
                )
            else:
                results[sheet], _ = _write(sheet, overwrite=overwrite)
    if any(result.status != "written" for result in results.values()):
        _raise("Some sheet files were not written", changed, results)


def _write(
    sheet: SheetFile, *, overwrite: bool
) -> tuple[SheetSaveResult, _Kind | None]:
    try:
        sheet.save(overwrite=overwrite)
    except SchematicConflictError as exc:
        return SheetSaveResult(sheet.path, "conflict", str(exc)), None
    except OSError as exc:
        return SheetSaveResult(sheet.path, "failed", str(exc)), _kind(exc)
    return SheetSaveResult(sheet.path, "written"), None
