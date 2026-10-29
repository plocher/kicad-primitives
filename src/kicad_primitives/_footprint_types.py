"""Dependency-free footprint views and errors, exported by the functional service."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ._symbol_types import UnsupportedOperationError

_MANDATORY = frozenset({"reference", "value", "datasheet", "description"})
_COPPER_SUFFIX = ".Cu"


def _attribute_key(name: str) -> str:
    return name.casefold() if name.casefold() in _MANDATORY else name


class FootprintLibraryError(Exception):
    """Base error for footprint-library operations."""


class InvalidFootprintError(FootprintLibraryError, ValueError):
    """A file is not a structurally valid supported footprint."""


class AmbiguousFootprintAttributeError(FootprintLibraryError, ValueError):
    """More than one attribute matches the requested identity."""


class FootprintConflictError(FootprintLibraryError, RuntimeError):
    """The file on disk is not the file this footprint read or last wrote."""


class FootprintLifecycleError(FootprintLibraryError, RuntimeError):
    """A library or footprint is closed, discarded, deleted, or stale."""


@dataclass(frozen=True)
class FootprintAttribute:
    """One ``(property …)`` on a footprint: a named text value."""

    name: str
    value: str
    layer: str | None = None
    hidden: bool = False


@dataclass(frozen=True)
class PadDrill:
    """Drill of a through-hole or NPTH pad; ``width == height`` for a round hole."""

    width: float
    height: float
    oval: bool = False


@dataclass(frozen=True)
class Pad:
    """One ``(pad …)`` node as immutable data.

    ``number`` is the pad name text (empty for unnamed mechanical pads).
    ``pad_type`` is KiCad's token: ``smd``, ``thru_hole``, ``np_thru_hole``,
    or ``connect``. ``rotation`` is zero when the file omits it.
    """

    number: str
    pad_type: str
    shape: str
    x: float
    y: float
    rotation: float
    width: float
    height: float
    layers: tuple[str, ...]
    drill: PadDrill | None = None

    @property
    def on_copper(self) -> bool:
        """Whether any layer of this pad is a copper layer (``*.Cu``)."""
        return any(layer.endswith(_COPPER_SUFFIX) for layer in self.layers)


@dataclass(frozen=True)
class FootprintSummary:
    """Immutable table-of-contents row for one ``.kicad_mod`` file.

    ``name`` is the file stem, which is the footprint's identity in KiCad.
    ``declared_name`` is the name atom inside the file; KiCad overwrites it
    with the stem on load. ``footprint_type`` is ``smd``, ``through_hole``, or
    ``unspecified``; ``flags`` holds the other ``(attr …)`` tokens such as
    ``exclude_from_bom``.
    """

    name: str
    declared_name: str
    version: int
    description: str
    tags: str
    attributes: tuple[FootprintAttribute, ...]
    footprint_type: str
    flags: frozenset[str]
    pad_count: int
    unique_pad_count: int
    path: Path

    def attribute(self, name: str) -> FootprintAttribute:
        """Get one attribute; mandatory names use KiCad's case-insensitive identity."""
        return _select_attribute(self.attributes, name, self.name)

    def matches_filters(
        self, patterns: Iterable[str], *, nickname: str | None = None
    ) -> bool:
        """Apply symbol ``ki_fp_filters`` patterns as KiCad 10.0.1 does."""
        return matches_filters(self.name, patterns, nickname=nickname)


@dataclass(frozen=True)
class FootprintFailure:
    """One file that could not be read as a footprint; the library kept the rest."""

    name: str
    path: Path
    error: str


def _select_attribute(
    attributes: tuple[FootprintAttribute, ...], name: str, owner: str
) -> FootprintAttribute:
    matches = tuple(
        a for a in attributes if _attribute_key(a.name) == _attribute_key(name)
    )
    if not matches:
        raise KeyError(name)
    if len(matches) != 1:
        raise AmbiguousFootprintAttributeError(f"{owner}: ambiguous attribute {name!r}")
    return matches[0]


def unique_pad_count(pads: Iterable[Pad]) -> int:
    """Count unique non-empty pad numbers on copper, NPTH excluded.

    This is ``FOOTPRINT::GetUniquePadCount(DO_NOT_INCLUDE_NPTH)`` in KiCad
    10.0.1 (``pcbnew/footprint.cpp:2525-2559``): a pad with no copper layer or
    no number is skipped, and a ganged name such as ``A1_B12`` is one number.
    """
    numbers = {
        pad.number
        for pad in pads
        if pad.on_copper and pad.number and pad.pad_type != "np_thru_hole"
    }
    return len(numbers)


def _wildcard_regex(pattern: str) -> re.Pattern[str]:
    parts: list[str] = ["^"]
    for char in pattern:
        if char == "?":
            parts.append(".")
        elif char == "*":
            parts.append(".*")
        else:
            parts.append(re.escape(char))
    parts.append("$")
    return re.compile("".join(parts), re.DOTALL)


def matches_filters(
    name: str, patterns: Iterable[str], *, nickname: str | None = None
) -> bool:
    """Match a footprint name against ``ki_fp_filters`` as KiCad 10.0.1 does.

    Each pattern is an anchored, case-insensitive wildcard (``?`` one
    character, ``*`` any run). When a pattern contains ``:`` the candidate is
    ``nickname:name``; otherwise it is the bare name
    (``common/footprint_filter.cpp:126-148``). No patterns means no filter,
    so every footprint matches.
    """
    terms = [p for p in patterns if p]
    if not terms:
        return True
    bare = name.lower()
    qualified = f"{(nickname or '').lower()}:{bare}"
    for term in terms:
        candidate = qualified if ":" in term else bare
        if _wildcard_regex(term.lower()).search(candidate):
            return True
    return False


__all__ = [
    "AmbiguousFootprintAttributeError",
    "FootprintAttribute",
    "FootprintConflictError",
    "FootprintFailure",
    "FootprintLibraryError",
    "FootprintLifecycleError",
    "FootprintSummary",
    "InvalidFootprintError",
    "Pad",
    "PadDrill",
    "UnsupportedOperationError",
    "matches_filters",
    "unique_pad_count",
]
