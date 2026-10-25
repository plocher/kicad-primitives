"""Read schematic placed symbols and title blocks within project context.

Parsing uses the private lossless S-expression foundation (ADR 0003).
This slice is read-only: no localized schematic edits.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from os import PathLike
from pathlib import Path
from types import MappingProxyType

from lossless_sexpr import AtomNode, Document, ListNode, ParseError, parse

__all__ = [
    "AmbiguousPlacedSymbolError",
    "InvalidSchematicError",
    "PlacedProperty",
    "PlacedSymbol",
    "Schematic",
    "SchematicError",
    "TitleBlock",
    "open_schematic",
]


class SchematicError(ValueError):
    """Base error for schematic inspection failures."""


class InvalidSchematicError(SchematicError):
    """The file is not a usable KiCad schematic or required structure is missing."""


class AmbiguousPlacedSymbolError(SchematicError):
    """More than one placed symbol matches the requested reference."""


@dataclass(frozen=True)
class TitleBlock:
    """Title-block metadata from one schematic file."""

    title: str = ""
    revision: str = ""
    date: str = ""
    company: str = ""
    comments: Mapping[int, str] = MappingProxyType({})


@dataclass(frozen=True)
class PlacedProperty:
    """One property declared on a placed symbol instance."""

    name: str
    value: str


@dataclass(frozen=True)
class PlacedSymbol:
    """Merged placed-symbol snapshot: fields, identity, transform, and flags."""

    reference: str
    lib_id: str
    uuid: str
    value: str
    footprint: str
    properties: tuple[PlacedProperty, ...]
    x: float
    y: float
    rotation: float
    mirror: str
    unit: int
    in_bom: bool
    dnp: bool
    on_board: bool
    in_pos_files: bool
    exclude_from_sim: bool
    path: Path

    def property(self, name: str) -> PlacedProperty:
        """Return the unique property with this name."""
        matches = tuple(p for p in self.properties if p.name == name)
        if not matches:
            raise KeyError(name)
        if len(matches) > 1:
            raise AmbiguousPlacedSymbolError(
                f"Ambiguous property {name!r} on {self.reference!r}"
            )
        return matches[0]


@dataclass(frozen=True)
class Schematic:
    """One schematic file's placed symbols and title block (read-only)."""

    path: Path
    version: int
    title_block: TitleBlock
    symbols: tuple[PlacedSymbol, ...]

    def symbol(self, reference: str) -> PlacedSymbol:
        """Return the unique placed symbol with this reference."""
        matches = tuple(s for s in self.symbols if s.reference == reference)
        if not matches:
            raise KeyError(reference)
        if len(matches) > 1:
            raise AmbiguousPlacedSymbolError(
                f"Ambiguous placed symbol reference {reference!r}"
            )
        return matches[0]


def open_schematic(path: str | PathLike[str]) -> Schematic:
    """Parse one explicit ``.kicad_sch`` path.

    Prefer :meth:`kicad_primitives.projects.Project.schematic` so callers stay
    inside project context. This helper exists for tests and internal use when
    the path is already validated as part of a project hierarchy.
    """
    location = Path(path).expanduser().resolve()
    if not location.is_file():
        raise InvalidSchematicError(f"Schematic file not found: {location}")
    if location.suffix.lower() != ".kicad_sch":
        raise InvalidSchematicError(
            f"Expected .kicad_sch file, got: {location.suffix or '<none>'}"
        )
    try:
        raw = location.read_bytes()
        document = parse(raw.decode("utf-8"))
    except (OSError, UnicodeError, ParseError, RecursionError) as exc:
        raise InvalidSchematicError(f"Invalid schematic syntax: {exc}") from exc
    return _schematic_from_document(location, document)


def _schematic_from_document(path: Path, document: Document) -> Schematic:
    roots = document.roots()
    if (
        len(roots) != 1
        or not isinstance(roots[0], ListNode)
        or roots[0].head != "kicad_sch"
    ):
        raise InvalidSchematicError("Expected one kicad_sch root")
    root = roots[0]
    version = _format_version(root)
    title_block = _title_block(root)
    symbols = tuple(
        symbol
        for node in root.child_lists("symbol")
        if (symbol := _placed_symbol(node, path)) is not None
    )
    return Schematic(
        path=path,
        version=version,
        title_block=title_block,
        symbols=symbols,
    )


