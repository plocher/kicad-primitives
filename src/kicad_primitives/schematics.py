"""Inspect and edit schematic content within project context.

Parsing uses the private lossless S-expression foundation (ADR 0003).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from lossless_sexpr import AtomNode, Document, ListNode, ParseError, parse, quote

from ._erc_types import (
    ErcAcquisitionError,
    ErcContextError,
    ErcDocumentSnapshot,
    ErcIgnoredCheck,
    ErcItem,
    ErcPosition,
    ErcReport,
    ErcSheet,
    ErcSnapshot,
    ErcViolation,
)
from ._symbol_types import _MANDATORY, _attribute_key

if TYPE_CHECKING:
    from ._schematic_restore import _RestoreIntent
    from .projects import Project
    from .symbols import SymbolLibrary

__all__ = [
    "AmbiguousEmbeddedSymbolError",
    "AmbiguousPlacedSymbolError",
    "EmbeddedSymbol",
    "ErcAcquisitionError",
    "ErcContextError",
    "ErcDocumentSnapshot",
    "ErcIgnoredCheck",
    "ErcItem",
    "ErcPosition",
    "ErcReport",
    "ErcSheet",
    "ErcSnapshot",
    "ErcViolation",
    "GlobalLabel",
    "HierarchicalLabel",
    "InvalidSchematicError",
    "Junction",
    "Label",
    "NoConnect",
    "PlacedAttribute",
    "PlacedSymbol",
    "Schematic",
    "SchematicConflictError",
    "SchematicError",
    "SchematicVerificationError",
    "SheetInstance",
    "TitleBlock",
    "UnsupportedSchematicOperationError",
    "Wire",
    "open_schematic",
]


class SchematicError(ValueError):
    """Base error for schematic inspection failures."""


class InvalidSchematicError(SchematicError):
    """The file is not a usable KiCad schematic or required structure is missing."""


class AmbiguousPlacedSymbolError(SchematicError):
    """More than one placed symbol matches the requested reference."""


class AmbiguousEmbeddedSymbolError(SchematicError):
    """A cache container or embedded definition has ambiguous identity."""


class UnsupportedSchematicOperationError(SchematicError):
    """The requested schematic operation cannot be performed safely."""


class SchematicConflictError(SchematicError):
    """A schematic or its verification context changed on disk."""


class SchematicVerificationError(SchematicError):
    """Pending content did not satisfy its required electrical proof."""


@dataclass(frozen=True)
class TitleBlock:
    """Title-block metadata from one schematic file."""

    title: str = ""
    revision: str = ""
    date: str = ""
    company: str = ""
    comments: Mapping[int, str] = MappingProxyType({})


@dataclass(frozen=True)
class PlacedAttribute:
    """One attribute declared on a placed symbol instance."""

    name: str
    value: str


@dataclass(frozen=True, eq=False)
class PlacedSymbol:
    """Artifact-owned placed symbol with live attributes and focused edits."""

    reference: str
    lib_id: str
    uuid: str
    value: str
    footprint: str
    attributes: tuple[PlacedAttribute, ...]
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
    _owner: Schematic | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _index: int = field(default=-1, init=False, repr=False, compare=False)

    def set_attribute(self, name: str, value: str) -> None:
        """Establish an attribute in memory, without writing or annotating Reference.

        Create missing attributes, update differing values, and leave equal values
        byte-identical. Ambiguous or unsupported edits fail without changing source.
        """
        if self._owner is None:
            raise UnsupportedSchematicOperationError("Symbol has no owning schematic")
        self._owner._set_attribute(self, name, value)

    def attribute(self, name: str) -> PlacedAttribute:
        """Return the unique attribute with this name."""
        matches = tuple(
            p for p in self.attributes if _attribute_key(p.name) == _attribute_key(name)
        )
        if not matches:
            raise KeyError(name)
        if len(matches) > 1:
            raise AmbiguousPlacedSymbolError(
                f"Ambiguous attribute {name!r} on {self.reference!r}"
            )
        return matches[0]


@dataclass(frozen=True, eq=False)
class EmbeddedSymbol:
    """One source-backed definition in a schematic's embedded symbol cache."""

    lib_id: str
    _owner: Schematic = field(repr=False, compare=False)

    def restore_from(self, parent_library: SymbolLibrary, parent_name: str) -> None:
        """Restore this concrete definition from captured parent source in memory.

        Preserve placements and unrelated source. Ordinary visible pin-type
        corrections require explicit-save electrical proof. Unsupported
        inheritance or electrical changes fail before changing the schematic.
        """
        from ._schematic_restore import restore_definition

        restore_definition(self._owner, self.lib_id, parent_library, parent_name)


