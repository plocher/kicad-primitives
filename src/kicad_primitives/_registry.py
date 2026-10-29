"""Process-wide registry of open library artifacts, keyed by resolved real path.

ADR 0009 accepted one live object per library file or directory. The registry
keeps strong references while an artifact is open; ``close()`` and
``discard()`` remove the entry. There is no reference count and no policy.
"""

from __future__ import annotations

from os import PathLike
from pathlib import Path

from .tables import LibraryTables, LibraryTablesError, LibraryType, MissingLibraryError

_OPEN: dict[tuple[str, Path], object] = {}


def resolve_target(
    target: str | PathLike[str],
    *,
    library_type: LibraryType,
    tables: LibraryTables | None,
) -> Path:
    """Map an open target to an absolute path.

    Every ``PathLike`` is a filesystem path. With explicit *tables*, a ``str``
    is first tried as a registered nickname of *library_type*; an
    unregistered ``str`` is a path. Without *tables*, a ``str`` that names an
    existing path is that path at once; otherwise the default
    ``LibraryTables.open()`` context is consulted, and any table failure
    (missing nickname, malformed or unreadable table) falls back to the
    string as a path.
    """
    if not isinstance(target, str):
        return Path(target).absolute()
    if not target.strip():
        raise ValueError("Library target cannot be empty")
    as_path = Path(target).absolute()
    if tables is not None:
        try:
            return tables.resolve(target, library_type=library_type).resolved_path
        except MissingLibraryError:
            return as_path
    if as_path.exists():
        return as_path
    try:
        context = LibraryTables.open()
        return context.resolve(target, library_type=library_type).resolved_path
    except (LibraryTablesError, OSError):
        return as_path


def registry_key(kind: str, path: Path) -> tuple[str, Path]:
    """Identity for one artifact: its kind and its resolved real path."""
    return (kind, path.resolve())


def lookup(kind: str, path: Path) -> object | None:
    """Return the open artifact registered for *path*, or ``None``."""
    found = _OPEN.get(registry_key(kind, path))
    if found is None:
        return None
    if _is_closed(found):
        _OPEN.pop(registry_key(kind, path), None)
        return None
    return found


def register(kind: str, path: Path, artifact: object) -> None:
    """Record *artifact* as the open object for *path*."""
    _OPEN[registry_key(kind, path)] = artifact


def unregister(kind: str, path: Path, artifact: object) -> None:
    """Remove *artifact* for *path*; a different registered object stays."""
    key = registry_key(kind, path)
    if _OPEN.get(key) is artifact:
        del _OPEN[key]


def rebind(kind: str, old: Path, new: Path, artifact: object) -> None:
    """Move *artifact* from *old* to *new* after a successful save-as or rename."""
    unregister(kind, old, artifact)
    register(kind, new, artifact)


def _is_closed(artifact: object) -> bool:
    closed = getattr(artifact, "is_closed", False)
    return bool(closed)