def _format_version(root: ListNode) -> int:
    matches = root.child_lists("version")
    if len(matches) != 1:
        raise InvalidSchematicError("Expected one schematic version")
    value = _atom(matches[0], 1).value
    if not value.isascii() or not value.isdecimal():
        raise InvalidSchematicError("Invalid schematic version")
    return int(value)


def _title_block(root: ListNode) -> TitleBlock:
    blocks = root.child_lists("title_block")
    if not blocks:
        return TitleBlock()
    if len(blocks) > 1:
        raise InvalidSchematicError("Expected at most one title_block")
    block = blocks[0]
    title = revision = date = company = ""
    comments: dict[int, str] = {}
    for child in block.child_lists():
        head = child.head
        if head == "comment":
            if len(child.children()) < 3:
                continue
            index_atom = child.atom(1)
            text_atom = child.atom(2)
            if index_atom is None or text_atom is None:
                continue
            try:
                index = int(index_atom.value)
            except ValueError:
                continue
            if 1 <= index <= 9:
                comments[index] = text_atom.value
            continue
        if head in {"title", "rev", "date", "company"} and len(child.children()) >= 2:
            text = _atom(child, 1).value
            if head == "title":
                title = text
            elif head == "rev":
                revision = text
            elif head == "date":
                date = text
            else:
                company = text
    return TitleBlock(
        title=title,
        revision=revision,
        date=date,
        company=company,
        comments=MappingProxyType(comments),
    )


def _placed_symbol(node: ListNode, path: Path) -> PlacedSymbol | None:
    lib_nodes = node.child_lists("lib_id")
    if len(lib_nodes) != 1:
        return None
    lib_id = _atom(lib_nodes[0], 1).value
    if not lib_id:
        return None

    at_nodes = node.child_lists("at")
    if len(at_nodes) != 1:
        return None
    at = at_nodes[0]
    x = _number(at, 1)
    y = _number(at, 2)
    rotation = _number(at, 3) if len(at.children()) >= 4 else 0.0

    properties = tuple(_property(p) for p in node.child_lists("property"))
    reference = _named_value(properties, "Reference")
    if not reference:
        return None

    uuid_nodes = node.child_lists("uuid")
    uuid = _atom(uuid_nodes[0], 1).value if len(uuid_nodes) == 1 else ""

    unit_nodes = node.child_lists("unit")
    unit = int(_number(unit_nodes[0], 1)) if len(unit_nodes) == 1 else 1

    mirror_nodes = node.child_lists("mirror")
    mirror = ""
    if len(mirror_nodes) == 1 and len(mirror_nodes[0].children()) >= 2:
        mirror = _atom(mirror_nodes[0], 1).value.lower()

    return PlacedSymbol(
        reference=reference,
        lib_id=lib_id,
        uuid=uuid,
        value=_named_value(properties, "Value"),
        footprint=_named_value(properties, "Footprint"),
        properties=properties,
        x=x,
        y=y,
        rotation=rotation,
        mirror=mirror,
        unit=unit,
        in_bom=_flag(node, "in_bom", default=True),
        dnp=_flag(node, "dnp", default=False),
        on_board=_flag(node, "on_board", default=True),
        in_pos_files=_flag(node, "in_pos_files", default=True),
        exclude_from_sim=_flag(node, "exclude_from_sim", default=False),
        path=path,
    )


def _property(node: ListNode) -> PlacedProperty:
    name = _atom(node, 1).value
    value = _atom(node, 2).value
    if not name:
        raise InvalidSchematicError("Empty property name")
    return PlacedProperty(name=name, value=value)


def _named_value(properties: tuple[PlacedProperty, ...], name: str) -> str:
    for prop in properties:
        if prop.name == name:
            return prop.value
    return ""


def _flag(node: ListNode, head: str, *, default: bool) -> bool:
    matches = node.child_lists(head)
    if not matches:
        return default
    setting = matches[0]
    if len(setting.children()) == 1:
        return True
    value = _atom(setting, 1).value
    if value not in {"yes", "no"}:
        raise InvalidSchematicError(f"{head}: expected yes or no")
    return value == "yes"


def _atom(node: ListNode, index: int) -> AtomNode:
    value = node.atom(index)
    if value is None:
        raise InvalidSchematicError(f"{node.head}: missing atom {index}")
    return value


def _number(node: ListNode, index: int) -> float:
    try:
        value = float(_atom(node, index).value)
    except ValueError as exc:
        raise InvalidSchematicError(f"{node.head}: invalid number") from exc
    if not isfinite(value):
        raise InvalidSchematicError(f"{node.head}: non-finite number")
    return value
