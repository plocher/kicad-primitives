"""Strict hierarchy paths for project staging and save-as."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from .schematics import (
    SchematicConflictError,
    SheetFile,
    UnsupportedSchematicOperationError,
)

if TYPE_CHECKING:
    from .projects import Project


def _internal_path(project: Project, path: Path) -> Path:
    normalized = Path(os.path.abspath(path))
    if not normalized.is_relative_to(project.directory):
        raise UnsupportedSchematicOperationError(
            f"Project staging does not support external hierarchy paths: {path}"
        )
    if normalized.resolve() != normalized:
        raise UnsupportedSchematicOperationError(
            f"Project staging requires non-symlink paths: {path}"
        )
    return normalized


def _hierarchy(project: Project) -> tuple[SheetFile, ...]:
    """Return the loaded hierarchy, strict about missing and external sheets."""
    if project.schematic_file is None:
        return ()
    files = project.schematic().files
    for sheet_file in files:
        _internal_path(project, sheet_file.path)
        if not sheet_file.path.is_file():
            raise SchematicConflictError(
                f"Missing hierarchy schematic: {sheet_file.path}"
            )
        for sheet in sheet_file.sheet_symbols:
            if Path(sheet.filename).is_absolute():
                raise UnsupportedSchematicOperationError(
                    f"Unsupported Sheetfile for project staging: {sheet.filename}"
                )
    return files
