"""KiCad interpretation over the sole private source-preserving parser."""

from dataclasses import dataclass, replace
from math import isfinite

from lossless_sexpr import (
    AtomNode,
    Document,
    ListNode,
    ParseError,
    SourceSpan,
    TextEdit,
    apply_edits,
    parse,
    quote,
)

from ._symbol_types import (
    _MANDATORY,
    AmbiguousAttributeError,
    AmbiguousPinError,
    AmbiguousSymbolError,
    InheritanceError,
    InvalidLibraryError,
    SymbolAttribute,
    SymbolRectangle,
    SymbolText,
    UnsupportedOperationError,
    _attribute_key,
)
from ._symbol_types import (
    BodyDefinition as SymbolBody,
)
from ._symbol_types import (
    PinDefinition as SymbolPin,
)
from ._symbol_types import (
    SymbolDefinition as Symbol,
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


def attribute_value_node(node: ListNode) -> AtomNode:
    return atom(node, 3 if atom(node, 1).raw == "private" else 2)


def attribute_view(node: ListNode, origin: str, version: int) -> SymbolAttribute:
    private = atom(node, 1).raw == "private"
    name = atom(node, 2 if private else 1).value
    if not name:
        raise InvalidLibraryError("Empty attribute name")
    value = attribute_value_node(node).value
    if version < 20250318 and value == "~":
        value = ""
    at = one(node, "at")
    effects = one(node, "effects")
    hidden = flag(node, "hide") or (effects is not None and flag(effects, "hide"))
    return SymbolAttribute(
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


def rectangle_view(node: ListNode) -> SymbolRectangle:
    start = one(node, "start", required=True)
    end = one(node, "end", required=True)
    assert start is not None and end is not None
    return SymbolRectangle(
        start_x=number(start, 1),
        start_y=number(start, 2),
        end_x=number(end, 1),
        end_y=number(end, 2),
    )


def text_view(node: ListNode) -> SymbolText:
    at = one(node, "at", required=True)
    assert at is not None
    return SymbolText(
        text=atom(node, 1).value,
        x=number(at, 1),
        y=number(at, 2),
        rotation=number(at, 3),
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
        rectangles=tuple(rectangle_view(r) for r in node.child_lists("rectangle")),
        texts=tuple(text_view(t) for t in node.child_lists("text")),
    )


def symbol_view(node: ListNode, version: int) -> Symbol:
    name = atom(node, 1).value
    if not name:
        raise InvalidLibraryError("Empty symbol name")
    parent = one(node, "extends")
    attributes = tuple(
        attribute_view(p, name, version) for p in node.child_lists("property")
    )
    bodies = tuple(body_view(b, name) for b in node.child_lists("symbol"))
    if len({(b.unit, b.body_style) for b in bodies}) != len(bodies):
        raise InvalidLibraryError(f"{name}: duplicate unit/body style")
    return Symbol(
        name=name,
        extends=atom(parent, 1).value if parent else None,
        attributes=attributes,
        bodies=bodies,
        units_locked=any(p.name == "ki_locked" for p in attributes),
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
    attributes: dict[str, SymbolAttribute] = {}
    root = chain[-1]
    for symbol in reversed(chain):
        local: set[str] = set()
        for prop in symbol.attributes:
            key = _attribute_key(prop.name)
            if key in local:
                raise AmbiguousAttributeError(
                    f"{symbol.name}: ambiguous attribute {prop.name!r}"
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
            attributes[key] = prop
        if symbol is not root and symbol.bodies:
            raise InheritanceError(
                f"{symbol.name}: derived symbol with local bodies is unsupported"
            )
    return replace(
        chain[0],
        attributes=tuple(attributes.values()),
        bodies=root.bodies,
        units_locked=root.units_locked,
        resolved=True,
    )


def _require_writeable(source: ParsedLibrary) -> None:
    if source.version != WRITE_VERSION:
        raise UnsupportedOperationError(f"Format {source.version} is read-only")


def _require_attribute_value(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Attribute value must be a string")
    if "\x00" in value:
        raise ValueError("Attribute value cannot contain NUL")
    value.encode("utf-8")
    return value


def _require_attribute_name(attribute_name: str) -> str:
    if not isinstance(attribute_name, str):
        raise TypeError("Attribute name must be a string")
    if not attribute_name:
        raise ValueError("Attribute name cannot be empty")
    if "\x00" in attribute_name:
        raise ValueError("Attribute name cannot contain NUL")
    attribute_name.encode("utf-8")
    return attribute_name


def _apply_source_edit(before: str, span: SourceSpan, replacement: str) -> str:
    edited = apply_edits(before, [TextEdit(span, replacement)])
    expected = before[: span.start] + replacement + before[span.end :]
    if edited != expected:
        raise InvalidLibraryError(
            "Attribute edit did not preserve the required source delta"
        )
    return edited


def _line_ending(source: str) -> str:
    return "\r\n" if "\r\n" in source else "\n"


def _indent_before(source: str, index: int) -> str:
    line_start = source.rfind("\n", 0, index) + 1
    indent = ""
    cursor = line_start
    while cursor < index and source[cursor] in " \t":
        indent += source[cursor]
        cursor += 1
    return indent


def _indent_step(indent: str, sample: str) -> str:
    if indent.endswith("\t") or "\t" in sample:
        return "\t"
    return "  "


def _insertion_anchor(symbol_node: ListNode) -> tuple[int, ListNode | None]:
    """Return (insert_at, style_anchor) after the last attribute or prelude node."""
    attributes = symbol_node.child_lists("property")
    if attributes:
        return attributes[-1].span.end, attributes[-1]
    extends = one(symbol_node, "extends")
    if extends is not None:
        return extends.span.end, extends
    return atom(symbol_node, 1).span.end, None


def _attribute_fragment(
    source: str,
    symbol_node: ListNode,
    style_anchor: ListNode | None,
    name: str,
    value: str,
    *,
    private: bool,
) -> str:
    """Build inserted attribute text matching the symbol's existing layout."""
    sample = source[symbol_node.span.start : symbol_node.span.end]
    compact = "\n" not in sample
    head = "property private" if private else "property"
    if compact:
        return f" ({head} {quote(name)} {quote(value)} (at 0 0 0))"
    newline = _line_ending(source)
    if style_anchor is not None:
        indent = _indent_before(source, style_anchor.span.start)
    else:
        indent = _indent_before(source, symbol_node.span.start) + _indent_step(
            _indent_before(source, symbol_node.span.start), sample
        )
    if not indent:
        indent = _indent_step("", sample)
    inner = indent + _indent_step(indent, sample)
    return (
        f"{newline}{indent}({head} {quote(name)} {quote(value)}"
        f"{newline}{inner}(at 0 0 0)"
        f"{newline}{indent})"
    )


def _leading_separator_start(source: str, node_start: int) -> int:
    index = node_start
    while index > 0 and source[index - 1] in " \t":
        index -= 1
    if index > 0 and source[index - 1] == "\n":
        index -= 1
        if index > 0 and source[index - 1] == "\r":
            index -= 1
    elif index == node_start and index > 0 and source[index - 1] == " ":
        # Compact single-line form: drop the space before the node.
        index -= 1
    return index


def replace_attribute(
    source: ParsedLibrary, symbol_name: str, attribute_name: str, value: str
) -> ParsedLibrary:
    _require_writeable(source)
    value = _require_attribute_value(value)
    symbol = source.symbol(symbol_name)
    try:
        target = symbol.attribute(attribute_name)
    except KeyError as exc:
        raise UnsupportedOperationError(
            f"{symbol_name}: attribute {attribute_name!r} is not declared; "
            "use add_attribute to insert"
        ) from exc
    if target.value == value:
        return source
    symbol_node = source.nodes[source.symbols.index(symbol)]
    prop_node = symbol_node.child_lists("property")[symbol.attributes.index(target)]
    token = attribute_value_node(prop_node)
    before = source.document.source
    replacement = quote(value)
    edited = _apply_source_edit(before, token.span, replacement)
    updated = read_source(edited.encode("utf-8"))
    if updated.symbol(symbol_name).attribute(attribute_name).value != value:
        raise InvalidLibraryError(
            "Attribute edit did not establish the requested value"
        )
    return updated


def insert_attribute(
    source: ParsedLibrary,
    symbol_name: str,
    attribute_name: str,
    value: str,
    *,
    private: bool = False,
) -> ParsedLibrary:
    _require_writeable(source)
    attribute_name = _require_attribute_name(attribute_name)
    value = _require_attribute_value(value)
    if not isinstance(private, bool):
        raise TypeError("private must be a bool")
    symbol = source.symbol(symbol_name)
    try:
        symbol.attribute(attribute_name)
    except KeyError:
        pass
    else:
        raise UnsupportedOperationError(
            f"{symbol_name}: attribute {attribute_name!r} already declared"
        )
    symbol_node = source.nodes[source.symbols.index(symbol)]
    before = source.document.source
    insert_at, style_anchor = _insertion_anchor(symbol_node)
    fragment = _attribute_fragment(
        before,
        symbol_node,
        style_anchor,
        attribute_name,
        value,
        private=private,
    )
    edited = _apply_source_edit(before, SourceSpan(insert_at, insert_at), fragment)
    updated = read_source(edited.encode("utf-8"))
    inserted = updated.symbol(symbol_name).attribute(attribute_name)
    if inserted.value != value or inserted.is_private != private:
        raise InvalidLibraryError(
            "Attribute insert did not establish the requested attribute"
        )
    if len(updated.symbol(symbol_name).attributes) != len(symbol.attributes) + 1:
        raise InvalidLibraryError(
            "Attribute insert changed unexpected attribute counts"
        )
    return updated


def delete_attribute(
    source: ParsedLibrary, symbol_name: str, attribute_name: str
) -> ParsedLibrary:
    _require_writeable(source)
    attribute_name = _require_attribute_name(attribute_name)
    symbol = source.symbol(symbol_name)
    target = symbol.attribute(attribute_name)
    symbol_node = source.nodes[source.symbols.index(symbol)]
    prop_node = symbol_node.child_lists("property")[symbol.attributes.index(target)]
    before = source.document.source
    start = _leading_separator_start(before, prop_node.span.start)
    edited = _apply_source_edit(before, SourceSpan(start, prop_node.span.end), "")
    updated = read_source(edited.encode("utf-8"))
    remaining = updated.symbol(symbol_name)
    try:
        remaining.attribute(attribute_name)
    except KeyError:
        pass
    else:
        raise InvalidLibraryError(
            "Attribute delete did not remove the requested attribute"
        )
    if len(remaining.attributes) != len(symbol.attributes) - 1:
        raise InvalidLibraryError(
            "Attribute delete changed unexpected attribute counts"
        )
    return updated


def _require_pin_string(label: str, value: object, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not allow_empty and not value:
        raise ValueError(f"{label} cannot be empty")
    if "\x00" in value:
        raise ValueError(f"{label} cannot contain NUL")
    value.encode("utf-8")
    return value


def _require_pin_token(label: str, value: object) -> str:
    text = _require_pin_string(label, value)
    if any(ch.isspace() for ch in text) or any(ch in text for ch in '()"'):
        raise ValueError(f"Invalid {label}: {text!r}")
    return text


def _require_pin_number_coord(label: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a number")
    number_value = float(value)
    if not isfinite(number_value):
        raise ValueError(f"{label} must be finite")
    return number_value


def _format_number(value: float) -> str:
    if value == 0:
        return "0"
    as_int = int(value)
    if as_int == value and abs(value) < 1e15:
        return str(as_int)
    return format(value, "g")


def _require_unit_style(unit: object, body_style: object) -> tuple[int, int]:
    if isinstance(unit, bool) or not isinstance(unit, int):
        raise TypeError("unit must be an int")
    if isinstance(body_style, bool) or not isinstance(body_style, int):
        raise TypeError("body_style must be an int")
    if unit < 0 or body_style < 0:
        raise ValueError("unit and body_style must be non-negative")
    return unit, body_style


def _body_node(
    source: ParsedLibrary, symbol: Symbol, unit: int, body_style: int
) -> tuple[SymbolBody, ListNode]:
    body = symbol.body(unit, body_style)
    symbol_node = source.nodes[source.symbols.index(symbol)]
    body_node = symbol_node.child_lists("symbol")[symbol.bodies.index(body)]
    return body, body_node


def _pin_node(
    body: SymbolBody, body_node: ListNode, number: str
) -> tuple[SymbolPin, ListNode]:
    pin = body.pin(number)
    return pin, body_node.child_lists("pin")[body.pins.index(pin)]


def _pin_insertion_anchor(body_node: ListNode) -> tuple[int, ListNode | None]:
    pins = body_node.child_lists("pin")
    if pins:
        return pins[-1].span.end, pins[-1]
    return atom(body_node, 1).span.end, None


def _pin_fragment(
    source: str,
    body_node: ListNode,
    style_anchor: ListNode | None,
    *,
    number: str,
    name: str,
    electrical_type: str,
    shape: str,
    x: float,
    y: float,
    rotation: float,
    length: float,
    hidden: bool,
) -> str:
    sample = source[body_node.span.start : body_node.span.end]
    compact = "\n" not in sample
    hide = " (hide yes)" if hidden else ""
    at = f"(at {_format_number(x)} {_format_number(y)} {_format_number(rotation)})"
    length_node = f"(length {_format_number(length)})"
    name_node = f"(name {quote(name)})"
    number_node = f"(number {quote(number)})"
    if compact:
        return (
            f" (pin {electrical_type} {shape} {at} {length_node} "
            f"{name_node} {number_node}{hide})"
        )
    newline = _line_ending(source)
    if style_anchor is not None:
        indent = _indent_before(source, style_anchor.span.start)
    else:
        indent = _indent_before(source, body_node.span.start) + _indent_step(
            _indent_before(source, body_node.span.start), sample
        )
    if not indent:
        indent = _indent_step("", sample)
    inner = indent + _indent_step(indent, sample)
    hide_line = f"{newline}{inner}(hide yes)" if hidden else ""
    return (
        f"{newline}{indent}(pin {electrical_type} {shape}"
        f"{newline}{inner}{at}"
        f"{newline}{inner}{length_node}"
        f"{newline}{inner}{name_node}"
        f"{newline}{inner}{number_node}"
        f"{hide_line}"
        f"{newline}{indent})"
    )


def insert_pin(
    source: ParsedLibrary,
    symbol_name: str,
    unit: int,
    body_style: int,
    number: str,
    name: str,
    electrical_type: str,
    *,
    x: float,
    y: float,
    rotation: float = 0.0,
    length: float = 2.54,
    shape: str = "line",
    hidden: bool = False,
) -> ParsedLibrary:
    _require_writeable(source)
    unit, body_style = _require_unit_style(unit, body_style)
    number = _require_pin_string("Pin number", number)
    name = _require_pin_string("Pin name", name, allow_empty=True)
    electrical_type = _require_pin_token("electrical_type", electrical_type)
    shape = _require_pin_token("shape", shape)
    x = _require_pin_number_coord("x", x)
    y = _require_pin_number_coord("y", y)
    rotation = _require_pin_number_coord("rotation", rotation)
    length = _require_pin_number_coord("length", length)
    if not isinstance(hidden, bool):
        raise TypeError("hidden must be a bool")
    symbol = source.symbol(symbol_name)
    body, body_node = _body_node(source, symbol, unit, body_style)
    try:
        body.pin(number)
    except KeyError:
        pass
    except AmbiguousPinError as exc:
        raise UnsupportedOperationError(
            f"{symbol_name}: pin {number!r} already declared on unit {unit} "
            f"body style {body_style}"
        ) from exc
    else:
        raise UnsupportedOperationError(
            f"{symbol_name}: pin {number!r} already declared on unit {unit} "
            f"body style {body_style}"
        )
    before = source.document.source
    insert_at, style_anchor = _pin_insertion_anchor(body_node)
    fragment = _pin_fragment(
        before,
        body_node,
        style_anchor,
        number=number,
        name=name,
        electrical_type=electrical_type,
        shape=shape,
        x=x,
        y=y,
        rotation=rotation,
        length=length,
        hidden=hidden,
    )
    edited = _apply_source_edit(before, SourceSpan(insert_at, insert_at), fragment)
    updated = read_source(edited.encode("utf-8"))
    inserted = updated.symbol(symbol_name).body(unit, body_style).pin(number)
    if (
        inserted.name != name
        or inserted.electrical_type != electrical_type
        or inserted.shape != shape
        or inserted.x != x
        or inserted.y != y
        or inserted.rotation != rotation
        or inserted.length != length
        or inserted.hidden != hidden
    ):
        raise InvalidLibraryError("Pin insert did not establish the requested pin")
    prior_count = len(body.pins)
    if len(updated.symbol(symbol_name).body(unit, body_style).pins) != prior_count + 1:
        raise InvalidLibraryError("Pin insert changed unexpected pin counts")
    return updated


def _pin_context(
    source: ParsedLibrary, symbol_name: str, unit: int, body_style: int, number: str
) -> tuple[SymbolPin, ListNode]:
    symbol = source.symbol(symbol_name)
    body, body_node = _body_node(source, symbol, unit, body_style)
    return _pin_node(body, body_node, number)


def _apply_pin_edit(
    source: ParsedLibrary, span: SourceSpan, replacement: str
) -> ParsedLibrary:
    edited = _apply_source_edit(source.document.source, span, replacement)
    return read_source(edited.encode("utf-8"))


def replace_pin(
    source: ParsedLibrary,
    symbol_name: str,
    unit: int,
    body_style: int,
    number: str,
    *,
    name: str | None = None,
    electrical_type: str | None = None,
    x: float | None = None,
    y: float | None = None,
    rotation: float | None = None,
    length: float | None = None,
    shape: str | None = None,
    hidden: bool | None = None,
) -> ParsedLibrary:
    _require_writeable(source)
    unit, body_style = _require_unit_style(unit, body_style)
    number = _require_pin_string("Pin number", number)
    if name is not None:
        name = _require_pin_string("Pin name", name, allow_empty=True)
    if electrical_type is not None:
        electrical_type = _require_pin_token("electrical_type", electrical_type)
    if shape is not None:
        shape = _require_pin_token("shape", shape)
    if x is not None:
        x = _require_pin_number_coord("x", x)
    if y is not None:
        y = _require_pin_number_coord("y", y)
    if rotation is not None:
        rotation = _require_pin_number_coord("rotation", rotation)
    if length is not None:
        length = _require_pin_number_coord("length", length)
    if hidden is not None and not isinstance(hidden, bool):
        raise TypeError("hidden must be a bool")
    if all(
        value is None
        for value in (name, electrical_type, x, y, rotation, length, shape, hidden)
    ):
        raise ValueError("set_pin requires at least one field to update")

    pin, _ = _pin_context(source, symbol_name, unit, body_style, number)
    desired_name = pin.name if name is None else name
    desired_type = pin.electrical_type if electrical_type is None else electrical_type
    desired_shape = pin.shape if shape is None else shape
    desired_x = pin.x if x is None else x
    desired_y = pin.y if y is None else y
    desired_rotation = pin.rotation if rotation is None else rotation
    desired_length = pin.length if length is None else length
    desired_hidden = pin.hidden if hidden is None else hidden

    if (
        pin.name == desired_name
        and pin.electrical_type == desired_type
        and pin.shape == desired_shape
        and pin.x == desired_x
        and pin.y == desired_y
        and pin.rotation == desired_rotation
        and pin.length == desired_length
        and pin.hidden == desired_hidden
    ):
        return source

    current = source
    pin, pin_node = _pin_context(current, symbol_name, unit, body_style, number)

    if pin.electrical_type != desired_type:
        current = _apply_pin_edit(current, atom(pin_node, 1).span, desired_type)
        pin, pin_node = _pin_context(current, symbol_name, unit, body_style, number)

    if pin.shape != desired_shape:
        current = _apply_pin_edit(current, atom(pin_node, 2).span, desired_shape)
        pin, pin_node = _pin_context(current, symbol_name, unit, body_style, number)

    at = one(pin_node, "at", required=True)
    assert at is not None
    if pin.x != desired_x:
        current = _apply_pin_edit(current, atom(at, 1).span, _format_number(desired_x))
        pin, pin_node = _pin_context(current, symbol_name, unit, body_style, number)
        at = one(pin_node, "at", required=True)
        assert at is not None
    if pin.y != desired_y:
        current = _apply_pin_edit(current, atom(at, 2).span, _format_number(desired_y))
        pin, pin_node = _pin_context(current, symbol_name, unit, body_style, number)
        at = one(pin_node, "at", required=True)
        assert at is not None
    if pin.rotation != desired_rotation:
        current = _apply_pin_edit(
            current, atom(at, 3).span, _format_number(desired_rotation)
        )
        pin, pin_node = _pin_context(current, symbol_name, unit, body_style, number)

    if pin.length != desired_length:
        length_node = one(pin_node, "length", required=True)
        assert length_node is not None
        current = _apply_pin_edit(
            current, atom(length_node, 1).span, _format_number(desired_length)
        )
        pin, pin_node = _pin_context(current, symbol_name, unit, body_style, number)

    if pin.name != desired_name:
        name_node = one(pin_node, "name", required=True)
        assert name_node is not None
        current = _apply_pin_edit(current, atom(name_node, 1).span, quote(desired_name))
        pin, pin_node = _pin_context(current, symbol_name, unit, body_style, number)

    if pin.hidden != desired_hidden:
        text = current.document.source
        hide_lists = pin_node.child_lists("hide")
        bare_hides = [
            child
            for child in pin_node.children()[1:]
            if isinstance(child, AtomNode) and child.raw == "hide"
        ]
        if desired_hidden:
            if not hide_lists and not bare_hides:
                insert_at = pin_node.span.end - 1
                indent = _indent_before(text, pin_node.span.start)
                sample = text[pin_node.span.start : pin_node.span.end]
                if "\n" in sample:
                    inner = indent + _indent_step(indent, sample)
                    fragment = f"{_line_ending(text)}{inner}(hide yes)"
                else:
                    fragment = " (hide yes)"
                current = _apply_pin_edit(
                    current, SourceSpan(insert_at, insert_at), fragment
                )
        elif hide_lists:
            hide_list = hide_lists[0]
            start = _leading_separator_start(text, hide_list.span.start)
            current = _apply_pin_edit(
                current, SourceSpan(start, hide_list.span.end), ""
            )
        elif bare_hides:
            bare_hide = bare_hides[0]
            start = _leading_separator_start(text, bare_hide.span.start)
            current = _apply_pin_edit(
                current, SourceSpan(start, bare_hide.span.end), ""
            )

    final = current.symbol(symbol_name).body(unit, body_style).pin(number)
    if (
        final.name != desired_name
        or final.electrical_type != desired_type
        or final.shape != desired_shape
        or final.x != desired_x
        or final.y != desired_y
        or final.rotation != desired_rotation
        or final.length != desired_length
        or final.hidden != desired_hidden
    ):
        raise InvalidLibraryError("Pin edit did not establish the requested values")
    return current


def delete_pin(
    source: ParsedLibrary,
    symbol_name: str,
    unit: int,
    body_style: int,
    number: str,
) -> ParsedLibrary:
    _require_writeable(source)
    unit, body_style = _require_unit_style(unit, body_style)
    number = _require_pin_string("Pin number", number)
    symbol = source.symbol(symbol_name)
    body, body_node = _body_node(source, symbol, unit, body_style)
    _pin, pin_node = _pin_node(body, body_node, number)
    before = source.document.source
    start = _leading_separator_start(before, pin_node.span.start)
    edited = _apply_source_edit(before, SourceSpan(start, pin_node.span.end), "")
    updated = read_source(edited.encode("utf-8"))
    remaining = updated.symbol(symbol_name).body(unit, body_style)
    try:
        remaining.pin(number)
    except KeyError:
        pass
    else:
        raise InvalidLibraryError("Pin delete did not remove the requested pin")
    if len(remaining.pins) != len(body.pins) - 1:
        raise InvalidLibraryError("Pin delete changed unexpected pin counts")
    return updated


def _body_name(symbol_name: str, unit: int, body_style: int) -> str:
    return f"{symbol_name}_{unit}_{body_style}"


def _body_fragment(
    source: str,
    symbol_node: ListNode,
    style_anchor: ListNode | None,
    body_name: str,
) -> str:
    sample = source[symbol_node.span.start : symbol_node.span.end]
    compact = "\n" not in sample
    if compact:
        return f" (symbol {quote(body_name)})"
    newline = _line_ending(source)
    if style_anchor is not None:
        indent = _indent_before(source, style_anchor.span.start)
    else:
        indent = _indent_before(source, symbol_node.span.start) + _indent_step(
            _indent_before(source, symbol_node.span.start), sample
        )
    if not indent:
        indent = _indent_step("", sample)
    return f"{newline}{indent}(symbol {quote(body_name)}{newline}{indent})"


def _body_insertion_anchor(symbol_node: ListNode) -> tuple[int, ListNode | None]:
    bodies = symbol_node.child_lists("symbol")
    if bodies:
        return bodies[-1].span.end, bodies[-1]
    attributes = symbol_node.child_lists("property")
    if attributes:
        return attributes[-1].span.end, attributes[-1]
    extends = one(symbol_node, "extends")
    if extends is not None:
        return extends.span.end, extends
    return atom(symbol_node, 1).span.end, None


def ensure_body(
    source: ParsedLibrary, symbol_name: str, unit: int, body_style: int
) -> ParsedLibrary:
    """Create an empty body when missing; no-op when present."""
    _require_writeable(source)
    unit, body_style = _require_unit_style(unit, body_style)
    symbol = source.symbol(symbol_name)
    try:
        symbol.body(unit, body_style)
    except KeyError:
        pass
    else:
        return source
    symbol_node = source.nodes[source.symbols.index(symbol)]
    before = source.document.source
    insert_at, style_anchor = _body_insertion_anchor(symbol_node)
    name = _body_name(symbol_name, unit, body_style)
    fragment = _body_fragment(before, symbol_node, style_anchor, name)
    edited = _apply_source_edit(before, SourceSpan(insert_at, insert_at), fragment)
    updated = read_source(edited.encode("utf-8"))
    updated.symbol(symbol_name).body(unit, body_style)
    if len(updated.symbol(symbol_name).bodies) != len(symbol.bodies) + 1:
        raise InvalidLibraryError("Body ensure changed unexpected body counts")
    return updated


def _graphic_insertion_anchor(body_node: ListNode) -> tuple[int, ListNode | None]:
    children = [
        child for child in body_node.children()[1:] if isinstance(child, ListNode)
    ]
    if children:
        return children[-1].span.end, children[-1]
    return atom(body_node, 1).span.end, None


def insert_rectangle(
    source: ParsedLibrary,
    symbol_name: str,
    unit: int,
    body_style: int,
    *,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> ParsedLibrary:
    _require_writeable(source)
    unit, body_style = _require_unit_style(unit, body_style)
    start_x = _require_pin_number_coord("start_x", start_x)
    start_y = _require_pin_number_coord("start_y", start_y)
    end_x = _require_pin_number_coord("end_x", end_x)
    end_y = _require_pin_number_coord("end_y", end_y)
    symbol = source.symbol(symbol_name)
    body, body_node = _body_node(source, symbol, unit, body_style)
    before = source.document.source
    insert_at, style_anchor = _graphic_insertion_anchor(body_node)
    sample = before[body_node.span.start : body_node.span.end]
    compact = "\n" not in sample
    start = f"(start {_format_number(start_x)} {_format_number(start_y)})"
    end = f"(end {_format_number(end_x)} {_format_number(end_y)})"
    if compact:
        fragment = f" (rectangle {start} {end})"
    else:
        newline = _line_ending(before)
        if style_anchor is not None:
            indent = _indent_before(before, style_anchor.span.start)
        else:
            indent = _indent_before(before, body_node.span.start) + _indent_step(
                _indent_before(before, body_node.span.start), sample
            )
        if not indent:
            indent = _indent_step("", sample)
        inner = indent + _indent_step(indent, sample)
        fragment = (
            f"{newline}{indent}(rectangle"
            f"{newline}{inner}{start}"
            f"{newline}{inner}{end}"
            f"{newline}{indent})"
        )
    edited = _apply_source_edit(before, SourceSpan(insert_at, insert_at), fragment)
    updated = read_source(edited.encode("utf-8"))
    rects = updated.symbol(symbol_name).body(unit, body_style).rectangles
    if len(rects) != len(body.rectangles) + 1:
        raise InvalidLibraryError("Rectangle insert changed unexpected counts")
    last = rects[-1]
    if (
        last.start_x != start_x
        or last.start_y != start_y
        or last.end_x != end_x
        or last.end_y != end_y
    ):
        raise InvalidLibraryError("Rectangle insert did not establish geometry")
    return updated


def insert_body_text(
    source: ParsedLibrary,
    symbol_name: str,
    unit: int,
    body_style: int,
    text: str,
    *,
    x: float,
    y: float,
    rotation: float = 0.0,
) -> ParsedLibrary:
    _require_writeable(source)
    unit, body_style = _require_unit_style(unit, body_style)
    text = _require_pin_string("Body text", text, allow_empty=True)
    x = _require_pin_number_coord("x", x)
    y = _require_pin_number_coord("y", y)
    rotation = _require_pin_number_coord("rotation", rotation)
    symbol = source.symbol(symbol_name)
    body, body_node = _body_node(source, symbol, unit, body_style)
    before = source.document.source
    insert_at, style_anchor = _graphic_insertion_anchor(body_node)
    sample = before[body_node.span.start : body_node.span.end]
    compact = "\n" not in sample
    at = f"(at {_format_number(x)} {_format_number(y)} {_format_number(rotation)})"
    if compact:
        fragment = f" (text {quote(text)} {at})"
    else:
        newline = _line_ending(before)
        if style_anchor is not None:
            indent = _indent_before(before, style_anchor.span.start)
        else:
            indent = _indent_before(before, body_node.span.start) + _indent_step(
                _indent_before(before, body_node.span.start), sample
            )
        if not indent:
            indent = _indent_step("", sample)
        inner = indent + _indent_step(indent, sample)
        fragment = (
            f"{newline}{indent}(text {quote(text)}"
            f"{newline}{inner}{at}"
            f"{newline}{indent})"
        )
    edited = _apply_source_edit(before, SourceSpan(insert_at, insert_at), fragment)
    updated = read_source(edited.encode("utf-8"))
    texts = updated.symbol(symbol_name).body(unit, body_style).texts
    if len(texts) != len(body.texts) + 1:
        raise InvalidLibraryError("Body text insert changed unexpected counts")
    last = texts[-1]
    if last.text != text or last.x != x or last.y != y or last.rotation != rotation:
        raise InvalidLibraryError(
            "Body text insert did not establish the requested text"
        )
    return updated


def _require_symbol_name(name: object, *, label: str = "Symbol name") -> str:
    if not isinstance(name, str):
        raise TypeError(f"{label} must be a string")
    if not name:
        raise ValueError(f"{label} cannot be empty")
    if "\x00" in name:
        raise ValueError(f"{label} cannot contain NUL")
    name.encode("utf-8")
    return name


def _root_node(source: ParsedLibrary) -> ListNode:
    roots = source.document.roots()
    assert len(roots) == 1 and isinstance(roots[0], ListNode)
    return roots[0]


def _symbol_insert_anchor(source: ParsedLibrary) -> tuple[int, ListNode | None]:
    root = _root_node(source)
    if source.nodes:
        return source.nodes[-1].span.end, source.nodes[-1]
    version = one(root, "version", required=True)
    assert version is not None
    return version.span.end, version


def _symbol_shell_fragment(
    source_text: str, anchor: ListNode | None, name: str, extends: str | None
) -> str:
    if "\n" not in source_text:
        if extends is None:
            return f" (symbol {quote(name)})"
        return f" (symbol {quote(name)} (extends {quote(extends)}))"
    newline = _line_ending(source_text)
    if anchor is not None:
        indent = _indent_before(source_text, anchor.span.start)
    else:
        indent = _indent_step("", source_text)
    if not indent:
        indent = _indent_step("", source_text)
    inner = indent + _indent_step(indent, source_text)
    if extends is None:
        return f"{newline}{indent}(symbol {quote(name)}{newline}{indent})"
    return (
        f"{newline}{indent}(symbol {quote(name)}"
        f"{newline}{inner}(extends {quote(extends)})"
        f"{newline}{indent})"
    )


def create_symbol(
    source: ParsedLibrary,
    name: str,
    *,
    extends: str | None = None,
) -> ParsedLibrary:
    """Insert a new empty top-level symbol (optional extends)."""
    _require_writeable(source)
    name = _require_symbol_name(name)
    if extends is not None:
        extends = _require_symbol_name(extends, label="extends")
        source.symbol(extends)
    try:
        source.symbol(name)
    except KeyError:
        pass
    else:
        raise UnsupportedOperationError(f"Symbol {name!r} already exists")
    before = source.document.source
    insert_at, anchor = _symbol_insert_anchor(source)
    fragment = _symbol_shell_fragment(before, anchor, name, extends)
    edited = _apply_source_edit(before, SourceSpan(insert_at, insert_at), fragment)
    updated = read_source(edited.encode("utf-8"))
    created = updated.symbol(name)
    if created.extends != extends or created.bodies:
        raise InvalidLibraryError("Symbol create did not establish the requested shell")
    if len(updated.symbols) != len(source.symbols) + 1:
        raise InvalidLibraryError("Symbol create changed unexpected symbol counts")
    return updated


def delete_symbol(source: ParsedLibrary, name: str) -> ParsedLibrary:
    """Remove one top-level symbol; refuse if others still extend it."""
    _require_writeable(source)
    name = _require_symbol_name(name)
    symbol = source.symbol(name)
    dependents = tuple(s.name for s in source.symbols if s.extends == name)
    if dependents:
        raise UnsupportedOperationError(
            f"Cannot delete {name!r}: extended by {', '.join(dependents)}"
        )
    symbol_node = source.nodes[source.symbols.index(symbol)]
    before = source.document.source
    start = _leading_separator_start(before, symbol_node.span.start)
    edited = _apply_source_edit(before, SourceSpan(start, symbol_node.span.end), "")
    updated = read_source(edited.encode("utf-8"))
    try:
        updated.symbol(name)
    except KeyError:
        pass
    else:
        raise InvalidLibraryError("Symbol delete did not remove the requested symbol")
    if len(updated.symbols) != len(source.symbols) - 1:
        raise InvalidLibraryError("Symbol delete changed unexpected symbol counts")
    return updated


def rename_symbol(source: ParsedLibrary, old_name: str, new_name: str) -> ParsedLibrary:
    """Rename a symbol, its body names, and in-library extends references."""
    _require_writeable(source)
    old_name = _require_symbol_name(old_name, label="Old symbol name")
    new_name = _require_symbol_name(new_name, label="New symbol name")
    if old_name == new_name:
        return source
    symbol = source.symbol(old_name)
    try:
        source.symbol(new_name)
    except KeyError:
        pass
    else:
        raise UnsupportedOperationError(f"Symbol {new_name!r} already exists")

    current = source
    for other in list(current.symbols):
        if other.name == old_name or other.extends != old_name:
            continue
        other_node = current.nodes[current.symbols.index(other)]
        extends_node = one(other_node, "extends", required=True)
        assert extends_node is not None
        edited = _apply_source_edit(
            current.document.source, atom(extends_node, 1).span, quote(new_name)
        )
        current = read_source(edited.encode("utf-8"))

    symbol = current.symbol(old_name)
    symbol_node = current.nodes[current.symbols.index(symbol)]
    replacements: list[tuple[SourceSpan, str]] = [
        (atom(symbol_node, 1).span, quote(new_name))
    ]
    for body_node in symbol_node.child_lists("symbol"):
        body_atom = atom(body_node, 1)
        old_body = body_atom.value
        if not old_body.startswith(old_name + "_"):
            raise InvalidLibraryError(
                f"{old_name}: body name {old_body!r} does not match symbol"
            )
        suffix = old_body[len(old_name) :]
        replacements.append((body_atom.span, quote(new_name + suffix)))
    edited = current.document.source
    for span, token in sorted(
        replacements, key=lambda item: item[0].start, reverse=True
    ):
        edited = _apply_source_edit(edited, span, token)
    updated = read_source(edited.encode("utf-8"))
    try:
        updated.symbol(old_name)
    except KeyError:
        pass
    else:
        raise InvalidLibraryError("Symbol rename left the old name in place")
    renamed = updated.symbol(new_name)
    expected_bodies = {(b.unit, b.body_style) for b in symbol.bodies}
    if {(b.unit, b.body_style) for b in renamed.bodies} != expected_bodies:
        raise InvalidLibraryError("Symbol rename changed body identities")
    for body in renamed.bodies:
        if body.name != f"{new_name}_{body.unit}_{body.body_style}":
            raise InvalidLibraryError("Symbol rename did not rewrite body names")
    if any(s.extends == old_name for s in updated.symbols):
        raise InvalidLibraryError("Symbol rename left stale extends references")
    return updated


def copy_symbol(source: ParsedLibrary, old_name: str, new_name: str) -> ParsedLibrary:
    """Duplicate one symbol inside the same library under a new name."""
    return _copy_symbol_into(
        dest=source,
        source=source,
        old_name=old_name,
        new_name=new_name,
        require_distinct_names=True,
    )


def copy_symbol_from(
    dest: ParsedLibrary,
    source: ParsedLibrary,
    source_name: str,
    new_name: str,
) -> ParsedLibrary:
    """Copy one symbol from *source* into *dest* under *new_name*.

    When *source* is the same library object as *dest*, behaves like
    :func:`copy_symbol`. Derived symbols keep their ``extends`` parent name;
    that parent must already exist in *dest* (copy parents first).
    """
    return _copy_symbol_into(
        dest=dest,
        source=source,
        old_name=source_name,
        new_name=new_name,
        require_distinct_names=source is dest,
    )


def _renamed_symbol_chunk(
    source: ParsedLibrary,
    symbol_node: ListNode,
    old_name: str,
    new_name: str,
) -> str:
    before = source.document.source
    chunk = before[symbol_node.span.start : symbol_node.span.end]
    rel_edits: list[tuple[int, int, str]] = []
    top = atom(symbol_node, 1)
    rel_edits.append(
        (
            top.span.start - symbol_node.span.start,
            top.span.end - symbol_node.span.start,
            quote(new_name),
        )
    )
    for body_node in symbol_node.child_lists("symbol"):
        body_atom = atom(body_node, 1)
        old_body = body_atom.value
        if not old_body.startswith(old_name + "_"):
            raise InvalidLibraryError(
                f"{old_name}: body name {old_body!r} does not match symbol"
            )
        suffix = old_body[len(old_name) :]
        rel_edits.append(
            (
                body_atom.span.start - symbol_node.span.start,
                body_atom.span.end - symbol_node.span.start,
                quote(new_name + suffix),
            )
        )
    new_chunk = chunk
    for start, end, token in sorted(rel_edits, key=lambda item: item[0], reverse=True):
        new_chunk = new_chunk[:start] + token + new_chunk[end:]
    return new_chunk


def _copy_symbol_into(
    *,
    dest: ParsedLibrary,
    source: ParsedLibrary,
    old_name: str,
    new_name: str,
    require_distinct_names: bool,
) -> ParsedLibrary:
    _require_writeable(dest)
    old_name = _require_symbol_name(old_name, label="Source symbol name")
    new_name = _require_symbol_name(new_name, label="New symbol name")
    if require_distinct_names and old_name == new_name:
        raise UnsupportedOperationError("copy_symbol requires a distinct new name")
    symbol = source.symbol(old_name)
    try:
        dest.symbol(new_name)
    except KeyError:
        pass
    else:
        raise UnsupportedOperationError(f"Symbol {new_name!r} already exists")
    if symbol.extends is not None:
        try:
            dest.symbol(symbol.extends)
        except KeyError as exc:
            raise UnsupportedOperationError(
                f"Cannot copy derived symbol {old_name!r}: parent "
                f"{symbol.extends!r} is not in the destination library"
            ) from exc

    symbol_node = source.nodes[source.symbols.index(symbol)]
    new_chunk = _renamed_symbol_chunk(source, symbol_node, old_name, new_name)
    before = dest.document.source
    insert_at, _anchor = _symbol_insert_anchor(dest)
    if "\n" in before:
        # Prefer the destination library's indent style when it already has symbols.
        if dest.nodes:
            indent = _indent_before(before, dest.nodes[-1].span.start)
        else:
            indent = _indent_before(before, symbol_node.span.start)
        fragment = f"{_line_ending(before)}{indent}{new_chunk}"
    else:
        fragment = f" {new_chunk}"
    edited = _apply_source_edit(before, SourceSpan(insert_at, insert_at), fragment)
    updated = read_source(edited.encode("utf-8"))
    copied = updated.symbol(new_name)
    if len(copied.bodies) != len(symbol.bodies):
        raise InvalidLibraryError("Symbol copy changed body counts")
    if len(copied.attributes) != len(symbol.attributes):
        raise InvalidLibraryError("Symbol copy changed attribute counts")
    if copied.extends != symbol.extends:
        raise InvalidLibraryError("Symbol copy did not preserve extends")
    if len(updated.symbols) != len(dest.symbols) + 1:
        raise InvalidLibraryError("Symbol copy changed unexpected symbol counts")
    if source is dest:
        updated.symbol(old_name)
    return updated
