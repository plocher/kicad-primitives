"""Inspect and edit explicit-path symbol libraries; parsing stays private."""

import subprocess
import tempfile
from os import PathLike
from pathlib import Path

from . import _symbol_parse, _symbol_persist
from ._kicad_cli import KicadCliNotFoundError, resolve_kicad_cli
from ._symbol_types import (
    AmbiguousPinError,
    AmbiguousPropertyError,
    AmbiguousSymbolError,
    FileConflictError,
    InheritanceError,
    InvalidLibraryError,
    Symbol,
    SymbolBody,
    SymbolLibraryError,
    SymbolPin,
    SymbolProperty,
    SymbolRectangle,
    SymbolText,
    UnsupportedOperationError,
)

__all__ = [
    "AmbiguousPinError",
    "AmbiguousPropertyError",
    "AmbiguousSymbolError",
    "FileConflictError",
    "InheritanceError",
    "InvalidLibraryError",
    "KicadCliNotFoundError",
    "Symbol",
    "SymbolBody",
    "SymbolLibrary",
    "SymbolLibraryError",
    "SymbolPin",
    "SymbolProperty",
    "SymbolRectangle",
    "SymbolText",
    "UnsupportedOperationError",
]


class SymbolLibrary:
    """One library with immutable inspection snapshots and explicit persistence."""

    def __init__(self, path: Path, raw: bytes) -> None:
        self._path = path
        self._source = _symbol_parse.read_source(raw)
        self._baseline = raw

    @classmethod
    def open(cls, path: str | PathLike[str]) -> "SymbolLibrary":
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
        return self._source.symbols

    def symbol(self, name: str) -> Symbol:
        """Inspect one declared snapshot; raise on missing or ambiguous identity."""
        return self._source.symbol(name)

    def resolve(self, name: str) -> Symbol:
        """Inspect effective inheritance, retaining declaration provenance."""
        return _symbol_parse.resolve(self._source, name)

    def to_bytes(self) -> bytes:
        """Preview current source bytes, including all opaque untouched content."""
        return self._source.document.render().encode("utf-8")

    def set_property(self, symbol_name: str, property_name: str, value: str) -> None:
        """Update one existing declared value in memory, never a parent implicitly.

        Missing properties, ambiguous targets and read-only formats fail without
        changing either memory or disk. Query again for a fresh snapshot.
        """
        updated = _symbol_parse.replace_property(
            self._source, symbol_name, property_name, value
        )
        self._source = updated

    def add_property(
        self,
        symbol_name: str,
        property_name: str,
        value: str,
        *,
        private: bool = False,
    ) -> None:
        """Insert one new declared property on the selected symbol in memory.

        Does not edit a parent or replace an existing identity. Ambiguous names,
        empty names, invalid values, and read-only formats fail without changing
        memory or disk. Query again for a fresh snapshot.
        """
        updated = _symbol_parse.insert_property(
            self._source,
            symbol_name,
            property_name,
            value,
            private=private,
        )
        self._source = updated

    def delete_property(self, symbol_name: str, property_name: str) -> None:
        """Remove one unambiguous declared property from the selected symbol.

        Does not edit a parent. Missing or ambiguous targets and read-only
        formats fail without changing memory or disk. Query again for a fresh
        snapshot.
        """
        updated = _symbol_parse.delete_property(
            self._source, symbol_name, property_name
        )
        self._source = updated

    def add_pin(
        self,
        symbol_name: str,
        unit: int,
        body_style: int,
        number: str,
        name: str,
        electrical_type: str,
        *,
        x: float,
        y: float,
        rotation: float = 0.0,
        length: float = 2.54,
        shape: str = "line",
        hidden: bool = False,
    ) -> None:
        """Insert one pin on an existing body without collapsing body styles.

        Targets `(unit, body_style)` on the selected symbol only. Does not create
        bodies or edit a parent. Duplicate pin numbers, missing bodies, invalid
        values, and read-only formats fail without changing memory or disk.
        """
        updated = _symbol_parse.insert_pin(
            self._source,
            symbol_name,
            unit,
            body_style,
            number,
            name,
            electrical_type,
            x=x,
            y=y,
            rotation=rotation,
            length=length,
            shape=shape,
            hidden=hidden,
        )
        self._source = updated

    def set_pin(
        self,
        symbol_name: str,
        unit: int,
        body_style: int,
        number: str,
        *,
        name: str | None = None,
        electrical_type: str | None = None,
        x: float | None = None,
        y: float | None = None,
        rotation: float | None = None,
        length: float | None = None,
        shape: str | None = None,
        hidden: bool | None = None,
    ) -> None:
        """Update selected fields of one existing pin on a body.

        Unspecified fields stay unchanged. Missing or ambiguous targets and
        read-only formats fail without changing memory or disk. Equal values are
        a lexical no-op. Query again for a fresh snapshot.
        """
        updated = _symbol_parse.replace_pin(
            self._source,
            symbol_name,
            unit,
            body_style,
            number,
            name=name,
            electrical_type=electrical_type,
            x=x,
            y=y,
            rotation=rotation,
            length=length,
            shape=shape,
            hidden=hidden,
        )
        self._source = updated

    def delete_pin(
        self,
        symbol_name: str,
        unit: int,
        body_style: int,
        number: str,
    ) -> None:
        """Remove one unambiguous pin from an existing body.

        Does not edit a parent or other body styles. Missing or ambiguous
        targets and read-only formats fail without changing memory or disk.
        """
        updated = _symbol_parse.delete_pin(
            self._source, symbol_name, unit, body_style, number
        )
        self._source = updated

    def create_symbol(self, name: str, *, extends: str | None = None) -> None:
        """Insert a new empty top-level symbol in this library.

        Optional ``extends`` must name an existing symbol in the same library.
        Duplicate names and read-only formats fail without changing memory or disk.
        """
        self._source = _symbol_parse.create_symbol(self._source, name, extends=extends)

    def rename_symbol(self, old_name: str, new_name: str) -> None:
        """Rename one symbol, rewrite body names, and update in-library extends.

        Equal names are a no-op. Missing/duplicate targets and read-only formats
        fail without changing memory or disk.
        """
        self._source = _symbol_parse.rename_symbol(self._source, old_name, new_name)

    def delete_symbol(self, name: str) -> None:
        """Remove one top-level symbol from this library.

        Refuses when another symbol still extends it. Missing targets and
        read-only formats fail without changing memory or disk.
        """
        self._source = _symbol_parse.delete_symbol(self._source, name)

    def copy_symbol(self, source_name: str, new_name: str) -> None:
        """Duplicate one symbol inside this library under a new name.

        Preserves properties, bodies, and extends. For a second library use
        :meth:`copy_symbol_from`.
        """
        self._source = _symbol_parse.copy_symbol(self._source, source_name, new_name)

    def copy_symbol_from(
        self,
        source_library: "SymbolLibrary",
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
        self._source = _symbol_parse.copy_symbol_from(
            self._source,
            source_library._source,
            source_name,
            new_name,
        )

    def ensure_body(self, symbol_name: str, unit: int, body_style: int) -> None:
        """Create an empty body when missing; no-op when already present.

        Prefer unit ``0`` for shared graphics instead of copying artwork into
        every placed unit. Does not edit a parent. Read-only formats fail
        without changing memory or disk.
        """
        self._source = _symbol_parse.ensure_body(
            self._source, symbol_name, unit, body_style
        )

    def add_rectangle(
        self,
        symbol_name: str,
        unit: int,
        body_style: int,
        *,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> None:
        """Insert a minimal rectangle on an existing body.

        Stroke/fill stay out of scope. Missing bodies and read-only formats fail
        without changing memory or disk. Put shared boxes on unit ``0``.
        """
        start_x, start_y = start
        end_x, end_y = end
        self._source = _symbol_parse.insert_rectangle(
            self._source,
            symbol_name,
            unit,
            body_style,
            start_x=start_x,
            start_y=start_y,
            end_x=end_x,
            end_y=end_y,
        )

    def add_body_text(
        self,
        symbol_name: str,
        unit: int,
        body_style: int,
        text: str,
        *,
        x: float,
        y: float,
        rotation: float = 0.0,
    ) -> None:
        """Insert minimal body text on an existing body.

        Full text-effects authoring is out of scope. Missing bodies and
        read-only formats fail without changing memory or disk.
        """
        self._source = _symbol_parse.insert_body_text(
            self._source,
            symbol_name,
            unit,
            body_style,
            text,
            x=x,
            y=y,
            rotation=rotation,
        )

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
