"""Dependency-free provenance values for project pending-snapshot outputs."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SnapshotDocument:
    """One original schematic path, its exact checked-content hash, and pending state."""

    path: Path
    sha256: str
    is_modified: bool


@dataclass(frozen=True)
class ProjectSnapshot:
    """Project settings and hierarchy content that a report or export used.

    ``project_sha256`` hashes the captured ``.kicad_pro`` bytes. Each document
    hashes the in-memory ``to_bytes()`` content that was staged, so callers can
    compare it with current content to judge freshness.
    """

    project_file: Path
    project_sha256: str
    documents: tuple[SnapshotDocument, ...]
