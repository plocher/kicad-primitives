"""Inspect and edit schematic content within project context.

Parsing uses the private lossless S-expression foundation (ADR 0003).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from math import isfinite
from os import PathLike
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import TYPE_CHECKING, Literal, Self

from lossless_sexpr import AtomNode, Document, ListNode, ParseError, parse, quote

from . import _symbol_persist
from ._erc_types import (
    ErcAcquisitionError,
    ErcContextError,
    ErcIgnoredCheck,
    ErcItem,
    ErcPosition,
    ErcReport,
    ErcSheet,
    ErcSnapshot,
    ErcViolation,
)
from ._svg_types import SchematicSvgError, SchematicSvgExport, SchematicSvgFile
from ._symbol_parse import _leading_separator_start
from ._symbol_persist import Fingerprint
from ._symbol_types import _MANDATORY, _attribute_key

_FLAG_NAMES = frozenset(
    {"dnp", "in_bom", "on_board", "in_pos_files", "exclude_from_sim"}
)
# The KiCad 10 sheet-file format that the package edits and writes.
_WRITE_VERSION = 20260306

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
    "SchematicLifecycleError",
    "SchematicSaveError",
    "SchematicSvgError",
    "SchematicSvgExport",
    "SchematicSvgFile",
    "SchematicVerificationError",
    "SheetFile",
    "SheetSaveResult",
    "SheetSaveStatus",
    "SheetSymbol",
    "TitleBlock",
    "UnsupportedSchematicOperationError",
    "Wire",
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


class SchematicLifecycleError(RuntimeError):
    """A sheet file is closed or discarded."""


SheetSaveStatus = Literal["written", "conflict", "failed", "unsaved"]


@dataclass(frozen=True)
class SheetSaveResult:
    """What :meth:`Schematic.save` did with one changed sheet file.

    ``written``: saved. ``conflict``: the disk file is not the file read; not
    written. ``failed``: an error stopped this file; ``reason`` says which.
    ``unsaved``: not attempted, because the save stopped first.
    """

    path: Path
    status: SheetSaveStatus
    reason: str = ""


class SchematicSaveError(SchematicError):
    """``Schematic.save()`` did not write every changed sheet file.

    ``results`` lists each changed sheet file, children before parents, as
    written, conflict, failed, or unsaved, with the reason. Written files
    are saved; all others keep their unsaved changes.
    """

    def __init__(self, message: str, results: tuple[SheetSaveResult, ...]) -> None:
        detail = "; ".join(
            f"{result.path.name}: {result.status}"
            + (f" ({result.reason})" if result.reason else "")
            for result in results
        )
        super().__init__(f"{message}: {detail}" if detail else message)
        self.results = results


@dataclass(frozen=True)
class TitleBlock:
    """Title-block metadata from one schematic file."""

    title: str = ""
    revision: str = ""
    date: str = ""
    company: str = ""
    comments: Mapping[int, str] = field(default_factory=lambda: MappingProxyType({}))


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
    _owner: SheetFile | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _index: int = field(default=-1, init=False, repr=False, compare=False)

    def set_attribute(self, name: str, value: str) -> None:
        """Establish an attribute in memory, without writing or annotating Reference.

        Create missing attributes, update differing values, and leave equal values
        byte-identical. Ambiguous or unsupported edits fail without changing source.
        """
        if self._owner is None:
            raise UnsupportedSchematicOperationError("Symbol has no owning sheet file")
        self._owner._set_attribute(self, name, value)

    def delete_attribute(self, name: str) -> None:
        """Remove one custom attribute in memory, without writing.

        Remove only the selected ``(property ...)`` node and its leading
        separator. A missing name raises ``KeyError``. A repeated name raises
        ``AmbiguousPlacedSymbolError``. Mandatory attributes (Reference, Value,
        Footprint, Datasheet, Description) and flag names raise
        ``UnsupportedSchematicOperationError``. Failures leave source unchanged.
        """
        if self._owner is None:
            raise UnsupportedSchematicOperationError("Symbol has no owning sheet file")
        self._owner._delete_attribute(self, name)

    def attribute(self, name: str) -> PlacedAttribute:
        """Return the unique attribute with this name."""
        if self._owner is not None:
            self._owner._check_open()
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
    _owner: SheetFile = field(repr=False, compare=False)
    _alive: bool = field(default=True, init=False, repr=False, compare=False)

    def restore_from(self, parent_library: SymbolLibrary, parent_name: str) -> None:
        """Restore this concrete definition from captured parent source in memory.

        Preserve placements and unrelated source. Ordinary visible pin-type
        corrections require explicit-save electrical proof. Unsupported
        inheritance or electrical changes fail before changing the schematic.
        """
        from ._schematic_restore import restore_definition

        if not self._alive:
            raise UnsupportedSchematicOperationError(
                f"Embedded symbol handle is stale after revert: {self.lib_id}"
            )

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
class SheetSymbol:
    """The box on a parent sheet file that points at a target sheet file (KiCad ``SCH_SHEET``)."""

    name: str
    filename: str
    x: float
    y: float
    width: float
    height: float
    uuid: str = ""


@dataclass(frozen=True, eq=False)
class SheetFile:
    """One ``.kicad_sch`` file: symbols, title block, and electrical geometry.

    KiCad ``SCH_SCREEN``. One object per file, even when several sheet symbols
    use it. A layer-0 artifact with the full lifecycle: open, read, modify,
    validate, save, revert, discard, and close. A sheet file knows nothing
    about the hierarchy, so it cannot keep a parent sheet symbol's pins
    matched with its hierarchical labels.
    """

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
    sheet_symbols: tuple[SheetSymbol, ...] = ()
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
    _fingerprint: Fingerprint | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _modified: bool = field(default=False, init=False, repr=False, compare=False)
    _closed: bool = field(default=False, init=False, repr=False, compare=False)

    @classmethod
    def open(cls, path: str | PathLike[str]) -> SheetFile:
        """Open one ``.kicad_sch`` file as a layer-0 artifact, outside a project.

        Record a fingerprint (size and content hash) of the bytes read. A
        missing, non-``.kicad_sch``, or unparsable file raises
        :class:`InvalidSchematicError`. Project sheet files come from
        :meth:`kicad_primitives.projects.Project.schematic` instead.
        """
        return _read_sheet_file(Path(path).expanduser().absolute())

    def _check_open(self) -> None:
        if self._closed:
            raise SchematicLifecycleError(f"Sheet file is closed: {self.path}")
        if self._project is not None:
            self._project._check_open()

    @property
    def is_closed(self) -> bool:
        """Whether this sheet file exited through close or discard."""
        return self._closed or (self._project is not None and self._project.is_closed)

    def validate(self) -> None:
        """Check that the current content can be written; write nothing, run no KiCad.

        Raises:
            UnsupportedSchematicOperationError: the format is read-only.
            InvalidSchematicError: the current source is not a valid sheet file.
        """
        self._check_open()
        if self.version != _WRITE_VERSION:
            raise UnsupportedSchematicOperationError(
                f"Sheet file format {self.version} is read-only: {self.path}"
            )
        assert self._document is not None
        try:
            _sheet_file_from_document(self.path, parse(self._document.source))
        except (ParseError, RecursionError) as exc:
            raise InvalidSchematicError(f"Invalid sheet file source: {exc}") from exc

    def save(self, *, overwrite: bool = False) -> None:
        """Write this file to its opened location when it has unsaved changes.

        A clean save writes nothing. A changed save runs :meth:`validate`,
        then replaces the file atomically. It runs no KiCad, makes no backup,
        and checks no lock. If the disk file is not the file that was read,
        raise :class:`SchematicConflictError` and write nothing, unless
        *overwrite* is true (ADR 0009). Failures keep the unsaved changes.
        """
        self._check_open()
        if not self._modified:
            return
        self.validate()
        output = self.to_bytes()
        _symbol_persist.save_source(
            self.path,
            None if overwrite else self._fingerprint,
            output,
            conflict_error=SchematicConflictError,
            unsupported_error=UnsupportedSchematicOperationError,
            label="Sheet file",
        )
        self._mark_saved(output)

    def _mark_saved(self, output: bytes) -> None:
        """Record that *output* is now the disk content."""
        object.__setattr__(self, "_baseline", output)
        object.__setattr__(self, "_fingerprint", Fingerprint.of(output))
        object.__setattr__(self, "_modified", self.to_bytes() != output)

    def revert(self) -> None:
        """Drop unsaved changes and reload this file from disk.

        The object keeps its identity and ``is_modified`` becomes false.
        Placed-symbol and embedded-symbol handles taken before the revert
        become stale; get fresh ones. A missing file, or a disk file that is
        not the file that was read, raises :class:`SchematicConflictError`
        and changes nothing.
        """
        self._check_open()
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError as exc:
            raise SchematicConflictError(
                f"Sheet file no longer exists: {self.path}"
            ) from exc
        if self._fingerprint is not None and not self._fingerprint.matches(raw):
            raise SchematicConflictError(f"Sheet file changed on disk: {self.path}")
        self._adopt(_parse_sheet_file(self.path, raw), raw)

    def _adopt(self, fresh: SheetFile, raw: bytes) -> None:
        """Replace content with *fresh*, read from *raw*; invalidate old handles."""
        for symbol in self.symbols:
            object.__setattr__(symbol, "_owner", None)
        for handle in self._embedded_handles.values():
            object.__setattr__(handle, "_alive", False)
        self._embedded_handles.clear()
        self._restore_intents.clear()
        for item in fields(self):
            if item.init and item.name != "path":
                object.__setattr__(self, item.name, getattr(fresh, item.name))
        for symbol in self.symbols:
            object.__setattr__(symbol, "_owner", self)
        object.__setattr__(self, "_document", fresh._document)
        object.__setattr__(self, "_baseline", raw)
        object.__setattr__(self, "_fingerprint", Fingerprint.of(raw))
        object.__setattr__(self, "_modified", False)

    def discard(self) -> None:
        """End this sheet file without a read or a write; it cannot fail.

        A project-owned sheet file ends with its project; discarding it alone
        is not supported yet (#78) and raises
        :class:`UnsupportedSchematicOperationError`.
        """
        if self._closed:
            return
        if self._project is not None:
            raise UnsupportedSchematicOperationError(
                "A project-owned sheet file ends with its project (#78)"
            )
        object.__setattr__(self, "_closed", True)

    def close(self) -> None:
        """Save when there are unsaved changes, then end this sheet file.

        If the save fails, the error propagates and the file stays open with
        its changes. Close is idempotent. A project-owned sheet file closes
        with its project; closing it alone raises
        :class:`UnsupportedSchematicOperationError` (#78).
        """
        if self._closed:
            return
        if self._project is not None:
            raise UnsupportedSchematicOperationError(
                "A project-owned sheet file closes with its project (#78)"
            )
        if self._modified:
            self.save()
        object.__setattr__(self, "_closed", True)

    def __enter__(self) -> Self:
        """Use the open sheet file as a context manager."""
        self._check_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close on normal exit; discard without writing when an exception exits."""
        if exc_type is None:
            self.close()
        else:
            self.discard()

    @property
    def embedded_symbols(self) -> tuple[EmbeddedSymbol, ...]:
        """Embedded definitions in source order, with stable object identity."""
        self._check_open()
        from ._schematic_restore import cache_nodes

        nodes = cache_nodes(self)
        for lib_id in nodes:
            if lib_id not in self._embedded_handles:
                self._embedded_handles[lib_id] = EmbeddedSymbol(lib_id, self)
        return tuple(self._embedded_handles[lib_id] for lib_id in nodes)

    def embedded_symbol(self, lib_id: str) -> EmbeddedSymbol:
        """Select one unambiguous embedded definition, or raise KeyError."""
        self._check_open()
        for symbol in self.embedded_symbols:
            if symbol.lib_id == lib_id:
                return symbol
        raise KeyError(lib_id)

    @property
    def is_modified(self) -> bool:
        """Whether an edit changed this file since it was opened, saved, or reverted.

        Edits set the flag (ADR 0009). An edit back to the original content
        leaves it set; save or revert clears it.
        """
        self._check_open()
        return self._modified

    def to_bytes(self) -> bytes:
        """Preview pending source without writing or running electrical checks."""
        self._check_open()
        if self._document is None:
            raise UnsupportedSchematicOperationError("Schematic has no source")
        return self._document.source.encode("utf-8")

    def erc(self, *, kicad_cli: str | PathLike[str] | None = None) -> ErcReport:
        """Reject document-only ERC because the backend cannot honor that scope."""
        self._check_open()
        raise UnsupportedSchematicOperationError(
            "Document-only ERC is unsupported; request the full hierarchy on Project.erc"
        )

    def _set_attribute(self, symbol: PlacedSymbol, name: str, value: str) -> None:
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError("Attribute name and value must be strings")
        self._check_open()
        if not name or "\x00" in name or "\x00" in value:
            raise ValueError("Attribute name must be nonempty; NUL is not supported")
        name.encode("utf-8")
        value.encode("utf-8")
        root, node = self._editable_node(symbol)
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
        if name in _FLAG_NAMES:
            raise UnsupportedSchematicOperationError("Flags are not named attributes")
        if _attribute_key(name) == "value" and _is_power_symbol(root, symbol):
            raise UnsupportedSchematicOperationError(
                "Power-symbol Value changes are electrical edits"
            )
        assert self._document is not None
        before = self._document.source
        if matches:
            token = _atom(matches[0], 2)
            start, end, replacement = token.span.start, token.span.end, quote(value)
        else:
            anchor = node.child_lists("property")[-1]
            start = end = anchor.span.end
            replacement = _attribute_fragment(before, node, anchor, name, value)
        edited = before[:start] + replacement + before[end:]
        updated = _sheet_file_from_document(self.path, parse(edited))
        if updated.symbols[symbol._index].attribute(name).value != value:
            raise InvalidSchematicError(
                "Edit did not establish the requested attribute"
            )
        self._accept_document(updated)

    def _editable_node(self, symbol: PlacedSymbol) -> tuple[ListNode, ListNode]:
        """Return the root and the writable source node for one placed symbol."""
        if self.version != _WRITE_VERSION:
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
        return root, node

    def _delete_attribute(self, symbol: PlacedSymbol, name: str) -> None:
        if not isinstance(name, str):
            raise TypeError("Attribute name must be a string")
        self._check_open()
        if not name or "\x00" in name:
            raise ValueError("Attribute name must be nonempty; NUL is not supported")
        name.encode("utf-8")
        if _attribute_key(name) in _MANDATORY:
            raise UnsupportedSchematicOperationError(
                f"Mandatory attribute {name!r} cannot be deleted"
            )
        if name in _FLAG_NAMES:
            raise UnsupportedSchematicOperationError("Flags are not named attributes")
        _root, node = self._editable_node(symbol)
        matches = tuple(
            p for p in node.child_lists("property") if _atom(p, 1).value == name
        )
        if not matches:
            raise KeyError(name)
        if len(matches) > 1:
            raise AmbiguousPlacedSymbolError(f"Ambiguous attribute {name!r}")
        assert self._document is not None
        before = self._document.source
        start = _leading_separator_start(before, matches[0].span.start)
        edited = before[:start] + before[matches[0].span.end :]
        updated = _sheet_file_from_document(self.path, parse(edited))
        remaining = updated.symbols[symbol._index]
        if (
            any(p.name == name for p in remaining.attributes)
            or len(remaining.attributes) != len(symbol.attributes) - 1
        ):
            raise InvalidSchematicError("Edit did not remove the requested attribute")
        self._accept_document(updated)

    def _accept_document(self, updated: SheetFile) -> None:
        self._check_open()
        changed = self.to_bytes() != updated.to_bytes()
        for old, new in zip(self.symbols, updated.symbols, strict=True):
            object.__setattr__(old, "attributes", new.attributes)
            object.__setattr__(old, "value", new.value)
            object.__setattr__(old, "footprint", new.footprint)
        object.__setattr__(self, "_document", updated._document)
        if changed:
            object.__setattr__(self, "_modified", True)

    def symbol(self, reference: str) -> PlacedSymbol:
        """Return the unique placed symbol with this reference."""
        self._check_open()
        matches = tuple(s for s in self.symbols if s.reference == reference)
        if not matches:
            raise KeyError(reference)
        if len(matches) > 1:
            raise AmbiguousPlacedSymbolError(
                f"Ambiguous placed symbol reference {reference!r}"
            )
        return matches[0]


class Schematic:
    """The project's set of sheet trees, as one document (KiCad ``SCHEMATIC``).

    Opening loads every sheet file reachable from the top-level sheets. A file
    that several sheet symbols use loads once, as one :class:`SheetFile`.
    There is no hidden root: each top-level sheet is the root of one tree.
    Entry is through :meth:`kicad_primitives.projects.Project.schematic`.
    """

    def __init__(self, project: Project, roots: tuple[Path, ...]) -> None:
        self._project = project
        self._roots = roots
        self._files: dict[Path, SheetFile] = {}
        self._load()

    def _check_open(self) -> None:
        self._project._check_open()

    def _load(self) -> None:
        """Walk every tree; reuse loaded sheet files that are still reachable."""
        previous = self._files
        loaded: dict[Path, SheetFile] = {}
        active: set[Path] = set()

        def visit(path: Path) -> None:
            if path in active:
                raise UnsupportedSchematicOperationError(
                    f"Cyclic schematic hierarchy: {path}"
                )
            if path in loaded:
                return
            if not path.is_file():
                raise InvalidSchematicError(f"Missing sheet file: {path}")
            sheet_file = previous.get(path)
            if sheet_file is None:
                sheet_file = _read_sheet_file(path)
                object.__setattr__(sheet_file, "_project", self._project)
            loaded[path] = sheet_file
            active.add(path)
            for sheet in sheet_file.sheet_symbols:
                if "${" in sheet.filename:
                    raise UnsupportedSchematicOperationError(
                        f"Unsupported Sheetfile with a variable: {sheet.filename}"
                    )
                visit(Path(os.path.normpath(path.parent / sheet.filename)))
            active.remove(path)

        for root in self._roots:
            visit(Path(os.path.abspath(root)))
        self._files = loaded

    @property
    def files(self) -> tuple[SheetFile, ...]:
        """Every sheet file once, in walk order: each tree depth-first, roots first."""
        self._check_open()
        return tuple(self._files.values())

    @property
    def root_files(self) -> tuple[SheetFile, ...]:
        """The sheet files of the top-level sheets, in project order."""
        self._check_open()
        return tuple(self._files[Path(os.path.abspath(root))] for root in self._roots)

    def file(self, path: str | PathLike[str]) -> SheetFile:
        """Return the sheet file at *path*, or raise ``KeyError`` for an outsider."""
        self._check_open()
        target = Path(path).expanduser().resolve()
        for sheet_file in self._files.values():
            if sheet_file.path.resolve() == target:
                return sheet_file
        raise KeyError(f"Sheet file is not part of this schematic: {target}")

    @property
    def is_modified(self) -> bool:
        """Whether any sheet file has unsaved changes."""
        self._check_open()
        return any(sheet_file.is_modified for sheet_file in self._files.values())

    def validate(self) -> None:
        """Run the content checks on every changed sheet file; write nothing.

        Raises:
            SchematicSaveError: some changed sheet files have invalid content
                or a read-only format. ``results`` names them.
        """
        self._check_open()
        from . import _schematic_save

        _schematic_save.validate(self)

    def save(self, *, overwrite: bool = False) -> None:
        """Write the sheet files that have unsaved changes; touch no others.

        This deviates from KiCad on purpose (ADR 0011 D3): KiCad rewrites
        every sheet file. A clean save writes nothing. Child sheet files are
        written before their parents. The save runs no KiCad, makes no
        backup, and checks no lock.

        Failure policy (ADR 0011 D4): invalid content, an unwritable target,
        or missing permissions found before any write stop the save with
        nothing written. A conflict (the disk file is not the file read)
        leaves that sheet unsaved and is never retried; *overwrite* is the
        explicit way through. A short-lived system error is retried once at
        the end. A lasting or unknown system error stops the save at once.

        Raises:
            SchematicSaveError: not every changed sheet file was written.
                ``results`` lists each one. A later save writes only what is
                still unsaved.
        """
        self._check_open()
        from . import _schematic_save

        _schematic_save.save(self, overwrite=overwrite)

    def revert(self) -> None:
        """Drop all unsaved changes and reload the whole hierarchy from disk.

        The Schematic and its sheet files keep their identity, and
        ``is_modified`` becomes false. Handles to things inside them become
        stale; get fresh ones. Every sheet file is checked first: if any is
        missing or is not the file that was read, raise
        :class:`SchematicConflictError` naming them, and change nothing. The
        trees are walked again, so sheet files that are no longer reachable
        leave :attr:`files` and newly reachable ones join it.
        """
        self._check_open()
        conflicts = [
            sheet_file.path
            for sheet_file in self._files.values()
            if not _matches_disk(sheet_file)
        ]
        if conflicts:
            names = ", ".join(str(path) for path in conflicts)
            raise SchematicConflictError(f"Cannot revert; changed on disk: {names}")
        for sheet_file in self._files.values():
            sheet_file.revert()
        self._load()

    def _write_order(self) -> tuple[SheetFile, ...]:
        """Every loaded sheet file once, each child before its parents."""
        order: dict[Path, SheetFile] = {}

        def visit(path: Path) -> None:
            if path in order or path not in self._files:
                return
            sheet_file = self._files[path]
            for sheet in sheet_file.sheet_symbols:
                visit(Path(os.path.normpath(path.parent / sheet.filename)))
            order[path] = sheet_file

        for root in self._roots:
            visit(Path(os.path.abspath(root)))
        for path in self._files:
            visit(path)
        return tuple(order.values())

    def _rebind(self, roots: tuple[Path, ...], files: tuple[SheetFile, ...]) -> None:
        """Adopt relocated paths after a successful project save-as."""
        self._roots = roots
        self._files = {sheet_file.path: sheet_file for sheet_file in files}


def _matches_disk(sheet_file: SheetFile) -> bool:
    """Whether the disk file is still the file that was read."""
    try:
        raw = sheet_file.path.read_bytes()
    except FileNotFoundError:
        return False
    fingerprint = sheet_file._fingerprint
    return fingerprint is None or fingerprint.matches(raw)


def _read_sheet_file(location: Path) -> SheetFile:
    """Read and parse one ``.kicad_sch`` file and fingerprint the bytes read."""
    if not location.is_file():
        raise InvalidSchematicError(f"Schematic file not found: {location}")
    if location.suffix.lower() != ".kicad_sch":
        raise InvalidSchematicError(
            f"Expected .kicad_sch file, got: {location.suffix or '<none>'}"
        )
    try:
        raw = location.read_bytes()
    except OSError as exc:
        raise InvalidSchematicError(f"Cannot read schematic: {exc}") from exc
    sheet_file = _parse_sheet_file(location, raw)
    object.__setattr__(sheet_file, "_fingerprint", Fingerprint.of(raw))
    return sheet_file


def _parse_sheet_file(location: Path, raw: bytes) -> SheetFile:
    try:
        document = parse(raw.decode("utf-8"))
    except (UnicodeError, ParseError, RecursionError) as exc:
        raise InvalidSchematicError(f"Invalid schematic syntax: {exc}") from exc
    return _sheet_file_from_document(location, document)


def _sheet_file_from_document(path: Path, document: Document) -> SheetFile:
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
    schematic = SheetFile(
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
        sheet_symbols=tuple(_sheet(n) for n in root.child_lists("sheet")),
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


def _sheet_filename(node: ListNode) -> str:
    matches = tuple(
        prop
        for prop in node.child_lists("property")
        if _atom(prop, 1).value == "Sheetfile"
    )
    if len(matches) != 1 or not _atom(matches[0], 2).value:
        raise InvalidSchematicError("sheet: expected one nonempty Sheetfile")
    return _atom(matches[0], 2).value


def _sheet(node: ListNode) -> SheetSymbol:
    x, y, _rot = _at(node)
    size_nodes = node.child_lists("size")
    if len(size_nodes) != 1:
        raise InvalidSchematicError("sheet: expected one size")
    width = _number(size_nodes[0], 1)
    height = _number(size_nodes[0], 2)
    name = ""
    filename = _sheet_filename(node)
    seen: set[str] = set()
    for prop in node.child_lists("property"):
        key = _atom(prop, 1).value
        value = _atom(prop, 2).value
        if key == "Sheetname":
            if key in seen:
                raise InvalidSchematicError(f"sheet: ambiguous {key}")
            seen.add(key)
            name = value
    return SheetSymbol(
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
