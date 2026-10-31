"""Inspect and edit explicit-path symbol libraries; parsing stays private."""

from __future__ import annotations

import os
import subprocess
import tempfile
from os import PathLike
from pathlib import Path
from types import TracebackType
from typing import Self

from . import _registry, _symbol_parse, _symbol_persist
from ._kicad_cli import KicadCliNotFoundError, resolve_kicad_cli
from ._symbol_live import (
    StaleSymbolError,
    Symbol,
    SymbolBody,
    SymbolPin,
    SymbolRectangle,
    SymbolText,
)
from ._symbol_types import (
    AmbiguousAttributeError,
    AmbiguousPinError,
    AmbiguousSymbolError,
    FileConflictError,
    InheritanceError,
    InvalidLibraryError,
    LibraryLifecycleError,
    RectangleDefinition,
    SymbolAttribute,
    SymbolDefinition,
    SymbolLibraryError,
    TextDefinition,
    UnsupportedOperationError,
)
from .tables import LibraryTables

_KIND = "symbol"

__all__ = [
    "AmbiguousAttributeError",
    "AmbiguousPinError",
    "AmbiguousSymbolError",
    "FileConflictError",
    "InheritanceError",
    "InvalidLibraryError",
    "KicadCliNotFoundError",
    "LibraryLifecycleError",
    "RectangleDefinition",
    "StaleSymbolError",
    "Symbol",
    "SymbolAttribute",
    "SymbolBody",
    "SymbolDefinition",
    "SymbolLibrary",
    "SymbolLibraryError",
    "SymbolPin",
    "SymbolRectangle",
    "SymbolText",
    "TextDefinition",
    "UnsupportedOperationError",
]