@dataclass(frozen=True)
class Wire:
    """A wire polyline in schematic space."""

    points: tuple[tuple[float, float], ...]
    uuid: str = ""


@dataclass(frozen=True)
class Junction:
    """A junction point."""

    x: float
    y: float
    uuid: str = ""


@dataclass(frozen=True)
class Label:
    """A local net label."""

    text: str
    x: float
    y: float
    rotation: float = 0.0
    uuid: str = ""
    kind: str = "label"


@dataclass(frozen=True)
class GlobalLabel:
    """A global net label."""

    text: str
    x: float
    y: float
    rotation: float = 0.0
    shape: str = ""
    uuid: str = ""


@dataclass(frozen=True)
class HierarchicalLabel:
    """A hierarchical sheet pin label."""

    text: str
    x: float
    y: float
    rotation: float = 0.0
    shape: str = ""
    uuid: str = ""


@dataclass(frozen=True)
class NoConnect:
    """A no-connect marker."""

    x: float
    y: float
    uuid: str = ""


@dataclass(frozen=True)
class SheetInstance:
    """A hierarchical sheet block (edge to a child schematic file)."""

    name: str
    filename: str
    x: float
    y: float
    width: float
    height: float
    uuid: str = ""


@dataclass(frozen=True, eq=False)
class Schematic:
    """One schematic file: symbols, title block, and electrical geometry."""

    path: Path
    version: int
    title_block: TitleBlock
    symbols: tuple[PlacedSymbol, ...]
    wires: tuple[Wire, ...] = ()
    junctions: tuple[Junction, ...] = ()
    labels: tuple[Label, ...] = ()
    global_labels: tuple[GlobalLabel, ...] = ()
    hierarchical_labels: tuple[HierarchicalLabel, ...] = ()
    no_connects: tuple[NoConnect, ...] = ()
    sheets: tuple[SheetInstance, ...] = ()
    _document: Document | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _baseline: bytes = field(default=b"", init=False, repr=False, compare=False)
    _project: Project | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _embedded_handles: dict[str, EmbeddedSymbol] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _restore_intents: dict[str, _RestoreIntent] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @property
    def embedded_symbols(self) -> tuple[EmbeddedSymbol, ...]:
        """Embedded definitions in source order, with stable object identity."""
        from ._schematic_restore import cache_nodes

        nodes = cache_nodes(self)
        for lib_id in nodes:
            if lib_id not in self._embedded_handles:
                self._embedded_handles[lib_id] = EmbeddedSymbol(lib_id, self)
        return tuple(self._embedded_handles[lib_id] for lib_id in nodes)

    def embedded_symbol(self, lib_id: str) -> EmbeddedSymbol:
        """Select one unambiguous embedded definition, or raise KeyError."""
        for symbol in self.embedded_symbols:
            if symbol.lib_id == lib_id:
                return symbol
        raise KeyError(lib_id)

    @property
    def is_modified(self) -> bool:
        """Whether content differs from the last opened or saved bytes."""
        return self.to_bytes() != self._baseline

    def to_bytes(self) -> bytes:
        """Preview pending source without writing or running electrical checks."""
        if self._document is None:
            raise UnsupportedSchematicOperationError("Schematic has no source")
        return self._document.source.encode("utf-8")

    def save(self, *, kicad_cli: str | PathLike[str] | None = None) -> None:
        """Verify and save this document to its opened location explicitly.

        Other owned documents remain pending. Verification uses the complete
        project hierarchy with only this document's changes staged. Requires
        KiCad for changed saves; never silently skips electrical verification.
        """
        if self._project is None:
            raise UnsupportedSchematicOperationError(
                "Save requires owning project context"
            )
        from ._schematic_persist import save_schematics

        save_schematics(self._project, (self,), kicad_cli=kicad_cli)

    def erc(self, *, kicad_cli: str | PathLike[str] | None = None) -> ErcReport:
        """Reject document-only ERC because the backend cannot honor that scope."""
        raise UnsupportedSchematicOperationError(
            "Document-only ERC is unsupported; request the full hierarchy on Project.erc"
        )

    def _set_attribute(self, symbol: PlacedSymbol, name: str, value: str) -> None:
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError("Attribute name and value must be strings")
        if not name or "\x00" in name or "\x00" in value:
            raise ValueError("Attribute name must be nonempty; NUL is not supported")
        name.encode("utf-8")
        value.encode("utf-8")
        if self.version != 20260306:
            raise UnsupportedSchematicOperationError(
                f"Format {self.version} is read-only"
            )
        assert self._document is not None
        root = self._document.roots()[0]
        assert isinstance(root, ListNode)
        nodes = tuple(
            n
            for n in root.child_lists("symbol")
            if _placed_symbol(n, self.path) is not None
        )
        node = nodes[symbol._index]
        if not symbol.uuid or len(node.child_lists("uuid")) != 1:
            raise UnsupportedSchematicOperationError(
                "Editing requires one nonempty symbol UUID"
            )
        if sum(s.uuid == symbol.uuid for s in self.symbols) != 1:
            raise AmbiguousPlacedSymbolError(f"Ambiguous symbol UUID {symbol.uuid!r}")
        matches = tuple(
            p
            for p in node.child_lists("property")
            if _attribute_key(_atom(p, 1).value) == _attribute_key(name)
        )
        if len(matches) > 1:
            raise AmbiguousPlacedSymbolError(f"Ambiguous attribute {name!r}")
        if matches and _atom(matches[0], 2).value == value:
            return
        if _attribute_key(name) == "reference":
            raise UnsupportedSchematicOperationError(
                "Reference requires reference annotation"
            )
        if name in {"dnp", "in_bom", "on_board", "in_pos_files", "exclude_from_sim"}:
            raise UnsupportedSchematicOperationError("Flags are not named attributes")
        if _attribute_key(name) == "value" and _is_power_symbol(root, symbol):
            raise UnsupportedSchematicOperationError(
                "Power-symbol Value changes are electrical edits"
            )
        before = self._document.source
        if matches:
            token = _atom(matches[0], 2)
            start, end, replacement = token.span.start, token.span.end, quote(value)
        else:
            anchor = node.child_lists("property")[-1]
            start = end = anchor.span.end
            replacement = _attribute_fragment(before, node, anchor, name, value)
        edited = before[:start] + replacement + before[end:]
        updated = _schematic_from_document(self.path, parse(edited))
        if updated.symbols[symbol._index].attribute(name).value != value:
            raise InvalidSchematicError(
                "Edit did not establish the requested attribute"
            )
        self._accept_document(updated)

    def _accept_document(self, updated: Schematic) -> None:
        for old, new in zip(self.symbols, updated.symbols, strict=True):
            object.__setattr__(old, "attributes", new.attributes)
            object.__setattr__(old, "value", new.value)
            object.__setattr__(old, "footprint", new.footprint)
        object.__setattr__(self, "_document", updated._document)

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
    location = Path(path).expanduser().absolute()
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
    schematic = Schematic(
        path=path,
        version=version,
        title_block=title_block,
        symbols=symbols,
        wires=tuple(_wire(n) for n in root.child_lists("wire")),
        junctions=tuple(_junction(n) for n in root.child_lists("junction")),
        labels=tuple(_label(n) for n in root.child_lists("label")),
        global_labels=tuple(_global_label(n) for n in root.child_lists("global_label")),
        hierarchical_labels=tuple(
            _hierarchical_label(n) for n in root.child_lists("hierarchical_label")
        ),
        no_connects=tuple(_no_connect(n) for n in root.child_lists("no_connect")),
        sheets=tuple(_sheet(n) for n in root.child_lists("sheet")),
    )
    object.__setattr__(schematic, "_document", document)
    object.__setattr__(schematic, "_baseline", document.source.encode("utf-8"))
    for index, symbol in enumerate(schematic.symbols):
        object.__setattr__(symbol, "_owner", schematic)
        object.__setattr__(symbol, "_index", index)
    return schematic


