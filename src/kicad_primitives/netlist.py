"""Parse and obtain KiCad kicadsexpr netlist **exchange** files.

This module is the ADR 0006 Connectivity **B** exchange slice: read existing
``.net`` exports and obtain fresh ones via private ``kicad-cli`` discovery
(ADR 0007). It is **not** the full project-owned Connectivity area (trace,
live design model, or project-context service). A saved ``.net`` can be stale;
callers that keep one accept that risk.

See ``docs/netlist.md``.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from types import MappingProxyType

from lossless_sexpr import AtomNode, ListNode, ParseError, parse

from ._kicad_cli import KicadCliNotFoundError, resolve_kicad_cli

__all__ = [
    "KicadCliNotFoundError",
    "Net",
    "NetNode",
    "Netlist",
    "NetlistComponent",
    "NetlistError",
    "NetlistExportError",
    "NetlistParseError",
    "connectivity_sets",
    "export_netlist",
    "obtain_netlist",
]


class NetlistError(Exception):
    """Shared base for netlist exchange failures."""


class NetlistParseError(NetlistError, ValueError):
    """A netlist file is missing, invalid, or cannot be parsed as kicadsexpr."""


class NetlistExportError(NetlistError, RuntimeError):
    """``kicad-cli sch export netlist`` failed or wrote no file."""


@dataclass(frozen=True)
class NetNode:
    """One pin attachment on a net."""

    reference: str
    pin: str
    pinfunction: str = ""
    pintype: str = ""


@dataclass(frozen=True)
class Net:
    """One named net with zero or more connected nodes."""

    code: str
    name: str
    nodes: tuple[NetNode, ...]


@dataclass(frozen=True)
class NetlistComponent:
    """One component instance from a KiCad netlist export."""

    reference: str
    value: str
    lib: str
    part: str
    fields: Mapping[str, str]
    sheetpath: str = ""

    @property
    def lib_id(self) -> str:
        """Return ``lib:part`` when both sides are present."""
        if self.lib and self.part:
            return f"{self.lib}:{self.part}"
        return self.part or self.lib


@dataclass(frozen=True)
class Netlist:
    """Parsed KiCad kicadsexpr netlist exchange dataset."""

    path: Path
    source: str
    version: str
    components: Mapping[str, NetlistComponent]
    nets: tuple[Net, ...]
    sheets: tuple[str, ...]
    sheet_files: Mapping[str, str]

    @classmethod
    def open(cls, path: str | PathLike[str]) -> Netlist:
        """Read a kicadsexpr ``.net`` file without invoking KiCad.

        Raises:
            FileNotFoundError: the path does not exist.
            NetlistParseError: the file is not a usable ``(export …)`` netlist.
        """
        location = Path(path).expanduser().resolve()
        if not location.is_file():
            raise FileNotFoundError(f"Netlist not found: {location}")
        try:
            text = location.read_text(encoding="utf-8")
        except OSError as exc:
            raise NetlistParseError(f"Cannot read netlist: {location}: {exc}") from exc
        if not text.lstrip().startswith("(export"):
            raise NetlistParseError(f"Root is not export: {location}")
        try:
            document = parse(text)
        except ParseError as exc:
            raise NetlistParseError(
                f"Failed to parse netlist: {location}: {exc}"
            ) from exc
        roots = [node for node in document.roots() if isinstance(node, ListNode)]
        if not roots or roots[0].head != "export":
            raise NetlistParseError(f"Root node is not export: {location}")
        return _parse_export(roots[0], location)

    def component(self, reference: str) -> NetlistComponent:
        """Return one component by reference designator."""
        try:
            return self.components[reference]
        except KeyError as exc:
            raise KeyError(f"Component not found: {reference}") from exc

    def net(self, name: str) -> Net:
        """Return the first net with the given name."""
        for item in self.nets:
            if item.name == name:
                return item
        raise KeyError(f"Net not found: {name}")


def connectivity_sets(
    netlist: Netlist,
    *,
    ignore: re.Pattern[str] | None = None,
) -> frozenset[frozenset[tuple[str, str]]]:
    """Connectivity as frozensets of ``(reference, pin)``, ignoring net names.

    Single-node nets are dropped (same rule as Subdivision ``netlist_diff``).
    When *ignore* is set, nodes whose reference matches are omitted.
    """
    nets: set[frozenset[tuple[str, str]]] = set()
    for net in netlist.nets:
        nodes = frozenset(
            (node.reference, node.pin)
            for node in net.nodes
            if not (ignore is not None and ignore.search(node.reference))
        )
        if len(nodes) > 1:
            nets.add(nodes)
    return frozenset(nets)


def export_netlist(
    schematic_path: str | PathLike[str],
    output_path: str | PathLike[str] | None = None,
    *,
    kicad_cli: str | PathLike[str] | None = None,
) -> Path:
    """Export a kicadsexpr netlist for *schematic_path* via ``kicad-cli``.

    Discovery follows ADR 0007. When *output_path* is omitted, a temporary
    ``.net`` file is created (caller owns cleanup). Prefer
    :func:`obtain_netlist` for a parse-and-discard obtain path.

    Raises:
        FileNotFoundError: schematic missing.
        KicadCliNotFoundError: discovery failed.
        NetlistExportError: CLI non-zero exit or missing output file.
    """
    schematic = Path(schematic_path).expanduser().resolve()
    if not schematic.is_file():
        raise FileNotFoundError(f"Schematic not found: {schematic}")
    cli = resolve_kicad_cli(None if kicad_cli is None else Path(kicad_cli))
    if output_path is None:
        handle, name = tempfile.mkstemp(
            prefix="kicad-primitives-netlist-", suffix=".net"
        )
        os.close(handle)
        destination = Path(name)
    else:
        destination = Path(output_path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)

    command = [
        str(cli),
        "sch",
        "export",
        "netlist",
        "--format",
        "kicadsexpr",
        "-o",
        str(destination),
        str(schematic),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except OSError as exc:
        raise NetlistExportError(f"Failed to run kicad-cli: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise NetlistExportError(
            f"kicad-cli netlist export failed ({completed.returncode}): {detail}"
        )
    if not destination.is_file():
        raise NetlistExportError(
            f"kicad-cli reported success but wrote no file: {destination}"
        )
    return destination


def obtain_netlist(
    schematic_path: str | PathLike[str],
    *,
    kicad_cli: str | PathLike[str] | None = None,
) -> Netlist:
    """Export a fresh netlist to a temp file, parse it, then delete the file.

    A netlist is a cache of schematic state and is invalid as soon as the design
    changes. This helper keeps that cache volatile. Callers that must keep a
    saved ``.net`` (for example a machine without KiCad) take staleness on
    themselves via :meth:`Netlist.open` or :func:`export_netlist`.
    """
    with tempfile.TemporaryDirectory(prefix="kicad-primitives-netlist-") as tmp:
        path = export_netlist(
            schematic_path,
            Path(tmp) / "fresh.net",
            kicad_cli=kicad_cli,
        )
        return Netlist.open(path)


def _parse_export(root: ListNode, path: Path) -> Netlist:
    version = ""
    source = ""
    sheets: list[str] = []
    sheet_files: dict[str, str] = {}
    components: dict[str, NetlistComponent] = {}
    nets: list[Net] = []

    version_node = _one(root, "version")
    if version_node is not None:
        version = _atom_str(version_node, 1)

    design = _one(root, "design")
    if design is not None:
        source, sheets, sheet_files = _parse_design(design)

    components_node = _one(root, "components")
    if components_node is not None:
        for comp_node in components_node.child_lists("comp"):
            component = _parse_component(comp_node)
            if component is not None:
                components[component.reference] = component

    nets_node = _one(root, "nets")
    if nets_node is not None:
        for net_node in nets_node.child_lists("net"):
            net = _parse_net(net_node)
            if net is not None:
                nets.append(net)

    return Netlist(
        path=path,
        source=source,
        version=version,
        components=MappingProxyType(components),
        nets=tuple(nets),
        sheets=tuple(sheets),
        sheet_files=MappingProxyType(dict(sheet_files)),
    )


def _parse_design(
    design: ListNode,
) -> tuple[str, list[str], dict[str, str]]:
    source = ""
    sheets: list[str] = []
    sheet_files: dict[str, str] = {}
    source_node = _one(design, "source")
    if source_node is not None:
        source = _atom_str(source_node, 1)
    for sheet in design.child_lists("sheet"):
        name_node = _one(sheet, "name")
        name = _atom_str(name_node, 1) if name_node is not None else ""
        file_name = ""
        title_block = _one(sheet, "title_block")
        if title_block is not None:
            tb_source = _one(title_block, "source")
            if tb_source is not None:
                file_name = _atom_str(tb_source, 1)
        if name:
            sheets.append(name)
            if file_name:
                sheet_files[name] = file_name
    return source, sheets, sheet_files


def _parse_component(node: ListNode) -> NetlistComponent | None:
    reference = ""
    value = ""
    lib = ""
    part = ""
    sheetpath = ""
    fields: dict[str, str] = {}

    ref_node = _one(node, "ref")
    if ref_node is not None:
        reference = _atom_str(ref_node, 1)
    value_node = _one(node, "value")
    if value_node is not None:
        value = _atom_str(value_node, 1)

    libsource = _one(node, "libsource")
    if libsource is not None:
        lib_node = _one(libsource, "lib")
        part_node = _one(libsource, "part")
        if lib_node is not None:
            lib = _atom_str(lib_node, 1)
        if part_node is not None:
            part = _atom_str(part_node, 1)

    sheetpath_node = _one(node, "sheetpath")
    if sheetpath_node is not None:
        names = _one(sheetpath_node, "names")
        if names is not None:
            sheetpath = _atom_str(names, 1)

    fields_node = _one(node, "fields")
    if fields_node is not None:
        for field_node in fields_node.child_lists("field"):
            parsed = _parse_field(field_node)
            if parsed is not None:
                fields[parsed[0]] = parsed[1]

    for prop in node.child_lists("property"):
        name_node = _one(prop, "name")
        value_prop = _one(prop, "value")
        if name_node is None:
            continue
        name = _atom_str(name_node, 1)
        if not name:
            continue
        prop_value = _atom_str(value_prop, 1) if value_prop is not None else ""
        fields.setdefault(name, prop_value)

    if not reference:
        return None
    return NetlistComponent(
        reference=reference,
        value=value,
        lib=lib,
        part=part,
        fields=MappingProxyType(fields),
        sheetpath=sheetpath,
    )


def _parse_field(node: ListNode) -> tuple[str, str] | None:
    """Parse ``(field (name \"X\") \"Y\")`` or name-only field rows."""
    name_node = _one(node, "name")
    if name_node is None:
        return None
    name = _atom_str(name_node, 1)
    if not name:
        return None
    value = ""
    for child in node.children()[1:]:
        if isinstance(child, AtomNode):
            value = child.value
            break
    return name, value


def _parse_net(node: ListNode) -> Net | None:
    code = ""
    name = ""
    nodes: list[NetNode] = []
    code_node = _one(node, "code")
    if code_node is not None:
        code = _atom_str(code_node, 1)
    name_node = _one(node, "name")
    if name_node is not None:
        name = _atom_str(name_node, 1)
    for pin_node in node.child_lists("node"):
        net_node = _parse_node(pin_node)
        if net_node is not None:
            nodes.append(net_node)
    if not name and not code:
        return None
    return Net(code=code, name=name, nodes=tuple(nodes))


def _parse_node(node: ListNode) -> NetNode | None:
    reference = ""
    pin = ""
    pinfunction = ""
    pintype = ""
    ref_node = _one(node, "ref")
    if ref_node is not None:
        reference = _atom_str(ref_node, 1)
    pin_node = _one(node, "pin")
    if pin_node is not None:
        pin = _atom_str(pin_node, 1)
    fn_node = _one(node, "pinfunction")
    if fn_node is not None:
        pinfunction = _atom_str(fn_node, 1)
    type_node = _one(node, "pintype")
    if type_node is not None:
        pintype = _atom_str(type_node, 1)
    if not reference or not pin:
        return None
    return NetNode(
        reference=reference,
        pin=pin,
        pinfunction=pinfunction,
        pintype=pintype,
    )


def _one(node: ListNode, head: str) -> ListNode | None:
    matches = node.child_lists(head)
    return matches[0] if matches else None


def _atom_str(node: ListNode, index: int) -> str:
    atom = node.atom(index)
    if atom is None:
        return ""
    return atom.value
