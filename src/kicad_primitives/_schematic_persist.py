"""Bounded same-location schematic persistence; no session/transaction framework."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from lossless_sexpr import ListNode, ParseError, parse

from . import _symbol_persist
from ._schematic_restore import predict_restored_signature
from .netlist import export_netlist
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
            parent = document.path.parent
            mode = stat.S_IMODE(parent.stat().st_mode)
            if (
                not mode & 0o222
                or not mode & 0o111
                or not os.access(parent, os.W_OK | os.X_OK)
            ):
                raise PermissionError(
                    f"Schematic destination directory is not writable: {parent}"
                )


@dataclass(frozen=True)
class _ElectricalSignature:
    components: tuple[tuple[str, str, str, str], ...]
    nets: tuple[tuple[str, tuple[tuple[str, str, str, str], ...]], ...]
    libparts: tuple[tuple[str, str, tuple[tuple[str, str, str], ...]], ...] = ()


def _required_list(node: ListNode, head: str) -> ListNode:
    matches = node.child_lists(head)
    if len(matches) != 1:
        raise SchematicVerificationError(
            f"Incomplete or ambiguous netlist evidence: {head}"
        )
    return matches[0]


def _evidence_value(node: ListNode, head: str, *, optional: bool = False) -> str:
    matches = node.child_lists(head)
    if optional and not matches:
        return ""
    item = _required_list(node, head)
    value = item.atom(1)
    if value is None or len(item.children()) != 2:
        raise SchematicVerificationError(f"Invalid netlist evidence value: {head}")
    return value.value


def _electrical_signature(
    path: Path, *, include_libparts: bool = False
) -> _ElectricalSignature:
    """Validate raw proof before any model can discard ambiguous occurrences."""
    try:
        document = parse(path.read_bytes().decode("utf-8"))
    except (UnicodeError, ParseError, RecursionError) as exc:
        raise SchematicVerificationError(f"Invalid netlist evidence: {exc}") from exc
    roots = document.roots()
    if (
        len(roots) != 1
        or not isinstance(roots[0], ListNode)
        or roots[0].head != "export"
    ):
        raise SchematicVerificationError("Expected one netlist export root")
    root = roots[0]
    if not _evidence_value(root, "version"):
        raise SchematicVerificationError("Missing netlist evidence version")
    components = _required_list(root, "components")
    nets = _required_list(root, "nets")
    identities: list[tuple[str, str, str, str]] = []
    references: set[str] = set()
    for component in components.children()[1:]:
        if not isinstance(component, ListNode) or component.head != "comp":
            raise SchematicVerificationError("Invalid component evidence")
        reference = _evidence_value(component, "ref")
        if not reference or reference in references:
            raise SchematicVerificationError(
                f"Missing or duplicate component reference: {reference!r}"
            )
        references.add(reference)
        library = _required_list(component, "libsource")
        part = _evidence_value(library, "part")
        if not part:
            raise SchematicVerificationError("Missing component part identity")
        paths = component.child_lists("sheetpath")
        if len(paths) > 1:
            raise SchematicVerificationError("Ambiguous component sheet path")
        sheetpath = _evidence_value(paths[0], "names") if paths else ""
        identities.append((reference, _evidence_value(library, "lib"), part, sheetpath))
    named_nets: list[tuple[str, tuple[tuple[str, str, str, str], ...]]] = []
    for net in nets.children()[1:]:
        if not isinstance(net, ListNode) or net.head != "net":
            raise SchematicVerificationError("Invalid net evidence")
        name = _evidence_value(net, "name")
        nodes: list[tuple[str, str, str, str]] = []
        for node in net.child_lists("node"):
            reference = _evidence_value(node, "ref")
            pin = _evidence_value(node, "pin")
            if not reference or not pin or reference not in references:
                raise SchematicVerificationError("Incomplete pin attachment evidence")
            nodes.append(
                (
                    reference,
                    pin,
                    _evidence_value(node, "pinfunction", optional=True),
                    _evidence_value(node, "pintype", optional=True),
                )
            )
        named_nets.append((name, tuple(sorted(nodes))))
    libparts: list[tuple[str, str, tuple[tuple[str, str, str], ...]]] = []
    if include_libparts:
        parts = _required_list(root, "libparts")
        keys: set[tuple[str, str]] = set()
        for part_node in parts.children()[1:]:
            if not isinstance(part_node, ListNode) or part_node.head != "libpart":
                raise SchematicVerificationError("Invalid library-part proof")
            lib, name = (
                _evidence_value(part_node, "lib"),
                _evidence_value(part_node, "part"),
            )
            if (lib, name) in keys or not name:
                raise SchematicVerificationError("Ambiguous library-part proof")
            keys.add((lib, name))
            pins: list[tuple[str, str, str]] = []
            for pin_node in _required_list(part_node, "pins").children()[1:]:
                if not isinstance(pin_node, ListNode) or pin_node.head != "pin":
                    raise SchematicVerificationError("Invalid library pin proof")
                number = _evidence_value(pin_node, "num")
                electrical_type = _evidence_value(pin_node, "type")
                if not number or not electrical_type:
                    raise SchematicVerificationError("Incomplete library pin proof")
                pins.append(
                    (number, _evidence_value(pin_node, "name"), electrical_type)
                )
            libparts.append((lib, name, tuple(sorted(pins))))
    return _ElectricalSignature(
        tuple(sorted(identities)), tuple(sorted(named_nets)), tuple(sorted(libparts))
    )


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
        before_path = export_netlist(
            staged_root, stage / "before.net", kicad_cli=kicad_cli
        )
        include_libparts = any(document._restore_intents for document in changed)
        before = _electrical_signature(before_path, include_libparts=include_libparts)
        expected = predict_restored_signature(before, documents, changed)
        for document in changed:
            (stage / document.path.relative_to(project.directory)).write_bytes(
                document.to_bytes()
            )
        after_path = export_netlist(
            staged_root, stage / "after.net", kicad_cli=kicad_cli
        )
        after = _electrical_signature(after_path, include_libparts=include_libparts)
        if expected != after:
            raise SchematicVerificationError(
                "Pending content does not match the independently predicted electrical signature"
            )


def save_schematics(
    project: Project,
    selected: tuple[Schematic, ...],
    *,
    kicad_cli: str | os.PathLike[str] | None,
) -> None:
    """Save selected documents through their owning Project's snapshot safety net."""
    from ._project_persist import save_project

    save_project(project, selected, kicad_cli=kicad_cli)
