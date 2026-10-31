"""Replace one embedded symbol definition with a library definition, in memory."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from lossless_sexpr import AtomNode, Document, ListNode, parse, quote

from .schematics import (
    AmbiguousEmbeddedSymbolError,
    InvalidSchematicError,
    SheetFile,
    UnsupportedSchematicOperationError,
    _sheet_file_from_document,
)
from .symbols import SymbolLibrary

_GRAPHICS = frozenset(
    {"arc", "bezier", "circle", "polyline", "rectangle", "text", "text_box"}
)


@dataclass(frozen=True)
class _PinFact:
    unit: int
    style: int
    number: str
    name: str
    electrical_type: str
    guard: tuple[object, ...]
    hidden: bool
    alternates: bool

    @property
    def identity(self) -> tuple[int, int, str]:
        return self.unit, self.style, self.number


def _atom(node: ListNode, index: int) -> AtomNode:
    atom = node.atom(index)
    if atom is None:
        raise InvalidSchematicError(f"{node.head}: expected atom {index}")
    return atom


def _one(node: ListNode, head: str) -> ListNode:
    matches = node.child_lists(head)
    if len(matches) != 1:
        raise UnsupportedSchematicOperationError(f"{node.head}: expected one {head}")
    return matches[0]


def _root(document: Document) -> ListNode:
    roots = document.roots()
    if len(roots) != 1 or not isinstance(roots[0], ListNode):
        raise InvalidSchematicError("Expected one schematic root")
    return roots[0]


def cache_nodes(schematic: SheetFile) -> dict[str, ListNode]:
    assert schematic._document is not None
    return _cache_nodes(schematic._document)


def _cache_nodes(document: Document) -> dict[str, ListNode]:
    containers = _root(document).child_lists("lib_symbols")
    if len(containers) > 1:
        raise AmbiguousEmbeddedSymbolError("Ambiguous lib_symbols containers")
    if not containers:
        raise InvalidSchematicError("Missing lib_symbols container")
    result: dict[str, ListNode] = {}
    for node in containers[0].child_lists("symbol"):
        lib_id = _atom(node, 1).value
        if not lib_id:
            raise InvalidSchematicError("Empty embedded library identity")
        if lib_id in result:
            raise AmbiguousEmbeddedSymbolError(
                f"Ambiguous embedded identity: {lib_id!r}"
            )
        result[lib_id] = node
    return result


def _shape(node: AtomNode | ListNode) -> tuple[object, ...]:
    if isinstance(node, AtomNode):
        return ("atom", node.raw)
    return tuple(_shape(child) for child in node.children())


def _body_identity(body: ListNode, prefix: str) -> tuple[int, int]:
    pieces = _atom(body, 1).value.rsplit("_", 2)
    if (
        len(pieces) != 3
        or pieces[0] != prefix
        or any(not part.isascii() or not part.isdecimal() for part in pieces[1:])
    ):
        raise UnsupportedSchematicOperationError(
            "Malformed embedded/parent body suffix"
        )
    return int(pieces[1]), int(pieces[2])


def _inventory(
    node: ListNode, prefix: str
) -> tuple[tuple[_PinFact, ...], tuple[object, ...]]:
    if node.child_lists("extends"):
        raise UnsupportedSchematicOperationError("Inherited restore is not implemented")
    pins: list[_PinFact] = []
    body_ids: set[tuple[int, int]] = set()
    body_guards: list[tuple[object, ...]] = []
    for body in node.child_lists("symbol"):
        unit, style = _body_identity(body, prefix)
        if (unit, style) in body_ids:
            raise AmbiguousEmbeddedSymbolError("Duplicate embedded unit/body style")
        body_ids.add((unit, style))
        opaque = tuple(
            _shape(child)
            for child in body.children()[2:]
            if not isinstance(child, ListNode) or child.head not in _GRAPHICS | {"pin"}
        )
        if opaque:
            body_guards.append((unit, style, opaque))
        for pin in body.child_lists("pin"):
            number = _atom(_one(pin, "number"), 1).value
            if not number:
                raise UnsupportedSchematicOperationError("Empty pin number")
            name = _atom(_one(pin, "name"), 1).value
            at = _one(pin, "at")
            try:
                values = [float(_atom(at, index).value) for index in (1, 2, 3)]
                values.append(float(_atom(_one(pin, "length"), 1).value))
            except ValueError as exc:
                raise UnsupportedSchematicOperationError(
                    "Invalid pin geometry"
                ) from exc
            if not all(isfinite(value) for value in values):
                raise UnsupportedSchematicOperationError("Invalid pin geometry")
            hidden = any(
                isinstance(c, AtomNode) and c.value == "hide"
                for c in pin.children()[2:]
            ) or any(
                len(c.children()) == 1 or _atom(c, 1).value != "no"
                for c in pin.child_lists("hide")
            )
            pins.append(
                _PinFact(
                    unit,
                    style,
                    number,
                    name,
                    _atom(pin, 1).value,
                    tuple(_shape(c) for c in pin.children()[2:]),
                    hidden,
                    bool(pin.child_lists("alternate")),
                )
            )
    identities = [pin.identity for pin in pins]
    if len(set(identities)) != len(identities):
        raise AmbiguousEmbeddedSymbolError("Ambiguous pin occurrence identity")
    root_guard = tuple(
        _shape(child)
        for child in node.children()[2:]
        if not isinstance(child, ListNode)
        or child.head not in {"property", "symbol", "embedded_fonts"}
    )
    return tuple(sorted(pins, key=lambda p: p.identity)), (
        root_guard,
        tuple(body_guards),
    )


def _validate_delta(
    old: ListNode, new: ListNode, old_prefix: str, new_prefix: str
) -> tuple[tuple[_PinFact, ...], tuple[_PinFact, ...]]:
    before, old_guard = _inventory(old, old_prefix)
    after, new_guard = _inventory(new, new_prefix)
    if old_guard != new_guard:
        raise UnsupportedSchematicOperationError(
            "Changed unknown or electrical definition content"
        )
    if tuple(p.identity for p in before) != tuple(p.identity for p in after):
        raise UnsupportedSchematicOperationError(
            "Pin addition/removal or unit/style changes are unsupported"
        )
    for previous, requested in zip(before, after, strict=True):
        if previous.guard != requested.guard:
            raise UnsupportedSchematicOperationError(
                "Pin names, geometry, visibility, alternates and opaque pin content must stay unchanged"
            )
    return before, after


def _materialize(
    document: Document, node: ListNode, parent_name: str, lib_id: str
) -> str:
    text = document.source
    replacements = [(_atom(node, 1), lib_id)]
    short_name = lib_id.rsplit(":", 1)[-1]
    for body in node.child_lists("symbol"):
        _body_identity(body, parent_name)
        body_name = _atom(body, 1)
        replacements.append(
            (body_name, short_name + body_name.value[len(parent_name) :])
        )
    chunk = text[node.span.start : node.span.end]
    for atom, replacement in sorted(
        replacements, key=lambda pair: pair[0].span.start, reverse=True
    ):
        if atom.value == replacement:
            continue
        start, end = atom.span.start - node.span.start, atom.span.end - node.span.start
        chunk = chunk[:start] + quote(replacement) + chunk[end:]
    return chunk


def update_definition(
    schematic: SheetFile, lib_id: str, library: SymbolLibrary, name: str
) -> None:
    """Replace the embedded *lib_id* definition with *name* from *library*."""
    schematic._check_open()
    if not isinstance(library, SymbolLibrary):
        raise TypeError("library must be an opened SymbolLibrary")
    library._check_open()
    if not isinstance(name, str) or not name:
        raise ValueError("name must be a nonempty string")
    if schematic.version != 20260306 or library.version != 20251024:
        raise UnsupportedSchematicOperationError(
            "Update requires supported schematic and library formats"
        )
    source = library._source
    definition = source.symbol(name)
    node = source.nodes[source.symbols.index(definition)]
    target = cache_nodes(schematic)[lib_id]
    _validate_delta(target, node, lib_id.rsplit(":", 1)[-1], name)
    materialized = _materialize(source.document, node, name, lib_id)
    assert schematic._document is not None
    text = schematic._document.source
    if text[target.span.start : target.span.end] == materialized:
        return
    edited = text[: target.span.start] + materialized + text[target.span.end :]
    updated = _sheet_file_from_document(schematic.path, parse(edited))
    replaced = cache_nodes(updated)[lib_id]
    assert updated._document is not None
    if (
        updated._document.source[replaced.span.start : replaced.span.end]
        != materialized
    ):
        raise InvalidSchematicError("Update did not establish exact requested source")
    schematic._accept_document(updated)
