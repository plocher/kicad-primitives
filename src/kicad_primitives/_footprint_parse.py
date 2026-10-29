"""KiCad footprint interpretation over the sole private source-preserving parser."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

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

from . import _symbol_parse
from ._footprint_types import (
    FootprintAttribute,
    FootprintSummary,
    InvalidFootprintError,
    Pad,
    PadDrill,
    UnsupportedOperationError,
    _select_attribute,
    unique_pad_count,
)

WRITE_VERSION = 20260206
_FOOTPRINT_TYPES = frozenset({"smd", "through_hole"})
require_attribute_name = _symbol_parse._require_attribute_name
_PRELUDE = ("tags", "descr", "layer", "generator_version", "generator", "version")


def _atom(node: ListNode, index: int) -> AtomNode:
    value = node.atom(index)
    if value is None:
        raise InvalidFootprintError(f"{node.head}: missing atom {index}")
    return value


def _one(node: ListNode, head: str, *, required: bool = False) -> ListNode | None:
    matches = node.child_lists(head)
    if len(matches) > 1 or (required and not matches):
        raise InvalidFootprintError(f"{node.head}: expected one {head}")
    return matches[0] if matches else None


def _number(node: ListNode, index: int) -> float:
    try:
        value = float(_atom(node, index).value)
    except ValueError as exc:
        raise InvalidFootprintError(f"{node.head}: invalid number") from exc
    if not isfinite(value):
        raise InvalidFootprintError(f"{node.head}: non-finite number")
    return value


def _flag(node: ListNode, head: str) -> bool:
    setting = _one(node, head)
    if setting is None:
        return any(
            isinstance(c, AtomNode) and c.raw == head for c in node.children()[1:]
        )
    if len(setting.children()) == 1:
        return True
    value = _atom(setting, 1).value
    if value not in ("yes", "no"):
        raise InvalidFootprintError(f"{head}: expected yes or no")
    return value == "yes"


def _attribute_view(node: ListNode) -> FootprintAttribute:
    name = _atom(node, 1).value
    if not name:
        raise InvalidFootprintError("Empty attribute name")
    layer = _one(node, "layer")
    effects = _one(node, "effects")
    hidden = _flag(node, "hide") or (effects is not None and _flag(effects, "hide"))
    return FootprintAttribute(
        name=name,
        value=_atom(node, 2).value,
        layer=None if layer is None else _atom(layer, 1).value,
        hidden=hidden,
    )


def _drill_view(node: ListNode | None) -> PadDrill | None:
    if node is None:
        return None
    atoms = [c for c in node.children()[1:] if isinstance(c, AtomNode)]
    oval = bool(atoms) and atoms[0].raw == "oval"
    sizes = atoms[1:] if oval else atoms
    if not sizes:
        raise InvalidFootprintError("drill: missing size")
    try:
        width = float(sizes[0].value)
        height = float(sizes[1].value) if len(sizes) > 1 else width
    except ValueError as exc:
        raise InvalidFootprintError("drill: invalid number") from exc
    if not isfinite(width) or not isfinite(height):
        raise InvalidFootprintError("drill: non-finite number")
    return PadDrill(width=width, height=height, oval=oval)


def _pad_view(node: ListNode) -> Pad:
    at = _one(node, "at", required=True)
    size = _one(node, "size", required=True)
    layers = _one(node, "layers")
    assert at is not None and size is not None
    return Pad(
        number=_atom(node, 1).value,
        pad_type=_atom(node, 2).value,
        shape=_atom(node, 3).value,
        x=_number(at, 1),
        y=_number(at, 2),
        rotation=_number(at, 3) if at.atom(3) is not None else 0.0,
        width=_number(size, 1),
        height=_number(size, 2),
        layers=()
        if layers is None
        else tuple(c.value for c in layers.children()[1:] if isinstance(c, AtomNode)),
        drill=_drill_view(_one(node, "drill")),
    )


@dataclass(frozen=True)
class ParsedFootprint:
    """Semantic view plus the parsed document it was read from."""

    document: Document
    root: ListNode
    version: int
    name: str
    description: str
    tags: str
    attributes: tuple[FootprintAttribute, ...]
    footprint_type: str
    flags: frozenset[str]
    pads: tuple[Pad, ...]

    def attribute(self, name: str) -> FootprintAttribute:
        return _select_attribute(self.attributes, name, self.name)

    def summary(self, path: Path) -> FootprintSummary:
        return FootprintSummary(
            name=path.stem,
            declared_name=self.name,
            version=self.version,
            description=self.description,
            tags=self.tags,
            attributes=self.attributes,
            footprint_type=self.footprint_type,
            flags=self.flags,
            pad_count=len(self.pads),
            unique_pad_count=unique_pad_count(self.pads),
            path=path,
        )


def read_source(raw: bytes) -> ParsedFootprint:
    """Parse one ``.kicad_mod`` file; future formats fail explicitly."""
    try:
        document = parse(raw.decode("utf-8"))
    except (UnicodeError, ParseError, RecursionError) as exc:
        raise InvalidFootprintError(f"Invalid footprint syntax: {exc}") from exc
    roots = document.roots()
    if (
        len(roots) != 1
        or not isinstance(roots[0], ListNode)
        or roots[0].head not in ("footprint", "module")
    ):
        raise InvalidFootprintError("Expected one footprint root")
    root = roots[0]
    name = _atom(root, 1).value
    version_node = _one(root, "version")
    if version_node is None:
        version = 0
    else:
        value = _atom(version_node, 1).value
        if not value.isascii() or not value.isdecimal() or len(value) != 8:
            raise InvalidFootprintError("Expected eight-digit footprint version")
        version = int(value)
    if version > WRITE_VERSION:
        raise UnsupportedOperationError(
            f"Unsupported future footprint format {version}"
        )
    descr = _one(root, "descr")
    tags = _one(root, "tags")
    attr = _one(root, "attr")
    tokens = (
        ()
        if attr is None
        else tuple(c.value for c in attr.children()[1:] if isinstance(c, AtomNode))
    )
    types = [t for t in tokens if t in _FOOTPRINT_TYPES]
    if len(types) > 1:
        raise InvalidFootprintError("attr: more than one footprint type")
    return ParsedFootprint(
        document=document,
        root=root,
        version=version,
        name=name,
        description="" if descr is None else _atom(descr, 1).value,
        tags="" if tags is None else _atom(tags, 1).value,
        attributes=tuple(_attribute_view(p) for p in root.child_lists("property")),
        footprint_type=types[0] if types else "unspecified",
        flags=frozenset(t for t in tokens if t not in _FOOTPRINT_TYPES),
        pads=tuple(_pad_view(p) for p in root.child_lists("pad")),
    )


def require_writeable(version: int) -> None:
    """Refuse edits and writes for any format other than the write format."""
    if version != WRITE_VERSION:
        raise UnsupportedOperationError(f"Format {version} is read-only")


def _edit(before: str, span: SourceSpan, replacement: str) -> str:
    edited = apply_edits(before, [TextEdit(span, replacement)])
    expected = before[: span.start] + replacement + before[span.end :]
    if edited != expected:
        raise InvalidFootprintError("Edit did not preserve the required source delta")
    return edited


def _property_node(source: ParsedFootprint, target: FootprintAttribute) -> ListNode:
    return source.root.child_lists("property")[source.attributes.index(target)]


def replace_attribute(
    source: ParsedFootprint, attribute_name: str, value: str
) -> ParsedFootprint:
    """Replace one declared attribute value; an equal value returns *source*."""
    require_writeable(source.version)
    value = _symbol_parse._require_attribute_value(value)
    try:
        target = source.attribute(attribute_name)
    except KeyError as exc:
        raise UnsupportedOperationError(
            f"{source.name}: attribute {attribute_name!r} is not declared; "
            "use add_attribute to insert"
        ) from exc
    if target.value == value:
        return source
    token = _atom(_property_node(source, target), 2)
    edited = _edit(source.document.source, token.span, quote(value))
    updated = read_source(edited.encode("utf-8"))
    if updated.attribute(attribute_name).value != value:
        raise InvalidFootprintError("Attribute edit did not establish the value")
    return updated


def _insertion_anchor(root: ListNode) -> tuple[int, ListNode | None]:
    attributes = root.child_lists("property")
    if attributes:
        return attributes[-1].span.end, attributes[-1]
    for head in _PRELUDE:
        node = _one(root, head)
        if node is not None:
            return node.span.end, node
    return _atom(root, 1).span.end, None


def _attribute_fragment(
    source: str, root: ListNode, style_anchor: ListNode | None, name: str, value: str
) -> str:
    sample = source[root.span.start : root.span.end]
    if "\n" not in sample:
        return (
            f' (property {quote(name)} {quote(value)} (at 0 0 0) (layer "F.Fab")'
            " (hide yes) (effects (font (size 1 1) (thickness 0.15))))"
        )
    newline = _symbol_parse._line_ending(source)
    if style_anchor is not None:
        indent = _symbol_parse._indent_before(source, style_anchor.span.start)
    else:
        indent = _symbol_parse._indent_step("", sample)
    if not indent:
        indent = _symbol_parse._indent_step("", sample)
    step = _symbol_parse._indent_step(indent, sample)
    i1, i2, i3 = indent + step, indent + step * 2, indent + step * 3
    return (
        f"{newline}{indent}(property {quote(name)} {quote(value)}"
        f"{newline}{i1}(at 0 0 0)"
        f'{newline}{i1}(layer "F.Fab")'
        f"{newline}{i1}(hide yes)"
        f"{newline}{i1}(effects"
        f"{newline}{i2}(font"
        f"{newline}{i3}(size 1 1)"
        f"{newline}{i3}(thickness 0.15)"
        f"{newline}{i2})"
        f"{newline}{i1})"
        f"{newline}{indent})"
    )


def insert_attribute(
    source: ParsedFootprint, attribute_name: str, value: str
) -> ParsedFootprint:
    """Insert one new hidden attribute after the last one; reject duplicates."""
    require_writeable(source.version)
    attribute_name = _symbol_parse._require_attribute_name(attribute_name)
    value = _symbol_parse._require_attribute_value(value)
    try:
        source.attribute(attribute_name)
    except KeyError:
        pass
    else:
        raise UnsupportedOperationError(
            f"{source.name}: attribute {attribute_name!r} already declared"
        )
    before = source.document.source
    insert_at, style_anchor = _insertion_anchor(source.root)
    fragment = _attribute_fragment(
        before, source.root, style_anchor, attribute_name, value
    )
    edited = _edit(before, SourceSpan(insert_at, insert_at), fragment)
    updated = read_source(edited.encode("utf-8"))
    if (
        updated.attribute(attribute_name).value != value
        or len(updated.attributes) != len(source.attributes) + 1
    ):
        raise InvalidFootprintError("Attribute insert did not establish the attribute")
    return updated


def delete_attribute(source: ParsedFootprint, attribute_name: str) -> ParsedFootprint:
    """Remove one declared attribute node and its leading separator."""
    require_writeable(source.version)
    attribute_name = _symbol_parse._require_attribute_name(attribute_name)
    target = source.attribute(attribute_name)
    node = _property_node(source, target)
    before = source.document.source
    start = _symbol_parse._leading_separator_start(before, node.span.start)
    edited = _edit(before, SourceSpan(start, node.span.end), "")
    updated = read_source(edited.encode("utf-8"))
    if len(updated.attributes) != len(source.attributes) - 1:
        raise InvalidFootprintError("Attribute delete changed unexpected counts")
    return updated


def renamed_source(source: ParsedFootprint, old_name: str, new_name: str) -> str:
    """Rewrite the internal name, and a Value equal to *old_name*, to *new_name*.

    This is KiCad's rename and duplicate rule (``footprint_libraries_utils.cpp``).
    Only the two atoms change; every other byte is preserved.
    """
    edits = [TextEdit(_atom(source.root, 1).span, quote(new_name))]
    try:
        value = source.attribute("Value")
    except KeyError:
        value = None
    if value is not None and value.value == old_name:
        edits.append(
            TextEdit(_atom(_property_node(source, value), 2).span, quote(new_name))
        )
    return apply_edits(source.document.source, edits)


def new_footprint_source(name: str, *, generator_version: str) -> bytes:
    """Minimal KiCad 10 footprint: Reference, Value, no pads, no graphics."""
    return (
        f"(footprint {quote(name)}\n"
        f"\t(version {WRITE_VERSION})\n"
        '\t(generator "kicad_primitives")\n'
        f"\t(generator_version {quote(generator_version)})\n"
        '\t(layer "F.Cu")\n'
        '\t(property "Reference" "REF**"\n'
        "\t\t(at 0 -0.5 0)\n"
        '\t\t(layer "F.SilkS")\n'
        "\t\t(effects\n"
        "\t\t\t(font\n"
        "\t\t\t\t(size 1 1)\n"
        "\t\t\t\t(thickness 0.15)\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)\n"
        f'\t(property "Value" {quote(name)}\n'
        "\t\t(at 0 1 0)\n"
        '\t\t(layer "F.Fab")\n'
        "\t\t(effects\n"
        "\t\t\t(font\n"
        "\t\t\t\t(size 1 1)\n"
        "\t\t\t\t(thickness 0.15)\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)\n"
        "\t(embedded_fonts no)\n"
        ")\n"
    ).encode()
