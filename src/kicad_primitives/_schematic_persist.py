"""Strict hierarchy paths and netlist evidence for project staging and save-as proof."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from lossless_sexpr import ListNode, ParseError, parse

from .schematics import (
    SchematicConflictError,
    SchematicVerificationError,
    SheetFile,
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
                    f"Unsupported Sheetfile for save verification: {sheet.filename}"
                )
    return files


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