def _format_version(root: ListNode) -> int:
    matches = root.child_lists("version")
    if len(matches) != 1:
        raise InvalidSchematicError("Expected one schematic version")
    value = _atom(matches[0], 1).value
    if not value.isascii() or not value.isdecimal():
        raise InvalidSchematicError("Invalid schematic version")
    return int(value)


def _attribute_fragment(
    source: str, symbol: ListNode, anchor: ListNode, name: str, value: str
) -> str:
    newline = "\r\n" if "\r\n" in source else "\n"
    line_start = source.rfind("\n", 0, anchor.span.start) + 1
    prefix = source[line_start : anchor.span.start]
    indent = prefix if not prefix.strip() else "    "
    step = "\t" if "\t" in indent else "  "
    at = symbol.child_lists("at")[0]
    x, y = _atom(at, 1).raw, _atom(at, 2).raw
    return (
        f"{newline}{indent}(property {quote(name)} {quote(value)}"
        f"{newline}{indent}{step}(at {x} {y} 0)"
        f"{newline}{indent}{step}(effects (font (size 1.27 1.27)) (hide yes))"
        f"{newline}{indent})"
    )


def _is_power_symbol(root: ListNode, symbol: PlacedSymbol) -> bool:
    if symbol.lib_id.startswith("power:") or symbol.reference.startswith(
        ("#PWR", "#FLG")
    ):
        return True
    return any(
        _atom(definition, 1).value == symbol.lib_id
        and bool(definition.child_lists("power"))
        for cache in root.child_lists("lib_symbols")
        for definition in cache.child_lists("symbol")
    )


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

    attributes = tuple(_attribute(p) for p in node.child_lists("property"))
    mandatory = {name: _named_value(attributes, name) for name in _MANDATORY}
    reference = mandatory["reference"]
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
        value=mandatory["value"],
        footprint=mandatory["footprint"],
        attributes=attributes,
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


