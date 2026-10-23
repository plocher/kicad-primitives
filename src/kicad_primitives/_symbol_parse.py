"""KiCad interpretation over the sole private source-preserving parser."""

from dataclasses import dataclass, replace
from math import isfinite

from lossless_sexpr import (
    AtomNode,
    Document,
    ListNode,
    ParseError,
    TextEdit,
    apply_edits,
    parse,
    quote,
)

from ._symbol_types import (
    _MANDATORY,
    AmbiguousPropertyError,
    AmbiguousSymbolError,
    InheritanceError,
    InvalidLibraryError,
    Symbol,
    SymbolBody,
    SymbolPin,
    SymbolProperty,
    UnsupportedOperationError,
    _property_key,
)

WRITE_VERSION = 20251024
_NONEMPTY_OVERRIDE = frozenset({"ki_keywords", "ki_fp_filters", "ki_description"})


def atom(node: ListNode, index: int) -> AtomNode:
    value = node.atom(index)
    if value is None:
        raise InvalidLibraryError(f"{node.head}: missing atom {index}")
    return value


def one(node: ListNode, head: str, *, required: bool = False) -> ListNode | None:
    matches = node.child_lists(head)
    if len(matches) > 1 or (required and not matches):
        raise InvalidLibraryError(f"{node.head}: expected one {head}")
    return matches[0] if matches else None


def number(node: ListNode, index: int) -> float:
    try:
        value = float(atom(node, index).value)
    except ValueError as exc:
        raise InvalidLibraryError(f"{node.head}: invalid number") from exc
    if not isfinite(value):
        raise InvalidLibraryError(f"{node.head}: non-finite number")
    return value


def flag(node: ListNode, head: str, default: bool = False) -> bool:
    setting = one(node, head)
    if setting is not None:
        # KiCad's optional bool form: (do_not_autoplace) means true.
        if len(setting.children()) == 1:
            return True
        value = atom(setting, 1).value
        if value not in ("yes", "no"):
            raise InvalidLibraryError(f"{head}: expected yes or no")
        return value == "yes"
    # Older KiCad versions used bare hide inside effects/pin nodes.
    return default or any(
        isinstance(c, AtomNode) and c.raw == head for c in node.children()[1:]
    )


def property_value_node(node: ListNode) -> AtomNode:
    return atom(node, 3 if atom(node, 1).raw == "private" else 2)


def property_view(node: ListNode, origin: str, version: int) -> SymbolProperty:
    private = atom(node, 1).raw == "private"
    name = atom(node, 2 if private else 1).value
    if not name:
        raise InvalidLibraryError("Empty property name")
    value = property_value_node(node).value
    if version < 20250318 and value == "~":
        value = ""
    at = one(node, "at")
    effects = one(node, "effects")
    hidden = flag(node, "hide") or (effects is not None and flag(effects, "hide"))
    return SymbolProperty(
        name=name,
        value=value,
        origin_symbol=origin,
        is_private=private,
        hidden=hidden,
        autoplace=not flag(node, "do_not_autoplace"),
        x=number(at, 1) if at else None,
        y=number(at, 2) if at else None,
        rotation=number(at, 3) if at else None,
    )


def pin_view(node: ListNode) -> SymbolPin:
    at = one(node, "at", required=True)
    length = one(node, "length", required=True)
    name = one(node, "name", required=True)
    num = one(node, "number", required=True)
    assert (
        at is not None and length is not None and name is not None and num is not None
    )
    if not atom(num, 1).value:
        raise InvalidLibraryError("Empty pin number")
    return SymbolPin(
        number=atom(num, 1).value,
        name=atom(name, 1).value,
        electrical_type=atom(node, 1).value,
        shape=atom(node, 2).value,
        x=number(at, 1),
        y=number(at, 2),
        rotation=number(at, 3),
        length=number(length, 1),
        hidden=flag(node, "hide"),
    )


def body_view(node: ListNode, origin: str) -> SymbolBody:
    name = atom(node, 1).value
    parts = name.rsplit("_", 2)
    if (
        len(parts) != 3
        or parts[0] != origin
        or not all(p.isdecimal() for p in parts[1:])
    ):
        raise InvalidLibraryError(f"{origin}: invalid body name {name!r}")
    return SymbolBody(
        name=name,
        unit=int(parts[1]),
        body_style=int(parts[2]),
        pins=tuple(pin_view(p) for p in node.child_lists("pin")),
        origin_symbol=origin,
    )


def symbol_view(node: ListNode, version: int) -> Symbol:
    name = atom(node, 1).value
    if not name:
        raise InvalidLibraryError("Empty symbol name")
    parent = one(node, "extends")
    properties = tuple(
        property_view(p, name, version) for p in node.child_lists("property")
    )
    bodies = tuple(body_view(b, name) for b in node.child_lists("symbol"))
    if len({(b.unit, b.body_style) for b in bodies}) != len(bodies):
        raise InvalidLibraryError(f"{name}: duplicate unit/body style")
    return Symbol(
        name=name,
        extends=atom(parent, 1).value if parent else None,
        properties=properties,
        bodies=bodies,
        units_locked=any(p.name == "ki_locked" for p in properties),
    )


