"""Inspect and edit KiCad footprint libraries; parsing and writing stay private.

A ``.pretty`` library is a directory of independent ``.kicad_mod`` files.
``FootprintLibrary`` is the directory: a cached table of contents with an
explicit ``refresh()``, immediate directory operations, and a close decision
over its open footprints. ``Footprint`` is one file with the full lifecycle:
open, read, modify, validate, write, close (ADR 0009).
"""

from __future__ import annotations

import stat
from collections.abc import Iterable
from os import PathLike
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

from . import __version__, _footprint_parse, _registry, _symbol_persist
from ._footprint_types import (
    AmbiguousFootprintAttributeError,
    FootprintAttribute,
    FootprintConflictError,
    FootprintFailure,
    FootprintLibraryError,
    FootprintLifecycleError,
    FootprintSummary,
    InvalidFootprintError,
    Pad,
    PadDrill,
    UnsupportedOperationError,
    matches_filters,
)
from ._symbol_persist import Fingerprint
from .tables import LibraryTables

__all__ = [
    "AmbiguousFootprintAttributeError",
    "Footprint",
    "FootprintAttribute",
    "FootprintConflictError",
    "FootprintFailure",
    "FootprintLibrary",
    "FootprintLibraryError",
    "FootprintLifecycleError",
    "FootprintSummary",
    "InvalidFootprintError",
    "OnClose",
    "Pad",
    "PadDrill",
    "UnsupportedOperationError",
    "matches_filters",
]

OnClose = Literal["save", "discard", "raise"]
_KIND = "footprint"
_SUFFIX = ".kicad_mod"
_ON_CLOSE: tuple[OnClose, ...] = ("save", "discard", "raise")


def _require_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("Footprint name must be a string")
    if not name or name != name.strip():
        raise ValueError("Footprint name cannot be empty or padded with whitespace")
    if any(ch in name for ch in "/\\:\x00") or name in (".", ".."):
        raise ValueError(f"Invalid footprint name: {name!r}")
    name.encode("utf-8")
    return name


