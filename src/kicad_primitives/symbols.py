"""Inspect and edit explicit-path symbol libraries; parsing stays private."""

from __future__ import annotations

import subprocess
import tempfile
from os import PathLike
from pathlib import Path

from . import _symbol_parse, _symbol_persist
from ._kicad_cli import KicadCliNotFoundError, resolve_kicad_cli
from ._symbol_live import StaleSymbolError, Symbol, SymbolBody, SymbolPin
from ._symbol_types import (
    AmbiguousAttributeError,
    AmbiguousPinError,
    AmbiguousSymbolError,
    FileConflictError,
    InheritanceError,
    InvalidLibraryError,
    SymbolAttribute,
    SymbolDefinition,
    SymbolLibraryError,
    SymbolRectangle,
    SymbolText,
    UnsupportedOperationError,
)

__all__ = [
    "AmbiguousAttributeError",
    "AmbiguousPinError",
    "AmbiguousSymbolError",
    "FileConflictError",
    "InheritanceError",
    "InvalidLibraryError",
    "KicadCliNotFoundError",
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
    "UnsupportedOperationError",
]


class SymbolLibrary:
    """One source library with stable editable symbols and explicit persistence."""

    def __init__(self, path: Path, raw: bytes) -> None:
        self._path = path
        self._source = _symbol_parse.read_source(raw)
        self._baseline = raw
        self._symbols = tuple(Symbol(self, data) for data in self._source.symbols)

    def _accept_source(
        self,
        updated: _symbol_parse.ParsedLibrary,
        *,
        renamed: tuple[str, str] | None = None,
    ) -> None:
        if updated is self._source:
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

    @classmethod
    def open(cls, path: str | PathLike[str]) -> SymbolLibrary:
        """Read a library at an explicit path; no discovery or project is needed."""
        location = Path(path).absolute()
        return cls(location, location.read_bytes())

    @property
    def version(self) -> int:
        """The file's declared format version, not its generator version."""
        return self._source.version

    @property
    def symbols(self) -> tuple[Symbol, ...]:
        """Declared definitions in file order; repeated names are not discarded."""
        return self._symbols

    def symbol(self, name: str) -> Symbol:
        """Select one live declared symbol; reject missing or ambiguous identity."""
        data = self._source.symbol(name)
        return self._symbols[self._source.symbols.index(data)]

    def resolve(self, name: str) -> SymbolDefinition:
        """Inspect effective inheritance, retaining declaration provenance."""
        return _symbol_parse.resolve(self._source, name)

    def to_bytes(self) -> bytes:
        """Preview current source bytes, including all opaque untouched content."""
        return self._source.document.render().encode("utf-8")

    def create_symbol(self, name: str, *, extends: str | None = None) -> None:
        """Insert a new empty top-level symbol in this library.

        Optional ``extends`` must name an existing symbol in the same library.
        Duplicate names and read-only formats fail without changing memory or disk.
        """
        self._accept_source(
            _symbol_parse.create_symbol(self._source, name, extends=extends)
        )

    def rename_symbol(self, old_name: str, new_name: str) -> None:
        """Rename one symbol, rewrite body names, and update in-library extends.

        Equal names are a no-op. Missing/duplicate targets and read-only formats
        fail without changing memory or disk.
        """
        updated = _symbol_parse.rename_symbol(self._source, old_name, new_name)
        self._accept_source(updated, renamed=(old_name, new_name))

    def delete_symbol(self, name: str) -> None:
        """Remove one top-level symbol from this library.

        Refuses when another symbol still extends it. Missing targets and
        read-only formats fail without changing memory or disk.
        """
        self._accept_source(_symbol_parse.delete_symbol(self._source, name))

    def copy_symbol(self, source_name: str, new_name: str) -> None:
        """Duplicate one symbol inside this library under a new name.

        Preserves attributes, bodies, and extends. For a second library use
        :meth:`copy_symbol_from`.
        """
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

    def save(self) -> None:
        """Persist to the opened path after an optimistic conflict check.

        Changed output replaces a regular singly linked file atomically; no-op
        saves perform no replacement. This is not coordination with KiCad or
        another writer: a final check/replace race remains possible. OS errors
        propagate; unsuccessful saves retain edits in memory for inspection/retry.
        """
        if self.version != _symbol_parse.WRITE_VERSION:
            raise UnsupportedOperationError(f"Format {self.version} is read-only")
        output = self.to_bytes()
        _symbol_persist.save_source(self._path, self._baseline, output)
        self._baseline = output
