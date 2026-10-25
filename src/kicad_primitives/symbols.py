"""Inspect and edit explicit-path symbol libraries; parsing stays private."""

from os import PathLike
from pathlib import Path

from . import _symbol_parse, _symbol_persist
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
    UnsupportedOperationError,
)

__all__ = [
    "AmbiguousPinError",
    "AmbiguousPropertyError",
    "AmbiguousSymbolError",
    "FileConflictError",
    "InheritanceError",
    "InvalidLibraryError",
    "Symbol",
    "SymbolBody",
    "SymbolLibrary",
    "SymbolLibraryError",
    "SymbolPin",
    "SymbolProperty",
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