def _wire(node: ListNode) -> Wire:
    pts_nodes = node.child_lists("pts")
    if len(pts_nodes) != 1:
        raise InvalidSchematicError("wire: expected one pts list")
    points = tuple(
        (_number(xy, 1), _number(xy, 2)) for xy in pts_nodes[0].child_lists("xy")
    )
    if len(points) < 2:
        raise InvalidSchematicError("wire: expected at least two points")
    return Wire(points=points, uuid=_optional_uuid(node))


def _junction(node: ListNode) -> Junction:
    x, y, _rot = _at(node)
    return Junction(x=x, y=y, uuid=_optional_uuid(node))


def _label(node: ListNode) -> Label:
    text = _atom(node, 1).value
    x, y, rotation = _at(node)
    return Label(text=text, x=x, y=y, rotation=rotation, uuid=_optional_uuid(node))


def _global_label(node: ListNode) -> GlobalLabel:
    text = _atom(node, 1).value
    x, y, rotation = _at(node)
    return GlobalLabel(
        text=text,
        x=x,
        y=y,
        rotation=rotation,
        shape=_optional_shape(node),
        uuid=_optional_uuid(node),
    )


def _hierarchical_label(node: ListNode) -> HierarchicalLabel:
    text = _atom(node, 1).value
    x, y, rotation = _at(node)
    return HierarchicalLabel(
        text=text,
        x=x,
        y=y,
        rotation=rotation,
        shape=_optional_shape(node),
        uuid=_optional_uuid(node),
    )


def _no_connect(node: ListNode) -> NoConnect:
    x, y, _rot = _at(node)
    return NoConnect(x=x, y=y, uuid=_optional_uuid(node))


def _sheet(node: ListNode) -> SheetInstance:
    x, y, _rot = _at(node)
    size_nodes = node.child_lists("size")
    if len(size_nodes) != 1:
        raise InvalidSchematicError("sheet: expected one size")
    width = _number(size_nodes[0], 1)
    height = _number(size_nodes[0], 2)
    name = ""
    filename = ""
    for prop in node.child_lists("property"):
        key = _atom(prop, 1).value
        value = _atom(prop, 2).value
        if key == "Sheetname":
            name = value
        elif key == "Sheetfile":
            filename = value
    if not filename:
        raise InvalidSchematicError("sheet: missing Sheetfile")
    return SheetInstance(
        name=name,
        filename=filename,
        x=x,
        y=y,
        width=width,
        height=height,
        uuid=_optional_uuid(node),
    )


def _at(node: ListNode) -> tuple[float, float, float]:
    at_nodes = node.child_lists("at")
    if len(at_nodes) != 1:
        raise InvalidSchematicError(f"{node.head}: expected one at")
    at = at_nodes[0]
    x = _number(at, 1)
    y = _number(at, 2)
    rotation = _number(at, 3) if len(at.children()) >= 4 else 0.0
    return x, y, rotation


def _optional_uuid(node: ListNode) -> str:
    uuid_nodes = node.child_lists("uuid")
    if len(uuid_nodes) != 1:
        return ""
    return _atom(uuid_nodes[0], 1).value


def _optional_shape(node: ListNode) -> str:
    shapes = node.child_lists("shape")
    if len(shapes) != 1:
        return ""
    return _atom(shapes[0], 1).value


def _attribute(node: ListNode) -> PlacedAttribute:
    name = _atom(node, 1).value
    value = _atom(node, 2).value
    if not name:
        raise InvalidSchematicError("Empty attribute name")
    return PlacedAttribute(name=name, value=value)


def _named_value(attributes: tuple[PlacedAttribute, ...], name: str) -> str:
    matches = tuple(
        prop for prop in attributes if _attribute_key(prop.name) == _attribute_key(name)
    )
    if len(matches) > 1:
        raise AmbiguousPlacedSymbolError(f"Ambiguous mandatory attribute {name!r}")
    return matches[0].value if matches else ""


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
