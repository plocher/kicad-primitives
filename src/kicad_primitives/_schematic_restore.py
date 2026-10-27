"""Concrete cache materialization and independently captured electrical intent."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import TYPE_CHECKING

from lossless_sexpr import AtomNode, Document, ListNode, parse, quote

from .schematics import (
    AmbiguousEmbeddedSymbolError,
    InvalidSchematicError,
    Schematic,
    SchematicVerificationError,
    UnsupportedSchematicOperationError,
    _schematic_from_document,
)
from .symbols import SymbolLibrary

if TYPE_CHECKING:
    from ._schematic_persist import _ElectricalSignature

_GRAPHICS = frozenset(
    {"arc", "bezier", "circle", "polyline", "rectangle", "text", "text_box"}
)
_ORDINARY_TYPES = frozenset(
    {
        "input",
        "output",
        "bidirectional",
        "tri_state",
        "passive",
        "free",
        "unspecified",
        "open_collector",
        "open_emitter",
    }
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


@dataclass(frozen=True)
class _RestoreIntent:
    lib_id: str
    requested_chunk: str
    baseline_pins: tuple[_PinFact, ...]
    requested_pins: tuple[_PinFact, ...]


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


def cache_nodes(schematic: Schematic) -> dict[str, ListNode]:
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
        if previous.electrical_type != requested.electrical_type:
            if (
                previous.electrical_type not in _ORDINARY_TYPES
                or requested.electrical_type not in _ORDINARY_TYPES
                or previous.hidden
                or previous.alternates
                or old.child_lists("power")
                or new.child_lists("power")
                or any(
                    len(flag.children()) != 2 or _atom(flag, 1).value != "no"
                    for flag in old.child_lists("duplicate_pin_numbers_are_jumpers")
                )
            ):
                raise UnsupportedSchematicOperationError(
                    "Unsupported power/hidden/alternate pin type correction"
                )
            if any(p.unit not in {0, 1} or p.style not in {0, 1} for p in before):
                raise UnsupportedSchematicOperationError(
                    "Type correction requires simple unit/body mapping"
                )
            if len({p.number for p in before}) != len(before):
                raise UnsupportedSchematicOperationError(
                    "Type correction requires unique pin numbers"
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


def restore_definition(
    schematic: Schematic, lib_id: str, parent_library: SymbolLibrary, parent_name: str
) -> None:
    schematic._check_open()
    if not isinstance(parent_library, SymbolLibrary):
        raise TypeError("parent_library must be an opened SymbolLibrary")
    parent_library._check_open()
    if not isinstance(parent_name, str) or not parent_name:
        raise ValueError("parent_name must be a nonempty string")
    if schematic.version != 20260306 or parent_library.version != 20251024:
        raise UnsupportedSchematicOperationError(
            "Restore requires supported schematic and library formats"
        )
    parent_source = parent_library._source
    parent = parent_source.symbol(parent_name)
    node = parent_source.nodes[parent_source.symbols.index(parent)]
    target = cache_nodes(schematic)[lib_id]
    before_pins, requested_pins = _validate_delta(
        target, node, lib_id.rsplit(":", 1)[-1], parent_name
    )
    materialized = _materialize(parent_source.document, node, parent_name, lib_id)
    assert schematic._document is not None
    source = schematic._document.source
    if source[target.span.start : target.span.end] == materialized:
        return
    baseline_doc = parse(schematic._baseline.decode("utf-8"))
    baseline_node = _cache_nodes(baseline_doc)[lib_id]
    baseline_pins, _guard = _inventory(baseline_node, lib_id.rsplit(":", 1)[-1])
    intent = _RestoreIntent(lib_id, materialized, baseline_pins, requested_pins)
    if any(
        old.electrical_type != new.electrical_type
        for old, new in zip(before_pins, requested_pins, strict=True)
    ):
        _check_placements(schematic, intent)
    edited = source[: target.span.start] + materialized + source[target.span.end :]
    updated = _schematic_from_document(schematic.path, parse(edited))
    restored = cache_nodes(updated)[lib_id]
    assert updated._document is not None
    if (
        updated._document.source[restored.span.start : restored.span.end]
        != materialized
    ):
        raise InvalidSchematicError("Restore did not establish exact requested source")
    schematic._accept_document(updated)
    baseline_chunk = baseline_doc.source[
        baseline_node.span.start : baseline_node.span.end
    ]
    if materialized == baseline_chunk:
        schematic._restore_intents.pop(lib_id, None)
    else:
        schematic._restore_intents[lib_id] = intent


def _export_pins(pins: tuple[_PinFact, ...]) -> tuple[tuple[str, str, str], ...]:
    if len({pin.number for pin in pins}) != len(pins):
        raise UnsupportedSchematicOperationError(
            "Ambiguous unit/style export pin mapping"
        )
    return tuple(sorted((pin.number, pin.name, pin.electrical_type) for pin in pins))


def _check_placements(schematic: Schematic, intent: _RestoreIntent) -> tuple[str, ...]:
    qualified = intent.lib_id.rsplit(":", 1)
    if len(qualified) != 2 or not all(qualified):
        raise UnsupportedSchematicOperationError(
            "Type proof requires qualified cache identity"
        )
    matches = tuple(s for s in schematic.symbols if s.lib_id == intent.lib_id)
    if not matches or len({s.reference for s in matches}) != len(matches):
        raise UnsupportedSchematicOperationError(
            "Type correction requires observable unique placement references"
        )
    assert schematic._document is not None
    nodes = _root(schematic._document).child_lists("symbol")
    for symbol in matches:
        if (
            symbol.unit != 1
            or sum(s.reference == symbol.reference for s in schematic.symbols) != 1
            or not symbol.on_board
            or not symbol.in_bom
            or symbol.dnp
            or symbol.exclude_from_sim
            or not symbol.uuid
            or sum(s.uuid == symbol.uuid for s in schematic.symbols) != 1
        ):
            raise UnsupportedSchematicOperationError(
                "Excluded or multi-unit placement type proof is unsupported"
            )
        node = next(
            n
            for n in nodes
            if n.child_lists("uuid")
            and _atom(n.child_lists("uuid")[0], 1).value == symbol.uuid
        )
        converts = node.child_lists("convert")
        if len(converts) > 1 or (
            converts and _atom(converts[0], 1).value not in {"0", "1"}
        ):
            raise UnsupportedSchematicOperationError(
                "Alternate body-style type proof is unsupported"
            )
        if any(pin.child_lists("alternate") for pin in node.child_lists("pin")):
            raise UnsupportedSchematicOperationError(
                "Selected alternate pin type proof is unsupported"
            )
    return tuple(s.reference for s in matches)


def predict_restored_signature(
    before: _ElectricalSignature,
    documents: tuple[Schematic, ...],
    changed: tuple[Schematic, ...],
) -> _ElectricalSignature:
    """Predict actual export effects from baseline evidence and captured facts only."""
    node_updates: dict[tuple[str, str], tuple[str, str]] = {}
    part_updates: dict[tuple[str, str], tuple[tuple[str, str, str], ...]] = {}
    for schematic in changed:
        for intent in schematic._restore_intents.values():
            node = cache_nodes(schematic)[intent.lib_id]
            assert schematic._document is not None
            if (
                schematic._document.source[node.span.start : node.span.end]
                != intent.requested_chunk
            ):
                raise SchematicVerificationError(
                    "Captured restore source no longer matches pending content"
                )
            corrections = tuple(
                (old, new)
                for old, new in zip(
                    intent.baseline_pins, intent.requested_pins, strict=True
                )
                if old.electrical_type != new.electrical_type
            )
            if not corrections:
                continue
            if ":" not in intent.lib_id:
                raise UnsupportedSchematicOperationError(
                    "Type proof requires qualified cache identity"
                )
            key = tuple(intent.lib_id.rsplit(":", 1))
            lib, part = key
            baseline_pins = _export_pins(intent.baseline_pins)
            requested_pins = _export_pins(intent.requested_pins)
            # A global libpart cannot prove conflicting sheet-local cache variants.
            for document in documents:
                if not any(s.lib_id == intent.lib_id for s in document.symbols):
                    continue
                baseline = parse(document._baseline.decode("utf-8"))
                local_pins, _guard = _inventory(
                    _cache_nodes(baseline)[intent.lib_id], part
                )
                pending = (
                    document._restore_intents.get(intent.lib_id)
                    if document in changed
                    else None
                )
                local_after = pending.requested_pins if pending else local_pins
                if (
                    _export_pins(local_pins) != baseline_pins
                    or _export_pins(local_after) != requested_pins
                ):
                    raise UnsupportedSchematicOperationError(
                        "Sheet-local cache variants have ambiguous libpart proof"
                    )
            evidence = tuple(
                pins
                for library, name, pins in before.libparts
                if (library, name) == (lib, part)
            )
            if evidence != (baseline_pins,):
                raise SchematicVerificationError(
                    "Baseline libpart does not prove the complete source pin inventory"
                )
            part_updates[(lib, part)] = requested_pins
            for reference in _check_placements(schematic, intent):
                components = tuple(c for c in before.components if c[0] == reference)
                if len(components) != 1 or components[0][1:3] != (lib, part):
                    raise UnsupportedSchematicOperationError(
                        "Placement type correction is unobservable in baseline export"
                    )
                for old, new in corrections:
                    identity = reference, old.number
                    if identity in node_updates:
                        raise UnsupportedSchematicOperationError(
                            "Ambiguous placement pin correction"
                        )
                    node_updates[identity] = old.electrical_type, new.electrical_type
    occurrences = dict.fromkeys(node_updates, 0)
    nets: list[tuple[str, tuple[tuple[str, str, str, str], ...]]] = []
    for name, nodes in before.nets:
        predicted_nodes: list[tuple[str, str, str, str]] = []
        for reference, pin, function, electrical_type in nodes:
            correction = node_updates.get((reference, pin))
            if correction is not None:
                old_type, new_type = correction
                if electrical_type != old_type:
                    raise UnsupportedSchematicOperationError(
                        "Baseline pin type mapping is not directly observable"
                    )
                occurrences[(reference, pin)] += 1
                electrical_type = new_type
            predicted_nodes.append((reference, pin, function, electrical_type))
        nets.append((name, tuple(sorted(predicted_nodes))))
    if any(count != 1 for count in occurrences.values()):
        raise UnsupportedSchematicOperationError(
            "Every corrected placement pin must have one exported occurrence"
        )
    libparts = tuple(
        (lib, part, part_updates.get((lib, part), pins))
        for lib, part, pins in before.libparts
    )
    return replace(before, nets=tuple(sorted(nets)), libparts=libparts)
