"""Dependency-free symbol views and errors, exported by the functional service."""

from dataclasses import dataclass

_MANDATORY = frozenset({"reference", "value", "footprint", "datasheet", "description"})


def _property_key(name: str) -> str:
    return name.casefold() if name.casefold() in _MANDATORY else name


class SymbolLibraryError(Exception):
    """Base error for symbol-library operations."""


class InvalidLibraryError(SymbolLibraryError, ValueError):
    """The input is not a structurally valid supported symbol library."""


class UnsupportedOperationError(SymbolLibraryError, NotImplementedError):
    """The requested operation or format is not supported."""


class AmbiguousPropertyError(SymbolLibraryError, ValueError):
    """More than one declared property matches the requested identity."""


class AmbiguousSymbolError(SymbolLibraryError, ValueError):
    """More than one top-level symbol has the requested name."""


class AmbiguousPinError(SymbolLibraryError, ValueError):
    """More than one pin in the selected body matches the requested number."""


class InheritanceError(SymbolLibraryError, ValueError):
    """An effective definition cannot be established safely."""


class FileConflictError(SymbolLibraryError, RuntimeError):
    """The opened file has changed since the last successful read/save."""


@dataclass(frozen=True)
class SymbolProperty:
    """One property occurrence; origin identifies its declaring symbol."""

    name: str
    value: str
    origin_symbol: str
    is_private: bool = False
    hidden: bool = False
    autoplace: bool = True
    x: float | None = None
    y: float | None = None
    rotation: float | None = None


@dataclass(frozen=True)
class SymbolPin:
    """One pin within its containing body's unit and body style."""

    number: str
    name: str
    electrical_type: str
    x: float
    y: float
    rotation: float
    length: float
    shape: str
    hidden: bool = False


@dataclass(frozen=True)
class SymbolBody:
    """A declared body; zero unit/style means common, not an extra placed unit."""

    name: str
    unit: int
    body_style: int
    pins: tuple[SymbolPin, ...]
    origin_symbol: str

    def pin(self, number: str) -> SymbolPin:
        """Get one pin by number within this body; raise if missing or ambiguous."""
        matches = tuple(p for p in self.pins if p.number == number)
        if not matches:
            raise KeyError(number)
        if len(matches) != 1:
            raise AmbiguousPinError(f"{self.name}: ambiguous pin number {number!r}")
        return matches[0]


@dataclass(frozen=True)
class Symbol:
    """Immutable declared or effective snapshot; graphics remain opaque source."""

    name: str
    extends: str | None
    properties: tuple[SymbolProperty, ...]
    bodies: tuple[SymbolBody, ...]
    units_locked: bool = False
    resolved: bool = False

    def property(self, name: str) -> SymbolProperty:
        """Get one property; mandatory names use KiCad's case-insensitive identity."""
        matches = tuple(
            p for p in self.properties if _property_key(p.name) == _property_key(name)
        )
        if not matches:
            raise KeyError(name)
        if len(matches) != 1:
            raise AmbiguousPropertyError(f"{self.name}: ambiguous property {name!r}")
        return matches[0]

    def body(self, unit: int, body_style: int) -> SymbolBody:
        """Get one body by unit and body-style identity; raise if missing."""
        matches = tuple(
            b for b in self.bodies if b.unit == unit and b.body_style == body_style
        )
        if not matches:
            raise KeyError((unit, body_style))
        if len(matches) != 1:
            raise InvalidLibraryError(
                f"{self.name}: duplicate unit/body style {(unit, body_style)!r}"
            )
        return matches[0]