class Footprint:
    """One ``.kicad_mod`` file, opened through its library, with explicit persistence."""

    def __init__(
        self, library: FootprintLibrary | None, path: Path, raw: bytes
    ) -> None:
        self._library = library
        self._path = path
        self._source = _footprint_parse.read_source(raw)
        self._fingerprint = Fingerprint.of(raw)
        self._mode = stat.S_IMODE(path.stat().st_mode)
        self._modified = False
        self._closed = False
        self._deleted = False

    def _check_open(self) -> None:
        if self._deleted:
            raise FootprintLifecycleError(f"Footprint was deleted: {self._path}")
        if self._closed:
            raise FootprintLifecycleError(f"Footprint is closed: {self._path}")

    def _accept(self, updated: _footprint_parse.ParsedFootprint) -> None:
        if updated is self._source:
            return
        self._source = updated
        self._modified = True

    @property
    def library(self) -> FootprintLibrary | None:
        """The owning library, or ``None`` after a save-as outside it."""
        return self._library

    @property
    def path(self) -> Path:
        """Current file, retained as diagnostic identity after exit."""
        return self._path

    @property
    def name(self) -> str:
        """Identity: the file stem, as KiCad names a loaded footprint."""
        return self._path.stem

    @property
    def is_closed(self) -> bool:
        """Whether this footprint exited through close, discard, or delete."""
        return self._closed

    @property
    def is_modified(self) -> bool:
        """Edit mark: set by a real change, cleared by a successful save."""
        self._check_open()
        return self._modified

    @property
    def declared_name(self) -> str:
        """The name atom inside the file; KiCad replaces it with the stem on load."""
        self._check_open()
        return self._source.name

    @property
    def version(self) -> int:
        """The file's declared format version (0 for a legacy file without one)."""
        self._check_open()
        return self._source.version

    @property
    def description(self) -> str:
        """The ``(descr …)`` text, or an empty string."""
        self._check_open()
        return self._source.description

    @property
    def tags(self) -> str:
        """The ``(tags …)`` keyword text, or an empty string."""
        self._check_open()
        return self._source.tags

    @property
    def attributes(self) -> tuple[FootprintAttribute, ...]:
        """Current ``(property …)`` values in file order, including repeats."""
        self._check_open()
        return self._source.attributes

    @property
    def footprint_type(self) -> str:
        """``smd``, ``through_hole``, or ``unspecified``."""
        self._check_open()
        return self._source.footprint_type

    @property
    def flags(self) -> frozenset[str]:
        """Other ``(attr …)`` tokens, such as ``exclude_from_bom``."""
        self._check_open()
        return self._source.flags

    @property
    def pads(self) -> tuple[Pad, ...]:
        """Every ``(pad …)`` in file order, as immutable values."""
        self._check_open()
        return self._source.pads

    @property
    def pad_count(self) -> int:
        """Number of pad nodes, including NPTH and unnamed mechanical pads."""
        self._check_open()
        return len(self._source.pads)

    @property
    def unique_pad_count(self) -> int:
        """KiCad 10.0.1 ``GetUniquePadCount(DO_NOT_INCLUDE_NPTH)``; see ``unique_pad_count``."""
        self._check_open()
        return self.summary.unique_pad_count

    @property
    def summary(self) -> FootprintSummary:
        """An immutable row for the current in-memory content."""
        self._check_open()
        return self._source.summary(self._path)

    def attribute(self, name: str) -> FootprintAttribute:
        """Inspect one attribute; missing raises ``KeyError``, repeats raise."""
        self._check_open()
        return self._source.attribute(name)

    def matches_filters(
        self, patterns: Iterable[str], *, nickname: str | None = None
    ) -> bool:
        """Apply symbol ``ki_fp_filters`` patterns to this footprint's name."""
        self._check_open()
        return matches_filters(self.name, patterns, nickname=nickname)

    def to_bytes(self) -> bytes:
        """Preview the current source bytes, including untouched opaque content."""
        self._check_open()
        return self._source.document.render().encode("utf-8")

    def set_attribute(self, name: str, value: str) -> None:
        """Create, update, or exactly preserve one attribute in memory."""
        self._check_open()
        name = _footprint_parse.require_attribute_name(name)
        try:
            self._source.attribute(name)
        except KeyError:
            updated = _footprint_parse.insert_attribute(self._source, name, value)
        else:
            updated = _footprint_parse.replace_attribute(self._source, name, value)
        self._accept(updated)

    def add_attribute(self, name: str, value: str) -> None:
        """Create one new hidden attribute; an existing identity is refused."""
        self._check_open()
        self._accept(_footprint_parse.insert_attribute(self._source, name, value))

    def delete_attribute(self, name: str) -> None:
        """Delete one unambiguous attribute and its leading separator."""
        self._check_open()
        self._accept(_footprint_parse.delete_attribute(self._source, name))

    def validate(self, destination: str | PathLike[str] | None = None) -> None:
        """Check that the content can be written; run no KiCad.

        Raises ``UnsupportedOperationError`` for a format other than the
        write format, ``InvalidFootprintError`` when the pending source does
        not parse back as one footprint, ``UnicodeEncodeError`` for content
        that cannot be encoded, and ``OSError`` subclasses when the
        destination directory does not exist or is not writable.
        """
        self._check_open()
        _footprint_parse.require_writeable(self._source.version)
        output = self._source.document.render().encode("utf-8")
        _footprint_parse.read_source(output)
        target = self._path if destination is None else Path(destination).absolute()
        parent = target.parent
        if not parent.is_dir():
            raise NotADirectoryError(f"Destination directory does not exist: {parent}")
        if target.exists() and not target.is_file():
            raise IsADirectoryError(f"Destination is not a file: {target}")

    def save(self, *, overwrite: bool = False) -> None:
        """Write this footprint to its path under the ADR 0009 write promises.

        Runs :meth:`validate` first. Refuses when the file on disk is not the
        file this footprint read or last wrote, raising
        ``FootprintConflictError``; ``overwrite=True`` is the explicit way
        through and writes over whatever is there (or creates the file).
        The write is a same-directory temporary file renamed into place; a
        failure leaves the original untouched and the edits in memory.
        KiCad writes no backup for a footprint, and neither does this.
        """
        self.validate()
        output = self.to_bytes()
        if overwrite and not self._path.exists():
            _symbol_persist.save_new_source(
                self._path,
                output,
                mode=self._mode,
                unsupported_error=InvalidFootprintError,
            )
        else:
            baseline: _symbol_persist.Baseline = self._fingerprint
            if overwrite:
                baseline = self._path.read_bytes()
            _symbol_persist.save_source(
                self._path,
                baseline,
                output,
                conflict_error=FootprintConflictError,
                unsupported_error=InvalidFootprintError,
                label="Footprint",
            )
        self._fingerprint = Fingerprint.of(output)
        self._modified = False

    def save_as(self, path: str | PathLike[str], *, overwrite: bool = False) -> None:
        """Write one new file and rebind this footprint to it only after success.

        The destination must not exist unless ``overwrite=True``. Its parent
        must be an existing, writable, non-symlink directory. The original
        file is not changed. A destination inside the owning library joins
        that library under its new stem; a destination elsewhere detaches the
        footprint from the library (``library`` becomes ``None``).
        """
        self._check_open()
        destination = Path(path).expanduser().absolute()
        if destination.suffix != _SUFFIX:
            raise ValueError(f"Destination must end with {_SUFFIX}: {destination}")
        _require_name(destination.stem)
        self.validate(destination)
        output = self.to_bytes()
        if overwrite and destination.exists():
            _symbol_persist.save_source(
                destination,
                destination.read_bytes(),
                output,
                conflict_error=FootprintConflictError,
                unsupported_error=InvalidFootprintError,
                label="Footprint",
            )
        else:
            _symbol_persist.save_new_source(
                destination,
                output,
                mode=self._mode,
                unsupported_error=InvalidFootprintError,
            )
        old = self._path
        self._path = destination
        self._fingerprint = Fingerprint.of(output)
        self._modified = False
        if self._library is not None:
            self._library._rebound(self, old, destination)

    def discard(self) -> None:
        """Exit without writing; terminal, not a reset for continued editing."""
        if self._closed:
            return
        self._closed = True
        if self._library is not None:
            self._library._released(self)

    def close(self) -> None:
        """Exit, saving first only when modified; a failed save keeps it open."""
        if self._closed:
            return
        if self._modified:
            self.save()
        self.discard()

    def __enter__(self) -> Self:
        """Use the open footprint as a context manager."""
        self._check_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close on normal exit; discard without writing when an exception exits."""
        if exc_type is None:
            self.close()
        else:
            self.discard()


class FootprintLibrary:
    """One ``.pretty`` directory: cached summaries, live footprints, directory operations."""

    def __init__(self, path: Path, on_close: OnClose) -> None:
        if on_close not in _ON_CLOSE:
            raise ValueError(f"on_close must be one of {_ON_CLOSE}, not {on_close!r}")
        if not path.is_dir():
            raise NotADirectoryError(f"Footprint library is not a directory: {path}")
        self._path = path
        self._on_close: OnClose = on_close
        self._closed = False
        self._summaries: dict[str, FootprintSummary] = {}
        self._failures: dict[str, FootprintFailure] = {}
        self._stamps: dict[str, tuple[int, int, int]] = {}
        self._open: dict[str, Footprint] = {}
        self._scan()

    @classmethod
    def open(
        cls,
        target: str | PathLike[str],
        *,
        tables: LibraryTables | None = None,
        on_close: OnClose = "save",
    ) -> FootprintLibrary:
        """Open one library by registered nickname or by directory path.

        A ``str`` that is a registered footprint nickname in *tables* (or in
        the default ``LibraryTables.open()`` context) opens that library's
        resolved path; any other ``str`` and every ``Path`` is a path. The
        same directory, by resolved real path, opens to the same object until
        it is closed or discarded; *on_close* is taken from the first open.
        Opening parses every ``.kicad_mod`` once into :attr:`summaries`.
        """
        location = _registry.resolve_target(
            target, library_type="footprint", tables=tables
        )
        existing = _registry.lookup(_KIND, location)
        if isinstance(existing, FootprintLibrary):
            return existing
        library = cls(location, on_close)
        _registry.register(_KIND, location, library)
        return library

    def _check_open(self) -> None:
        if self._closed:
            raise FootprintLifecycleError(f"Library is closed: {self._path}")

    def _file(self, name: str) -> Path:
        return self._path / f"{_require_name(name)}{_SUFFIX}"

    def _stamp(self, path: Path) -> tuple[int, int, int]:
        info = path.stat()
        return (info.st_size, info.st_mtime_ns, info.st_ino)

    def _load(self, path: Path) -> None:
        name = path.stem
        try:
            stamp = self._stamp(path)
            summary = _footprint_parse.read_source(path.read_bytes()).summary(path)
        except (OSError, FootprintLibraryError, UnsupportedOperationError) as exc:
            self._summaries.pop(name, None)
            self._stamps.pop(name, None)
            self._failures[name] = FootprintFailure(
                name, path, f"{type(exc).__name__}: {exc}"
            )
            return
        self._failures.pop(name, None)
        self._summaries[name] = summary
        self._stamps[name] = stamp

    def _scan(self) -> None:
        present: set[str] = set()
        for path in sorted(self._path.iterdir()):
            if path.suffix != _SUFFIX or not path.is_file():
                continue
            name = path.stem
            present.add(name)
            try:
                unchanged = self._stamps.get(name) == self._stamp(path)
            except OSError:
                unchanged = False
            if not unchanged:
                self._load(path)
        for name in set(self._summaries) | set(self._failures):
            if name not in present:
                self._summaries.pop(name, None)
                self._failures.pop(name, None)
                self._stamps.pop(name, None)

    def _forget(self, name: str) -> None:
        self._summaries.pop(name, None)
        self._failures.pop(name, None)
        self._stamps.pop(name, None)

    def _released(self, footprint: Footprint) -> None:
        if self._open.get(footprint.name) is footprint:
            del self._open[footprint.name]

    def _rebound(self, footprint: Footprint, old: Path, new: Path) -> None:
        if self._open.get(old.stem) is footprint:
            del self._open[old.stem]
        if new.parent.resolve() == self._path.resolve():
            self._open[new.stem] = footprint
            self._load(new)
        else:
            footprint._library = None

    @property
    def path(self) -> Path:
        """The library directory."""
        return self._path

    @property
    def name(self) -> str:
        """The directory name without its ``.pretty`` suffix."""
        return self._path.stem if self._path.suffix == ".pretty" else self._path.name

    @property
    def on_close(self) -> OnClose:
        """The close decision chosen at open: ``save``, ``discard``, or ``raise``."""
        return self._on_close

    @property
    def is_closed(self) -> bool:
        """Whether this library exited through close or discard."""
        return self._closed

    @property
    def is_modified(self) -> bool:
        """Whether any open footprint carries an edit mark."""
        self._check_open()
        return any(f.is_modified for f in self._open.values())

    @property
    def summaries(self) -> tuple[FootprintSummary, ...]:
        """Cached rows, sorted by name, as of open or the last :meth:`refresh`."""
        self._check_open()
        return tuple(self._summaries[n] for n in sorted(self._summaries))

    @property
    def failures(self) -> tuple[FootprintFailure, ...]:
        """Files that did not read as footprints, sorted by name; the rest loaded."""
        self._check_open()
        return tuple(self._failures[n] for n in sorted(self._failures))

    @property
    def footprints(self) -> tuple[Footprint, ...]:
        """Currently open live footprints, sorted by name."""
        self._check_open()
        return tuple(self._open[n] for n in sorted(self._open))

    def summary(self, name: str) -> FootprintSummary:
        """One cached row by name; ``KeyError`` when absent from the cache."""
        self._check_open()
        return self._summaries[name]

    def refresh(self) -> None:
        """Rescan the directory and re-parse files whose size, mtime, or inode changed.

        New files appear, deleted files disappear, changed files are read
        again. Open footprints are not touched; their write promises still
        hold against the file on disk.
        """
        self._check_open()
        self._scan()

    def footprint(self, name: str) -> Footprint:
        """Open one live footprint from disk, or return the one already open."""
        self._check_open()
        live = self._open.get(name)
        if live is not None and not live.is_closed:
            return live
        path = self._file(name)
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise KeyError(name) from exc
        footprint = Footprint(self, path, raw)
        self._open[name] = footprint
        return footprint

    def _write_new(self, path: Path, raw: bytes, *, mode: int = 0o644) -> None:
        _symbol_persist.save_new_source(
            path, raw, mode=mode, unsupported_error=InvalidFootprintError
        )
        self._load(path)

    def create(self, name: str) -> None:
        """Write a new minimal footprint file now; refuse an existing name."""
        self._check_open()
        path = self._file(name)
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Footprint already exists: {path}")
        self._write_new(
            path,
            _footprint_parse.new_footprint_source(name, generator_version=__version__),
        )

    def _copy_bytes(self, source_dir: Path, source_name: str, new_name: str) -> bytes:
        source = source_dir / f"{_require_name(source_name)}{_SUFFIX}"
        try:
            raw = source.read_bytes()
        except FileNotFoundError as exc:
            raise KeyError(source_name) from exc
        parsed = _footprint_parse.read_source(raw)
        return _footprint_parse.renamed_source(parsed, source_name, new_name).encode(
            "utf-8"
        )

    def copy(self, source_name: str, new_name: str) -> None:
        """Duplicate one file on disk now under a new name, as KiCad's duplicate does.

        The internal name becomes *new_name*; a Value equal to *source_name*
        follows it. Other bytes are preserved. The source is read from disk,
        not from an open handle's pending edits.
        """
        self._check_open()
        destination = self._file(new_name)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Footprint already exists: {destination}")
        raw = self._copy_bytes(self._path, source_name, new_name)
        self._write_new(destination, raw)

    def copy_from(
        self, other: FootprintLibrary, source_name: str, new_name: str
    ) -> None:
        """Copy one footprint file from another open library into this one, now."""
        self._check_open()
        if not isinstance(other, FootprintLibrary):
            raise TypeError("other must be an opened FootprintLibrary")
        other._check_open()
        destination = self._file(new_name)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Footprint already exists: {destination}")
        raw = self._copy_bytes(other._path, source_name, new_name)
        self._write_new(destination, raw)

    def delete(self, name: str) -> None:
        """Remove one file now; an open handle for it becomes stale."""
        self._check_open()
        path = self._file(name)
        if not path.is_file():
            raise KeyError(name)
        path.unlink()
        live = self._open.pop(name, None)
        if live is not None:
            live._deleted = True
            live._closed = True
        self._forget(name)

    def rename(self, old_name: str, new_name: str) -> None:
        """Rename one footprint now, as KiCad does: write new, fix names, delete old.

        The new file carries *new_name* as its internal name, and its Value
        when the Value equalled *old_name*. The old file is deleted after
        the new one exists. An open handle is rebound to the new path with
        the same substitution applied to its pending content; its edit mark
        is unchanged.
        """
        self._check_open()
        source = self._file(old_name)
        destination = self._file(new_name)
        if old_name == new_name:
            return
        if not source.is_file():
            raise KeyError(old_name)
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"Footprint already exists: {destination}")
        raw = source.read_bytes()
        parsed = _footprint_parse.read_source(raw)
        renamed = _footprint_parse.renamed_source(parsed, old_name, new_name).encode(
            "utf-8"
        )
        self._write_new(destination, renamed, mode=stat.S_IMODE(source.stat().st_mode))
        source.unlink()
        self._forget(old_name)
        live = self._open.pop(old_name, None)
        if live is not None:
            pending = _footprint_parse.renamed_source(live._source, old_name, new_name)
            live._source = _footprint_parse.read_source(pending.encode("utf-8"))
            live._path = destination
            live._fingerprint = Fingerprint.of(renamed)
            self._open[new_name] = live

    def discard(self) -> None:
        """Drop every open footprint's edits and exit; terminal."""
        if self._closed:
            return
        for footprint in tuple(self._open.values()):
            footprint.discard()
        self._open.clear()
        self._closed = True
        _registry.unregister(_KIND, self._path, self)

    def close(self) -> None:
        """Apply the ``on_close`` decision to open footprints, then exit.

        ``save`` saves every modified open footprint, then closes all;
        ``discard`` drops open edits; ``raise`` refuses while any footprint
        is modified and names them. A failed save propagates and the
        library stays open. The library writes nothing of its own.
        """
        if self._closed:
            return
        modified = [f for f in self.footprints if f.is_modified]
        if self._on_close == "raise" and modified:
            names = ", ".join(f.name for f in modified)
            raise FootprintLifecycleError(f"Modified footprints are open: {names}")
        if self._on_close == "save":
            for footprint in modified:
                footprint.save()
        self.discard()

    def __enter__(self) -> Self:
        """Use the open library as a context manager."""
        self._check_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Apply ``on_close`` on normal exit; discard when an exception exits."""
        if exc_type is None:
            self.close()
        else:
            self.discard()