class SymbolLibrary:
    """One source library with stable editable symbols and explicit persistence."""

    def __init__(
        self, path: Path, raw: bytes, info: os.stat_result | None = None
    ) -> None:
        self._path = path
        self._source = _symbol_parse.read_source(raw)
        self._fingerprint = _symbol_persist.Fingerprint.of(raw, info)
        self._modified = False
        self._closed = False
        self._symbols = tuple(Symbol(self, data) for data in self._source.symbols)

    def _accept_source(
        self,
        updated: _symbol_parse.ParsedLibrary,
        *,
        renamed: tuple[str, str] | None = None,
    ) -> None:
        self._check_open()
        if updated.document.source == self._source.document.source:
            return
        old = list(self._symbols)
        handles: list[Symbol] = []
        for data in updated.symbols:
            name = (
                renamed[0]
                if renamed is not None and data.name == renamed[1]
                else data.name
            )
            handle = next((s for s in old if s._data.name == name), None)
            if handle is None:
                handle = Symbol(self, data)
            else:
                old.remove(handle)
                handle._refresh(data)
            handles.append(handle)
        for handle in old:
            handle._alive = False
        self._source = updated
        self._symbols = tuple(handles)
        self._modified = True

    def _check_open(self) -> None:
        if self._closed:
            raise LibraryLifecycleError(f"Library is closed: {self._path}")

    @property
    def path(self) -> Path:
        """Current destination, retained as diagnostic identity after exit."""
        return self._path

    @property
    def is_closed(self) -> bool:
        """Whether this artifact exited through close or terminal discard."""
        return self._closed

    @property
    def is_modified(self) -> bool:
        """Whether an edit changed this library since it was opened or saved.

        Edits set the flag (ADR 0009); an edit back to the original content
        leaves it set. A successful save or save-as clears it.
        """
        self._check_open()
        return self._modified

    def validate(self) -> None:
        """Check that the current content can be written; write nothing, run no KiCad.

        Raises:
            UnsupportedOperationError: the format is read-only.
            InvalidLibraryError: the current source is not a valid library.
        """
        self._check_open()
        if self.version != _symbol_parse.WRITE_VERSION:
            raise UnsupportedOperationError(f"Format {self.version} is read-only")
        _symbol_parse.read_source(self.to_bytes())

    @classmethod
    def open(
        cls,
        target: str | PathLike[str],
        *,
        tables: LibraryTables | None = None,
    ) -> SymbolLibrary:
        """Open one library by registered nickname or by path.

        A ``str`` that is a registered symbol nickname in *tables* (or in the
        default ``LibraryTables.open()`` context when *tables* is omitted)
        opens that library's resolved path. Any other ``str``, and every
        ``Path``, is a filesystem path. The same library, by resolved real
        path, opens to the same object until it is closed or discarded.
        """
        location = _registry.resolve_target(
            target, library_type="symbol", tables=tables
        )
        existing = _registry.lookup(_KIND, location)
        if isinstance(existing, SymbolLibrary):
            return existing
        info = location.stat()  # Before the read, so the stamp is never newer.
        library = cls(location, location.read_bytes(), info)
        _registry.register(_KIND, location, library)
        return library

    @property
    def version(self) -> int:
        """The file's declared format version, not its generator version."""
        self._check_open()
        return self._source.version

    @property
    def symbols(self) -> tuple[Symbol, ...]:
        """Declared definitions in file order; repeated names are not discarded."""
        self._check_open()
        return self._symbols

    def symbol(self, name: str) -> Symbol:
        """Select one live declared symbol; reject missing or ambiguous identity."""
        self._check_open()
        data = self._source.symbol(name)
        return self._symbols[self._source.symbols.index(data)]

    def resolve(self, name: str) -> SymbolDefinition:
        """Inspect effective inheritance, retaining declaration provenance."""
        self._check_open()
        return _symbol_parse.resolve(self._source, name)

    def to_bytes(self) -> bytes:
        """Preview current source bytes, including all opaque untouched content."""
        self._check_open()
        return self._source.document.render().encode("utf-8")

    def create_symbol(self, name: str, *, extends: str | None = None) -> None:
        """Insert a new empty top-level symbol in this library.

        Optional ``extends`` must name an existing symbol in the same library.
        Duplicate names and read-only formats fail without changing memory or disk.
        """
        self._check_open()
        self._accept_source(
            _symbol_parse.create_symbol(self._source, name, extends=extends)
        )

    def rename_symbol(self, old_name: str, new_name: str) -> None:
        """Rename one symbol, rewrite body names, and update in-library extends.

        Equal names are a no-op. Missing/duplicate targets and read-only formats
        fail without changing memory or disk.
        """
        self._check_open()
        updated = _symbol_parse.rename_symbol(self._source, old_name, new_name)
        self._accept_source(updated, renamed=(old_name, new_name))

    def delete_symbol(self, name: str) -> None:
        """Remove one top-level symbol from this library.

        Refuses when another symbol still extends it. Missing targets and
        read-only formats fail without changing memory or disk.
        """
        self._check_open()
        self._accept_source(_symbol_parse.delete_symbol(self._source, name))

    def copy_symbol(self, source_name: str, new_name: str) -> None:
        """Duplicate one symbol inside this library under a new name.

        Preserves attributes, bodies, and extends. For a second library use
        :meth:`copy_symbol_from`.
        """
        self._check_open()
        self._accept_source(
            _symbol_parse.copy_symbol(self._source, source_name, new_name)
        )

    def copy_symbol_from(
        self,
        source_library: SymbolLibrary,
        source_name: str,
        new_name: str,
    ) -> None:
        """Copy one symbol from another opened library into this library.

        Inserts a renamed declared definition. ``extends`` is preserved and the
        parent must already exist in this library (copy parents first). Same
        library object delegates to :meth:`copy_symbol` rules. Missing targets,
        duplicates, and read-only formats fail without changing memory or disk.
        Callers locate paths however they like (including
        :class:`~kicad_primitives.tables.LibraryTables`); this method does not
        open tables itself.
        """
        self._check_open()
        if not isinstance(source_library, SymbolLibrary):
            raise TypeError("source_library must be an opened SymbolLibrary")
        source_library._check_open()
        updated = _symbol_parse.copy_symbol_from(
            self._source,
            source_library._source,
            source_name,
            new_name,
        )
        self._accept_source(updated)

    def export_svgs(
        self,
        output_dir: str | PathLike[str],
        *,
        kicad_cli: str | PathLike[str] | None = None,
        symbol: str | None = None,
    ) -> Path:
        """Export the current library bytes to SVG via kicad-cli.

        Writes a temporary copy of ``to_bytes()`` so in-memory edits are visible
        without saving. Discovery follows ADR 0007. Raises
        ``KicadCliNotFoundError`` when discovery fails, and ``RuntimeError`` when
        the export process fails. This is an inspection hook, not a contact-sheet
        product UI.
        """
        self._check_open()
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        cli = resolve_kicad_cli(None if kicad_cli is None else Path(kicad_cli))
        with tempfile.TemporaryDirectory(prefix="kicad-primitives-svg-") as tmp:
            lib_path = Path(tmp) / self._path.name
            lib_path.write_bytes(self.to_bytes())
            command = [
                str(cli),
                "sym",
                "export",
                "svg",
                "--output",
                str(out),
                str(lib_path),
            ]
            if symbol is not None:
                command.extend(["--symbol", symbol])
            try:
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or exc.stdout or "").strip()
                raise RuntimeError(
                    f"kicad-cli svg export failed ({exc.returncode}): {detail}"
                ) from exc
        return out

    def save(self, *, overwrite: bool = False) -> None:
        """Write this library to its opened path when it has unsaved changes.

        A clean save writes nothing. A changed save runs :meth:`validate`,
        copies the bytes on disk to native ``Foo.bak``, then replaces the
        regular singly linked source atomically. Output equal to the disk
        bytes replaces neither file. If the disk file is not the file that was
        read, raise :class:`FileConflictError` and write nothing, unless
        *overwrite* is true (ADR 0009). This is not a two-file transaction:
        a final check/replace race remains possible. OS errors propagate;
        failed saves keep the edits in memory.
        """
        self._check_open()
        if not self._modified:
            return
        self.validate()
        output = self.to_bytes()
        written = _symbol_persist.save_library_source(
            self._path, None if overwrite else self._fingerprint, output
        )
        self._fingerprint = _symbol_persist.Fingerprint.of(output, written)
        self._modified = False

    def save_as(self, path: str | PathLike[str]) -> None:
        """Write one new file and rebind only after success, leaving source intact.

        Refuse existing destinations, links, and unsafe/missing destination
        parents. Read-only or readable linked sources may be copied after a
        source-byte conflict check. A new destination has no prior-file backup.
        """
        self._check_open()
        if self.version != _symbol_parse.WRITE_VERSION:
            raise UnsupportedOperationError(f"Format {self.version} is read-only")
        destination = Path(path).expanduser().absolute()
        info = _symbol_persist._check_read_baseline(self._path, self._fingerprint)
        output = self.to_bytes()
        written = _symbol_persist.save_new_source(
            destination, output, mode=info.st_mode & 0o7777
        )
        _registry.rebind(_KIND, self._path, destination, self)
        self._path = destination
        self._fingerprint = _symbol_persist.Fingerprint.of(output, written)
        self._modified = False

    def discard(self) -> None:
        """Exit without writing and invalidate editable handles; never reload or reset."""
        if self._closed:
            return
        self._closed = True
        _registry.unregister(_KIND, self._path, self)
        for symbol in self._symbols:
            symbol._alive = False

    def close(self) -> None:
        """Exit, saving first only when there are pending changes.

        A clean library closes without writing. A dirty library runs
        :meth:`save`. If that save fails, the error propagates and the library
        stays open with its pending changes, so the caller can retry,
        ``save_as`` elsewhere, or :meth:`discard`. Close is idempotent.
        """
        if self._closed:
            return
        if self.is_modified:
            self.save()
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
        """Close on normal exit; discard without writing when an exception exits."""
        if exc_type is None:
            self.close()
        else:
            self.discard()
