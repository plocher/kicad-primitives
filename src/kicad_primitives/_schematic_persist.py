"""Bounded same-location schematic persistence; no session/transaction framework."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from . import _symbol_persist
from .netlist import Netlist, obtain_netlist
from .schematics import (
    Schematic,
    SchematicConflictError,
    SchematicVerificationError,
    UnsupportedSchematicOperationError,
)

if TYPE_CHECKING:
    from .projects import Project


def _internal_path(project: Project, path: Path) -> Path:
    normalized = Path(os.path.abspath(path))
    if not normalized.is_relative_to(project.directory):
        raise UnsupportedSchematicOperationError(
            f"Save verification does not support external hierarchy paths: {path}"
        )
    if normalized.resolve() != normalized:
        raise UnsupportedSchematicOperationError(
            f"Save verification requires non-symlink paths: {path}"
        )
    return normalized


def _hierarchy(project: Project) -> tuple[Schematic, ...]:
    """Walk owned source strictly: missing/external sheets must not be omitted."""
    if project.schematic_file is None:
        return ()
    result: list[Schematic] = []
    visited: set[Path] = set()
    active: set[Path] = set()

    def visit(path: Path) -> None:
        path = _internal_path(project, path)
        if path in active:
            raise UnsupportedSchematicOperationError("Cyclic schematic hierarchy")
        if path in visited:
            return
        if not path.is_file():
            raise SchematicConflictError(f"Missing hierarchy schematic: {path}")
        schematic = project._load_schematic(path)
        result.append(schematic)
        visited.add(path)
        active.add(path)
        for sheet in schematic.sheets:
            filename = Path(sheet.filename)
            if filename.is_absolute() or "${" in sheet.filename:
                raise UnsupportedSchematicOperationError(
                    f"Unsupported Sheetfile for save verification: {sheet.filename}"
                )
            visit(path.parent / filename)
        active.remove(path)

    visit(project.schematic_file)
    return tuple(result)


def _preflight(
    project: Project, documents: tuple[Schematic, ...], changed: tuple[Schematic, ...]
) -> None:
    project.ensure_writes_allowed()
    _internal_path(project, project.project_file)
    _symbol_persist._check_baseline(
        project.project_file,
        project._project_baseline,
        conflict_error=SchematicConflictError,
        unsupported_error=UnsupportedSchematicOperationError,
        label="Project verification context",
    )
    for document in documents:
        _internal_path(project, document.path)
        info = _symbol_persist._check_baseline(
            document.path,
            document._baseline,
            conflict_error=SchematicConflictError,
            unsupported_error=UnsupportedSchematicOperationError,
            label="Schematic",
        )
        if document in changed:
            if document.version != 20260306:
                raise UnsupportedSchematicOperationError(
                    f"Schematic format {document.version} is read-only"
                )
            if not stat.S_IMODE(info.st_mode) & 0o222:
                raise PermissionError(
                    f"Schematic has no write permission bits: {document.path}"
                )


def _electrically_equal(before: Netlist, after: Netlist) -> bool:
    # Do not use connectivity_sets: it drops singleton nets and all names.
    before_nets = sorted(
        (
            net.name,
            sorted((n.reference, n.pin, n.pinfunction, n.pintype) for n in net.nodes),
        )
        for net in before.nets
    )
    after_nets = sorted(
        (
            net.name,
            sorted((n.reference, n.pin, n.pinfunction, n.pintype) for n in net.nodes),
        )
        for net in after.nets
    )
    before_components = sorted(
        (c.reference, c.lib, c.part, c.sheetpath) for c in before.components.values()
    )
    after_components = sorted(
        (c.reference, c.lib, c.part, c.sheetpath) for c in after.components.values()
    )
    return before_nets == after_nets and before_components == after_components


def _verify(
    project: Project,
    documents: tuple[Schematic, ...],
    changed: tuple[Schematic, ...],
    kicad_cli: str | os.PathLike[str] | None,
) -> None:
    root = project.schematic_file
    assert root is not None
    if root.stem != project.project_file.stem:
        raise UnsupportedSchematicOperationError(
            "Save verification requires matching root schematic and project basenames"
        )
    with TemporaryDirectory(prefix="kicad-primitives-schematic-") as temp:
        stage = Path(temp)
        (stage / project.project_file.name).write_bytes(project._project_baseline)
        for document in documents:
            target = stage / document.path.relative_to(project.directory)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(document._baseline)
        staged_root = stage / root.relative_to(project.directory)
        before = obtain_netlist(staged_root, kicad_cli=kicad_cli)
        for document in changed:
            (stage / document.path.relative_to(project.directory)).write_bytes(
                document.to_bytes()
            )
        after = obtain_netlist(staged_root, kicad_cli=kicad_cli)
        if not _electrically_equal(before, after):
            raise SchematicVerificationError(
                "Pending attributes change named nets, pin memberships or component identity; "
                "electrical edits are not supported by set_attribute"
            )


def save_schematics(
    project: Project,
    selected: tuple[Schematic, ...],
    *,
    kicad_cli: str | os.PathLike[str] | None,
) -> None:
    changed = tuple(document for document in selected if document.is_modified)
    if not selected:
        return
    _preflight(project, tuple(project._schematics.values()), changed)
    documents = _hierarchy(project)
    if any(document not in documents for document in selected):
        raise SchematicConflictError("Owned schematic is no longer in the hierarchy")
    _preflight(project, documents, changed)
    if not changed:
        return
    _verify(project, documents, changed, kicad_cli)
    # Verification can take time. Recheck ALL inputs, not only output files.
    _preflight(project, documents, changed)
    for document in changed:
        output = document.to_bytes()
        _symbol_persist.save_source(
            document.path,
            document._baseline,
            output,
            conflict_error=SchematicConflictError,
            unsupported_error=UnsupportedSchematicOperationError,
            label="Schematic",
        )
        object.__setattr__(document, "_baseline", output)
