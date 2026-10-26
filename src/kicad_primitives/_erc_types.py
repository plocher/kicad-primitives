"""Typed report values reexported by schematic artifacts, not a checks service."""

from dataclasses import dataclass
from pathlib import Path


class ErcAcquisitionError(RuntimeError):
    """ERC execution or report intake failed, rather than reporting design findings."""


class ErcContextError(ErcAcquisitionError):
    """The original library context cannot be represented faithfully for ERC."""


@dataclass(frozen=True)
class ErcPosition:
    """Numeric item coordinates in the report's declared coordinate units."""

    x: float
    y: float


@dataclass(frozen=True)
class ErcItem:
    """One affected item, retaining its UUID, description, and coordinates."""

    uuid: str
    description: str
    position: ErcPosition


@dataclass(frozen=True)
class ErcViolation:
    """One KiCad violation without application severity or exclusion policy."""

    type: str
    description: str
    severity: str
    items: tuple[ErcItem, ...]
    excluded: bool | None
    exclusion_comment: str | None
    comment: str | None


@dataclass(frozen=True)
class ErcSheet:
    """One sheet group with raw human/UUID paths and proved original file origin."""

    path: str
    uuid_path: str
    source_path: Path | None
    violations: tuple[ErcViolation, ...]


@dataclass(frozen=True)
class ErcIgnoredCheck:
    """One check that KiCad's captured project settings mark as ignored."""

    key: str
    description: str


@dataclass(frozen=True)
class ErcDocumentSnapshot:
    """Original document path, exact checked content hash, and pending-change state."""

    path: Path
    sha256: str
    is_modified: bool


@dataclass(frozen=True)
class ErcSnapshot:
    """Checked in-memory source/settings and original library-registration provenance."""

    project_file: Path
    project_sha256: str
    documents: tuple[ErcDocumentSnapshot, ...]
    config_home: Path
    symbol_table_sha256: str
    footprint_table_sha256: str


@dataclass(frozen=True)
class ErcReport:
    """A full-project ERC result with original origin and immutable snapshot provenance."""

    source_path: Path
    source: str
    schema: str
    date: str
    kicad_version: str
    coordinate_units: str
    included_severities: tuple[str, ...]
    ignored_checks: tuple[ErcIgnoredCheck, ...]
    sheets: tuple[ErcSheet, ...]
    snapshot: ErcSnapshot
    stdout: str
    stderr: str
