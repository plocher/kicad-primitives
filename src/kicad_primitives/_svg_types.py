"""Typed schematic SVG export values reexported by the schematics module."""

from dataclasses import dataclass
from pathlib import Path

from ._snapshot_types import ProjectSnapshot


class SchematicSvgError(RuntimeError):
    """SVG export execution or output intake failed; nothing is an empty result."""


@dataclass(frozen=True)
class SchematicSvgFile:
    """One produced SVG and its proved sheet mapping.

    ``sheet_path`` is the human sheet path (``"/"`` for the root, ``"/A/B/"``
    for nested sheets). ``source_path`` is the original schematic file. Both are
    ``None`` when the package cannot prove the mapping from the file name.
    """

    path: Path
    sheet_path: str | None
    source_path: Path | None


@dataclass(frozen=True)
class SchematicSvgExport:
    """Files written to a new output directory from one pending snapshot."""

    output_dir: Path
    files: tuple[SchematicSvgFile, ...]
    snapshot: ProjectSnapshot
    stdout: str
    stderr: str