@dataclass(frozen=True)
class ParsedLibrary:
    document: Document
    version: int
    symbols: tuple[Symbol, ...]
    nodes: tuple[ListNode, ...]

    def symbol(self, name: str) -> Symbol:
        matches = tuple(s for s in self.symbols if s.name == name)
        if not matches:
            raise KeyError(name)
        if len(matches) > 1:
            raise AmbiguousSymbolError(f"Ambiguous symbol {name!r}")
        return matches[0]


def read_source(raw: bytes) -> ParsedLibrary:
    try:
        document = parse(raw.decode("utf-8"))
    except (UnicodeError, ParseError, RecursionError) as exc:
        raise InvalidLibraryError(f"Invalid library syntax: {exc}") from exc
    roots = document.roots()
    if (
        len(roots) != 1
        or not isinstance(roots[0], ListNode)
        or roots[0].head != "kicad_symbol_lib"
    ):
        raise InvalidLibraryError("Expected one kicad_symbol_lib root")
    root = roots[0]
    version_node = one(root, "version", required=True)
    assert version_node is not None
    value = atom(version_node, 1).value
    if not value.isascii() or not value.isdecimal() or len(value) != 8:
        raise InvalidLibraryError("Expected eight-digit library version")
    version = int(value)
    if version > WRITE_VERSION:
        raise UnsupportedOperationError(f"Unsupported future library format {version}")
    nodes = root.child_lists("symbol")
    return ParsedLibrary(
        document, version, tuple(symbol_view(n, version) for n in nodes), nodes
    )


def resolve(source: ParsedLibrary, name: str) -> Symbol:
    chain: list[Symbol] = []
    visited: set[str] = set()
    current: str | None = name
    while current is not None:
        if current in visited:
            raise InheritanceError(f"{name}: inheritance cycle at {current!r}")
        visited.add(current)
        try:
            symbol = source.symbol(current)
        except KeyError as exc:
            if not chain:
                raise
            raise InheritanceError(f"{name}: missing parent {current!r}") from exc
        chain.append(symbol)
        current = symbol.extends
    fields: dict[str, SymbolProperty] = {}
    root = chain[-1]
    for symbol in reversed(chain):
        local: set[str] = set()
        for prop in symbol.properties:
            key = _property_key(prop.name)
            if key in local:
                raise AmbiguousPropertyError(
                    f"{symbol.name}: ambiguous property {prop.name!r}"
                )
            local.add(key)
            if symbol is not root and key == "ki_fp_filters" and not prop.value.split():
                continue
            if (
                symbol is not root
                and (key in _MANDATORY or key in _NONEMPTY_OVERRIDE)
                and not prop.value
            ):
                continue
            # ki_locked is a legacy structural marker, not an inherited text override.
            if prop.name == "ki_locked" and symbol is not root:
                continue
            fields[key] = prop
        if symbol is not root and symbol.bodies:
            raise InheritanceError(
                f"{symbol.name}: derived symbol with local bodies is unsupported"
            )
    return replace(
        chain[0],
        properties=tuple(fields.values()),
        bodies=root.bodies,
        units_locked=root.units_locked,
        resolved=True,
    )


def replace_property(
    source: ParsedLibrary, symbol_name: str, property_name: str, value: str
) -> ParsedLibrary:
    if source.version != WRITE_VERSION:
        raise UnsupportedOperationError(f"Format {source.version} is read-only")
    if not isinstance(value, str):
        raise TypeError("Property value must be a string")
    if "\x00" in value:
        raise ValueError("Property value cannot contain NUL")
    value.encode("utf-8")
    symbol = source.symbol(symbol_name)
    try:
        target = symbol.property(property_name)
    except KeyError as exc:
        raise UnsupportedOperationError(
            f"{symbol_name}: property {property_name!r} is not declared; insertion is unsupported"
        ) from exc
    if target.value == value:
        return source
    symbol_node = source.nodes[source.symbols.index(symbol)]
    prop_node = symbol_node.child_lists("property")[symbol.properties.index(target)]
    token = property_value_node(prop_node)
    before = source.document.source
    replacement = quote(value)
    edited = apply_edits(before, [TextEdit(token.span, replacement)])
    expected = before[: token.span.start] + replacement + before[token.span.end :]
    if edited != expected:
        raise InvalidLibraryError(
            "Property edit did not preserve the required source delta"
        )
    updated = read_source(edited.encode("utf-8"))
    if updated.symbol(symbol_name).property(property_name).value != value:
        raise InvalidLibraryError("Property edit did not establish the requested value")
    return updated
