"""Known Project identity spans, not general schematic or PCB editing."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from lossless_sexpr import AtomNode, ListNode, TextEdit, apply_edits, parse, quote

from .projects import InvalidProjectError
from .schematics import Schematic


def _atom(node: ListNode, index: int) -> AtomNode:
    value = node.atom(index)
    if value is None:
        raise InvalidProjectError(f"Missing native {node.head} metadata atom")
    return value


def _root(raw: bytes, head: str) -> ListNode:
    roots = parse(raw.decode("utf-8")).roots()
    if len(roots) != 1 or not isinstance(roots[0], ListNode) or roots[0].head != head:
        raise InvalidProjectError(f"Expected one native {head} identity root")
    return roots[0]


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise InvalidProjectError(
            "Project identity requires unambiguous native UUIDs"
        ) from exc


def _uuid_path(value: str) -> tuple[str, ...]:
    if not value.startswith("/"):
        raise InvalidProjectError("Expected an absolute native UUID instance path")
    return tuple(_uuid(part) for part in value.strip("/").split("/"))


def ownership(
    documents: tuple[Schematic, ...], source_root: Path
) -> tuple[str, dict[Path, set[tuple[str, ...]]]]:
    """Derive every owned sheet-instance path from the selected native hierarchy."""
    by_path = {document.path: document for document in documents}
    root = _root(by_path[source_root].to_bytes(), "kicad_sch")
    roots = root.child_lists("uuid")
    if len(roots) != 1:
        raise InvalidProjectError("Save-as requires one root schematic UUID")
    root_uuid = _uuid(_atom(roots[0], 1).value)
    paths: dict[Path, set[tuple[str, ...]]] = {path: set() for path in by_path}

    def visit(path: Path, chain: tuple[str, ...], active: frozenset[Path]) -> None:
        if path in active:
            raise InvalidProjectError("Cyclic identity hierarchy")
        paths[path].add(chain)
        for sheet in by_path[path].sheets:
            child = (path.parent / sheet.filename).resolve()
            if child not in by_path:
                raise InvalidProjectError("Identity hierarchy is incomplete")
            visit(child, (*chain, _uuid(sheet.uuid)), active | {path})

    visit(source_root, (root_uuid,), frozenset())
    return root_uuid, paths


def schematic(
    raw: bytes,
    *,
    old_name: str,
    new_name: str,
    root_uuid: str,
    owned_paths: set[tuple[str, ...]],
) -> bytes:
    """Rename only known project groups whose complete path set is owned."""
    text = raw.decode("utf-8")
    root = _root(raw, "kicad_sch")
    owners = (root, *root.child_lists("symbol"), *root.child_lists("sheet"))
    edits: list[TextEdit] = []
    for owner in owners:
        containers = owner.child_lists("instances")
        if len(containers) > 1:
            raise InvalidProjectError("Ambiguous native instance containers")
        for container in containers:
            for group in container.child_lists("project"):
                label = _atom(group, 1)
                if label.value not in {old_name, new_name}:
                    continue
                rows = group.child_lists("path")
                if not rows:
                    raise InvalidProjectError(
                        "Project instance group has no path provenance"
                    )
                paths = tuple(_uuid_path(_atom(row, 1).value) for row in rows)
                own = tuple(path in owned_paths for path in paths)
                if any(
                    path[0] == root_uuid and path not in owned_paths for path in paths
                ):
                    raise InvalidProjectError(
                        "Current-project path has unprovable document ownership"
                    )
                if not any(own):
                    continue
                if not all(own):
                    raise InvalidProjectError(
                        "Mixed owned/foreign instance paths are unsupported"
                    )
                if label.value == new_name and new_name != old_name:
                    raise InvalidProjectError(
                        "Destination project identity already owns instance paths"
                    )
                if label.value != new_name:
                    edits.append(TextEdit(label.span, quote(new_name)))
    return apply_edits(text, edits).encode("utf-8")


def pcb(
    raw: bytes,
    *,
    documents: tuple[Schematic, ...],
    owned_paths: Mapping[Path, set[tuple[str, ...]]],
    source_directory: Path,
    destination_directory: Path,
    targets: Mapping[Path, Path],
    root_uuid: str,
) -> bytes:
    """Update only uniquely proved footprint sheet filenames; preserve other board data."""
    text = raw.decode("utf-8")
    root = _root(raw, "kicad_pcb")
    versions = root.child_lists("version")
    if len(versions) != 1 or _atom(versions[0], 1).value != "20260206":
        raise InvalidProjectError("PCB relocation requires native format 20260206")
    if root.child_lists("module"):
        raise InvalidProjectError("Legacy PCB module relocation is unsupported")
    placements: dict[tuple[str, ...], set[Path]] = {}
    for document in documents:
        for symbol in document.symbols:
            symbol_uuid = _uuid(symbol.uuid)
            placements.setdefault((symbol_uuid,), set()).add(document.path)
            for chain in owned_paths[document.path]:
                placements.setdefault((*chain, symbol_uuid), set()).add(document.path)
    edits: list[TextEdit] = []
    for footprint in root.child_lists("footprint"):
        filenames = [_atom(node, 1) for node in footprint.child_lists("sheetfile")]
        names = [_atom(node, 1) for node in footprint.child_lists("sheetname")]
        for prop in footprint.child_lists("property"):
            key = _atom(prop, 1).value
            if key == "Sheetfile":
                filenames.append(_atom(prop, 2))
            elif key == "Sheetname":
                names.append(_atom(prop, 2))
        if (
            len({atom.value for atom in filenames}) > 1
            or len({atom.value for atom in names}) > 1
        ):
            raise InvalidProjectError("Conflicting PCB sheet provenance forms")
        references = footprint.child_lists("path")
        if not references:
            if any(
                atom.value
                in {path.name for path in targets if targets[path].name != path.name}
                for atom in filenames
            ):
                raise InvalidProjectError(
                    "Mapped PCB sheet filename lacks UUID provenance"
                )
            continue
        if len(references) != 1:
            raise InvalidProjectError("Ambiguous PCB footprint UUID path")
        chain = _uuid_path(_atom(references[0], 1).value)
        matches = placements.get(chain, set())
        if not matches:
            if chain[0] == root_uuid or any(
                atom.value
                in {path.name for path in targets if targets[path].name != path.name}
                for atom in filenames
            ):
                raise InvalidProjectError(
                    "PCB filename relocation has unproved placement ownership"
                )
            continue
        if len(matches) != 1:
            raise InvalidProjectError("PCB placement provenance is ambiguous")
        source = next(iter(matches))
        target = targets[source]
        for atom in filenames:
            if atom.value == source.name:
                replacement = target.name
            elif atom.value == source.relative_to(source_directory).as_posix():
                replacement = target.relative_to(destination_directory).as_posix()
            elif (
                Path(atom.value).is_absolute() and Path(atom.value).resolve() == source
            ):
                replacement = str(target)
            else:
                raise InvalidProjectError(
                    "PCB sheet filename disagrees with its UUID placement"
                )
            if replacement != atom.value:
                edits.append(TextEdit(atom.span, quote(replacement)))
    return apply_edits(text, edits).encode("utf-8")
