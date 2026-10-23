"""Inspect and edit explicit-path symbol libraries; parsing stays private."""

from os import PathLike
from pathlib import Path

from . import _symbol_parse
from ._symbol_types import (
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
        """Update an existing declared value in memory (not yet implemented)."""
        raise UnsupportedOperationError("Property editing is not implemented yet")

    def save(self) -> None:
        """Persist changed source explicitly (not yet implemented)."""
        raise UnsupportedOperationError("Persistence is not implemented yet")
