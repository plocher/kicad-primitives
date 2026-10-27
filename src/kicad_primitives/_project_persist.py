"""Project-owned file-set save, with explicit partial-I/O limits."""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from lossless_sexpr import ListNode, ParseError, parse

from . import _project_backup, _schematic_persist, _symbol_persist
from .projects import (
    InvalidProjectError,
    ProjectBackupError,
    ProjectLifecycleError,
    _find_companion,
)
from .schematics import SchematicConflictError, UnsupportedSchematicOperationError

if TYPE_CHECKING:
    from .projects import Project
    from .schematics import Schematic


def _context(project: Project) -> None:
    if not isinstance(json.loads(project._project_baseline), dict):
        raise UnsupportedSchematicOperationError(
            "Project settings must be a JSON object"
        )
    for suffix, expected in (
        (".kicad_sch", project.schematic_file),
        (".kicad_pcb", project.pcb_file),
    ):
        actual = _find_companion(
            project.directory, project.base_name, project.directory.name, suffix
        )
        if actual != expected:
            raise SchematicConflictError(
                f"Project companion membership changed: {suffix}"
            )
    if project.pcb_file is not None:
        path = _schematic_persist._internal_path(project, project.pcb_file)
        assert project._pcb_baseline is not None
        _symbol_persist._check_baseline(
            path,
            project._pcb_baseline,
            conflict_error=SchematicConflictError,
            unsupported_error=UnsupportedSchematicOperationError,
            label="Project PCB",
        )
        try:
            roots = parse(project._pcb_baseline.decode("utf-8")).roots()
        except (UnicodeError, ParseError, RecursionError) as exc:
            raise InvalidProjectError("Invalid raw PCB companion syntax") from exc
        if (
            len(roots) != 1
            or not isinstance(roots[0], ListNode)
            or roots[0].head != "kicad_pcb"
        ):
            raise UnsupportedSchematicOperationError("Expected one native PCB root")
        versions = roots[0].child_lists("version")
        if len(versions) != 1:
            raise UnsupportedSchematicOperationError("Expected one PCB version")
        version = versions[0].atom(1)
        if (
            version is None
            or not version.value.isascii()
            or not version.value.isdecimal()
            or len(version.value) != 8
        ):
            raise UnsupportedSchematicOperationError(
                "Expected an eight-digit PCB format"
            )
        if int(version.value) > 20260206:
            raise UnsupportedSchematicOperationError("Unsupported future PCB format")


def _accept_saved(document: Schematic, output: bytes) -> None:
    """Advance the written baseline without replacing newer pending source/intents."""
    from ._schematic_restore import _cache_nodes, _inventory

    object.__setattr__(document, "_baseline", output)
    if not document._restore_intents:
        return
    baseline = parse(output.decode("utf-8"))
    nodes = _cache_nodes(baseline)
    for key, intent in tuple(document._restore_intents.items()):
        node = nodes[key]
        chunk = baseline.source[node.span.start : node.span.end]
        if chunk == intent.requested_chunk:
            document._restore_intents.pop(key, None)
        else:
            pins, _ = _inventory(node, key.rsplit(":", 1)[-1])
            document._restore_intents[key] = replace(intent, baseline_pins=pins)


def save_project(
    project: Project,
    selected: tuple[Schematic, ...] | None,
    *,
    kicad_cli: str | os.PathLike[str] | None,
) -> None:
    """Persist frozen selected outputs and a complete actual post-save snapshot."""
    project._check_open()
    authorized = project._close_authorized
    project._close_authorized = False
    generation = project._generation
    cached = tuple(project._schematics.values())
    initial_targets = cached if selected is None else selected
    _schematic_persist._preflight(
        project, cached, tuple(d for d in initial_targets if d.is_modified)
    )
    _context(project)
    documents = _schematic_persist._hierarchy(project)
    targets = documents if selected is None else selected
    if any(document not in documents for document in (*cached, *targets)):
        raise SchematicConflictError(
            "Owned schematic is no longer in the complete hierarchy"
        )
    if any(d.version != 20260306 for d in documents):
        raise UnsupportedSchematicOperationError(
            "Project persistence requires supported schematic formats"
        )
    outputs = {d.path: d.to_bytes() if d in targets else d._baseline for d in documents}
    if project._generation != generation:
        raise ProjectLifecycleError(
            "Pending Project state changed during file-set preparation"
        )
    changed = tuple(d for d in targets if outputs[d.path] != d._baseline)
    _schematic_persist._preflight(project, documents, changed)
    if changed:
        _schematic_persist._verify(project, documents, changed, kicad_cli)
    if project._generation != generation:
        raise ProjectLifecycleError(
            "Pending Project state changed during save verification"
        )
    outputs[project.project_file] = project._project_baseline
    if project.pcb_file is not None:
        assert project._pcb_baseline is not None
        outputs[project.pcb_file] = project._pcb_baseline
    try:
        snapshot = _project_backup.prepare(project, outputs, tuple(outputs))
        if project._generation != generation:
            raise ProjectLifecycleError(
                "Pending Project state changed during snapshot preparation"
            )
        _schematic_persist._preflight(project, documents, changed)
        _context(project)
        written: dict[Path, os.stat_result] = {}
        _project_backup.check_fresh(project, snapshot, written)
        for document in changed:
            project._check_open()
            _project_backup.check_fresh(project, snapshot, written)
            output = outputs[document.path]
            installed = _symbol_persist.save_source(
                document.path,
                document._baseline,
                output,
                conflict_error=SchematicConflictError,
                unsupported_error=UnsupportedSchematicOperationError,
                label="Schematic",
            )
            _accept_saved(document, output)
            written[document.path] = installed
        project._check_open()
        _project_backup.check_fresh(project, snapshot, written)
        _project_backup.publish(project, snapshot)
        _project_backup.check_fresh(project, snapshot, written)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        if isinstance(exc, ProjectBackupError):
            raise
        raise ProjectBackupError(
            "Project save/history failed; successfully persisted files keep their new baselines"
        ) from exc
    project._check_open()
    if project._generation != generation:
        raise ProjectLifecycleError(
            "A newer pending Project state was not settled by this save"
        )
    project._close_authorized = selected is None or (
        authorized and not project.is_modified
    )
