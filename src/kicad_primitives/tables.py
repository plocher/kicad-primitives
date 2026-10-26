"""Discover, resolve, and edit KiCad symbol and footprint library tables.

Library definition content lives under symbols and footprint services. This
module owns registrations only: global and project ``sym-lib-table`` /
``fp-lib-table`` files, ``${VAR}`` expansion, nested ``Table`` entries, and
localized add/remove/rename of leaf nicknames.
"""

from __future__ import annotations

import json
import os
import platform
import re
from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from lossless_sexpr import ListNode, SourceSpan, TextEdit, apply_edits, parse, quote

from . import _symbol_persist

__all__ = [
    "AmbiguousLibraryError",
    "InvalidLibraryTableError",
    "LibraryEntry",
    "LibraryScope",
    "LibraryTable",
    "LibraryTableConflictError",
    "LibraryTableLifecycleError",
    "LibraryTables",
    "LibraryTablesError",
    "LibraryType",
    "MissingLibraryError",
    "TableEntry",
]

LibraryType = Literal["symbol", "footprint"]
LibraryScope = Literal["global", "project"]

_URI_VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)\}")
_TABLE_FILE_NAMES: dict[LibraryType, str] = {
    "symbol": "sym-lib-table",
    "footprint": "fp-lib-table",
}
_TABLE_ROOT_NAMES: dict[LibraryType, str] = {
    "symbol": "sym_lib_table",
    "footprint": "fp_lib_table",
}
_NESTED_ENTRY_TYPE = "Table"


class LibraryTablesError(Exception):
    """Shared base for library-table failures."""


class InvalidLibraryTableError(LibraryTablesError, ValueError):
    """A table file is missing required structure or cannot be parsed."""


class MissingLibraryError(LibraryTablesError, KeyError):
    """No leaf library matches the requested nickname."""


class AmbiguousLibraryError(LibraryTablesError, ValueError):
    """More than one leaf library matches within the same winning scope."""


@dataclass(frozen=True)
class LibraryEntry:
    """One resolved leaf library registration after nested-table expansion."""

    library_type: LibraryType
    scope: LibraryScope
    nickname: str
    uri: str
    entry_type: str
    options: str
    descr: str
    resolved_path: Path
    table_path: Path


class LibraryTableConflictError(LibraryTablesError, RuntimeError):
    """A physical table changed on disk since its successful open or save."""


class LibraryTableLifecycleError(LibraryTablesError, RuntimeError):
    """A table is closed, an entry is stale, or no current close decision exists."""


def _require_table_text(label: str, value: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if "\x00" in value:
        raise ValueError(f"{label} cannot contain NUL")
    value.encode("utf-8")
    if not allow_empty and not value.strip():
        raise ValueError(f"{label} cannot be empty")
    return value


class LibraryTable:
    """One physical table with buffered source and explicit persistence."""

    def __init__(
        self,
        context: LibraryTables,
        path: Path,
        library_type: LibraryType,
        scope: LibraryScope,
    ) -> None:
        self._context = context
        self._path = path
        self._library_type = library_type
        self._scope = scope
        self._baseline = path.read_bytes() if path.exists() else None
        raw = self._baseline
        self._source = (
            raw.decode("utf-8")
            if raw is not None
            else f"({_TABLE_ROOT_NAMES[library_type]}\n  (version 7)\n)\n"
        )
        self._initial = self._source.encode("utf-8")
        self._records = _records_from_source(
            self._source, table_path=path, library_type=library_type
        )
        self._entries = tuple(TableEntry(self, i) for i in range(len(self._records)))
        self._closed = False
        self._close_authorized = False

    def _check_open(self) -> None:
        if self._closed:
            raise LibraryTableLifecycleError(f"Table is closed: {self._path}")

    def _accept_source(self, source: str, *, removed: TableEntry | None = None) -> None:
        self._check_open()
        records = _records_from_source(
            source, table_path=self._path, library_type=self.library_type
        )
        if source == self._source:
            return
        handles = [entry for entry in self._entries if entry is not removed]
        if removed is not None:
            removed._alive = False
        while len(handles) < len(records):
            handles.append(TableEntry(self, len(handles)))
        for i, entry in enumerate(handles):
            entry._index = i
        self._source = source
        self._records = records
        self._entries = tuple(handles)
        self._close_authorized = False

    @property
    def library_type(self) -> LibraryType:
        """Symbol or footprint identity of this physical table."""
        return self._library_type

    @property
    def scope(self) -> LibraryScope:
        """Scope through which this physical table first entered its context."""
        return self._scope

    @property
    def path(self) -> Path:
        """Current physical destination, retained as diagnostic identity after close."""
        return self._path

    @property
    def is_closed(self) -> bool:
        """Whether this root has exited through close or terminal discard."""
        return self._closed

    @property
    def is_modified(self) -> bool:
        """Whether pending bytes differ from the last successful open/save baseline."""
        self._check_open()
        baseline = self._initial if self._baseline is None else self._baseline
        return self.to_bytes() != baseline

    @property
    def entries(self) -> tuple[TableEntry, ...]:
        """Live direct row occurrences, including nested links and repeated names."""
        self._check_open()
        return self._entries

    def entry(self, nickname: str) -> TableEntry:
        """Select one direct row, rejecting missing or ambiguous nicknames."""
        self._check_open()
        matches = tuple(e for e in self._entries if e.nickname == nickname)
        if not matches:
            raise MissingLibraryError(nickname)
        if len(matches) != 1:
            raise AmbiguousLibraryError(f"Ambiguous direct nickname: {nickname!r}")
        return matches[0]

    def add_entry(
        self,
        nickname: str,
        uri: str,
        *,
        entry_type: str = "KiCad",
        options: str = "",
        descr: str = "",
    ) -> TableEntry:
        """Append one new direct registration in memory, preserving existing source."""
        self._check_open()
        name = _require_table_text("Nickname", nickname).strip()
        uri = _require_table_text("URI", uri).strip()
        entry_type = _require_table_text("Entry type", entry_type).strip()
        _require_table_text("Options", options, allow_empty=True)
        _require_table_text("Description", descr, allow_empty=True)
        if any(e.nickname == name for e in self._entries):
            raise ValueError(f"Library nickname already exists: {name}")
        source = _append_lib_record(
            table_path=self._path,
            library_type=self.library_type,
            record={
                "name": name,
                "uri": uri,
                "type": entry_type,
                "options": options,
                "descr": descr,
            },
            source=self._source,
        )
        self._accept_source(source)
        return self._entries[-1]

    def to_bytes(self) -> bytes:
        """Preview full pending source, including opaque metadata and row flags."""
        self._check_open()
        return self._source.encode("utf-8")

    def save(self) -> None:
        """Persist this file only; authorize close only after successful persistence."""
        self._check_open()
        self._close_authorized = False
        output = self.to_bytes()
        if self._baseline is None:
            _symbol_persist.save_new_source(
                self._path, output, unsupported_error=InvalidLibraryTableError
            )
        else:
            _symbol_persist.save_source(
                self._path,
                self._baseline,
                output,
                conflict_error=LibraryTableConflictError,
                unsupported_error=InvalidLibraryTableError,
                label="Library table",
            )
        self._baseline = output
        self._close_authorized = True

    def save_as(self, path: str | PathLike[str]) -> None:
        """Save one new file and rebind only on success; never overwrite a destination."""
        self._check_open()
        self._close_authorized = False
        destination = Path(path).expanduser().absolute()
        self._context._check_rebind(self, destination)
        mode = 0o600
        if self._baseline is not None:
            info = _symbol_persist._check_read_baseline(
                self._path,
                self._baseline,
                conflict_error=LibraryTableConflictError,
                label="Library table",
            )
            mode = info.st_mode & 0o7777
        output = self.to_bytes()
        _symbol_persist.save_new_source(
            destination,
            output,
            mode=mode,
            unsupported_error=InvalidLibraryTableError,
        )
        self._context._rebind(self, destination)
        self._baseline = output
        self._close_authorized = True

    def discard(self) -> None:
        """Abandon this artifact and invalidate its entries without writing."""
        if self._closed:
            return
        self._closed = True
        for entry in self._entries:
            entry._alive = False

    def close(self) -> None:
        """Exit without writing, requiring a successful current save or terminal discard."""
        if self._closed:
            return
        if not self._close_authorized:
            raise LibraryTableLifecycleError("Save, save as, or discard before close")
        self.discard()


class TableEntry:
    """One live direct registration owned by a physical LibraryTable."""

    def __init__(self, table: LibraryTable, index: int) -> None:
        self._table = table
        self._index = index
        self._alive = True

    def _record(self) -> dict[str, str]:
        self._table._check_open()
        if not self._alive:
            raise LibraryTableLifecycleError("Library table entry has been deleted")
        return self._table._records[self._index]

    def _check_target(self) -> None:
        self._table.entry(self.nickname)
        node = _table_root_lists(
            self._table._source,
            library_type=self._table.library_type,
            table_path=self._table.path,
        )[0].child_lists("lib")[self._index]
        names = node.child_lists("name")
        if len(names) != 1 or len(names[0].children()) != 2:
            raise InvalidLibraryTableError("Expected one unambiguous nickname atom")

    @property
    def nickname(self) -> str:
        """Current raw direct nickname."""
        return self._record().get("name", "")

    @property
    def uri(self) -> str:
        """Current unexpanded URI text."""
        return self._record().get("uri", "")

    @property
    def entry_type(self) -> str:
        """Plugin type, including Table for nested registrations."""
        return self._record().get("type", "")

    @property
    def options(self) -> str:
        """Uninterpreted options text."""
        return self._record().get("options", "")

    @property
    def descr(self) -> str:
        """Current description text."""
        return self._record().get("descr", "")

    @property
    def resolved_path(self) -> Path:
        """URI resolved from the owning context's captured common base."""
        return _resolve_entry_path(
            uri=self.uri,
            base_directory=self._table._context.base_directory,
            path_variables=self._table._context.path_variables,
        )

    @property
    def included_table(self) -> LibraryTable | None:
        """Live physical nested table in this same context, or None for a leaf."""
        if self.entry_type != _NESTED_ENTRY_TYPE:
            return None
        return self._table._context._table_at(
            self.resolved_path, self._table.library_type, self._table.scope
        )

    def rename(self, nickname: str) -> None:
        """Rename this direct registration in memory, retaining row flags and metadata."""
        current = self.nickname
        self._check_target()
        name = _require_table_text("Nickname", nickname).strip()
        self._table._accept_source(
            _rename_direct_nickname(
                table_path=self._table.path,
                library_type=self._table.library_type,
                old_name=current,
                new_name=name,
                source=self._table._source,
            )
        )

    def set_uri(self, uri: str) -> None:
        """Set this row's URI in memory; an equal URI preserves exact source bytes."""
        current = self.uri
        self._check_target()
        value = _require_table_text("URI", uri)
        roots = _table_root_lists(
            self._table._source,
            library_type=self._table.library_type,
            table_path=self._table.path,
        )
        node = roots[0].child_lists("lib")[self._index]
        fields = node.child_lists("uri")
        if len(fields) != 1 or len(fields[0].children()) != 2:
            raise InvalidLibraryTableError("Expected one unambiguous URI atom")
        token = fields[0].atom(1)
        if token is None:
            raise InvalidLibraryTableError("Missing URI atom")
        if value == current:
            return
        self._table._accept_source(
            apply_edits(self._table._source, [TextEdit(token.span, quote(value))])
        )

    def delete(self) -> None:
        """Remove this direct row and invalidate its handle, without persistence."""
        nickname = self.nickname
        self._check_target()
        source = _delete_direct_nickname(
            table_path=self._table.path,
            library_type=self._table.library_type,
            nickname=nickname,
            source=self._table._source,
        )
        self._table._accept_source(source, removed=self)


class LibraryTables:
    """Global and optional project library-table context for one config home."""

    def __init__(
        self,
        *,
        config_home: Path,
        project_directory: Path | None,
        path_variables: Mapping[str, str],
        base_directory: Path,
    ) -> None:
        self._config_home = config_home
        self._project_directory = project_directory
        self._path_variables = path_variables
        self._base_directory = base_directory
        self._physical_tables: dict[tuple[Path, LibraryType], LibraryTable] = {}
        self._primary_tables: dict[tuple[LibraryType, LibraryScope], LibraryTable] = {}

    @classmethod
    def open(
        cls,
        *,
        config_home: str | PathLike[str] | None = None,
        project_directory: str | PathLike[str] | None = None,
        base_directory: str | PathLike[str] | None = None,
    ) -> LibraryTables:
        """Open tables for an optional project against a KiCad config home.

        *config_home* may be explicit. Otherwise ``KICAD_CONFIG_HOME`` wins,
        then the first platform candidate that already holds a table file,
        then the preferred versioned default path even when empty.

        *project_directory* adds project-scope tables, ``KIPRJMOD``, and
        ``.kicad_pro`` ``text_variables`` overrides. Library resolution works
        without a project.

        Relative include and leaf URIs use the project directory. Standalone
        resolution uses *base_directory*, or captures process CWD at open.
        The base is never the containing table's directory.
        """
        home = _detect_config_home(None if config_home is None else Path(config_home))
        project = (
            None
            if project_directory is None
            else Path(project_directory).expanduser().resolve()
        )
        if project is not None and not project.is_dir():
            raise InvalidLibraryTableError(
                f"Project directory does not exist: {project}"
            )
        variables = _build_path_variables(config_home=home, project_directory=project)
        if project is not None and base_directory is not None:
            raise ValueError("base_directory is only for standalone table resolution")
        base = project or (
            Path.cwd()
            if base_directory is None
            else Path(base_directory).expanduser().resolve()
        )
        if not base.is_dir():
            raise InvalidLibraryTableError(f"Base directory does not exist: {base}")
        return cls(
            config_home=home,
            project_directory=project,
            path_variables=variables,
            base_directory=base,
        )

    @property
    def config_home(self) -> Path:
        """Absolute KiCad configuration directory used for global tables."""
        return self._config_home

    @property
    def project_directory(self) -> Path | None:
        """Absolute project directory when opened with one, else ``None``."""
        return self._project_directory

    @property
    def path_variables(self) -> Mapping[str, str]:
        """Read-only effective ``${VAR}`` map used for URI expansion."""
        return MappingProxyType(dict(self._path_variables))

    @property
    def base_directory(self) -> Path:
        """Captured base for relative include and leaf URIs in this context."""
        return self._base_directory

    def table_path(self, library_type: LibraryType, scope: LibraryScope) -> Path:
        """Return the path of the primary table file for *scope* and *type*."""
        _require_library_type(library_type)
        _require_scope(scope)
        return _table_path_for_scope(
            library_type=library_type,
            scope=scope,
            project_directory=self._project_directory,
            config_home=self._config_home,
        )

    def libraries(self, library_type: LibraryType) -> tuple[LibraryEntry, ...]:
        """Leaf libraries after nested ``Table`` expansion, global then project.

        Nested ``type \"Table\"`` rows are followed, not returned as leaves.
        Duplicate nicknames may appear across scopes; use :meth:`resolve` for
        KiCad-style project-over-global selection.
        """
        _require_library_type(library_type)
        return tuple(self._collect_leaf_entries(library_type))

    def resolve(self, nickname: str, *, library_type: LibraryType) -> LibraryEntry:
        """Map a nickname to one leaf path using project-over-global precedence.

        Within the winning scope, the last expanded leaf with that nickname
        wins (nested tables and later rows can override earlier ones). Missing
        nicknames raise :class:`MissingLibraryError`.
        """
        _require_library_type(library_type)
        key = nickname.strip()
        if not key:
            raise ValueError("Nickname cannot be empty")
        by_scope: dict[LibraryScope, list[LibraryEntry]] = {
            "global": [],
            "project": [],
        }
        for entry in self._collect_leaf_entries(library_type):
            if entry.nickname == key:
                by_scope[entry.scope].append(entry)
        winners = by_scope["project"] or by_scope["global"]
        if not winners:
            raise MissingLibraryError(key)
        return winners[-1]

    def _table_at(
        self,
        path: Path,
        library_type: LibraryType,
        scope: LibraryScope,
    ) -> LibraryTable:
        for opened in self._physical_tables.values():
            if opened.path == path.absolute() and opened.library_type == library_type:
                opened._check_open()
                return opened
        key = (path.resolve(), library_type)
        if key not in self._physical_tables:
            self._physical_tables[key] = LibraryTable(self, path, library_type, scope)
        table = self._physical_tables[key]
        table._check_open()
        return table

    def table(self, library_type: LibraryType, scope: LibraryScope) -> LibraryTable:
        """Get the live physical primary table for this type and scope."""
        _require_library_type(library_type)
        _require_scope(scope)
        key = (library_type, scope)
        if key not in self._primary_tables:
            self._primary_tables[key] = self._table_at(
                self.table_path(library_type, scope), library_type, scope
            )
        table = self._primary_tables[key]
        table._check_open()
        return table

    @property
    def is_modified(self) -> bool:
        """Whether any opened physical table retains pending changes."""
        return any(
            t.is_modified for t in self._physical_tables.values() if not t.is_closed
        )

    def _check_rebind(self, table: LibraryTable, destination: Path) -> None:
        other = self._physical_tables.get((destination.resolve(), table.library_type))
        if other is not None and other is not table:
            raise ValueError("Destination already belongs to another opened table")

    def _rebind(self, table: LibraryTable, destination: Path) -> None:
        for key, opened in tuple(self._physical_tables.items()):
            if opened is table:
                del self._physical_tables[key]
        table._path = destination
        self._physical_tables[(destination.resolve(), table.library_type)] = table

    def _collect_leaf_entries(self, library_type: LibraryType) -> list[LibraryEntry]:
        entries: list[LibraryEntry] = []
        scopes: tuple[LibraryScope, ...] = (
            ("global", "project")
            if self._project_directory is not None
            else ("global",)
        )
        for scope in scopes:
            path = self.table(library_type, scope).path
            entries.extend(
                _expand_table_file(
                    table_path=path,
                    library_type=library_type,
                    scope=scope,
                    base_directory=self._base_directory,
                    path_variables=self._path_variables,
                    active=set(),
                    context=self,
                )
            )
        return entries


def _require_library_type(library_type: LibraryType) -> None:
    if library_type not in _TABLE_FILE_NAMES:
        raise ValueError(f"Unsupported library_type: {library_type!r}")


def _require_scope(scope: LibraryScope) -> None:
    if scope not in ("global", "project"):
        raise ValueError(f"Unsupported scope: {scope!r}")


def _table_path_for_scope(
    *,
    library_type: LibraryType,
    scope: LibraryScope,
    project_directory: Path | None,
    config_home: Path,
) -> Path:
    name = _TABLE_FILE_NAMES[library_type]
    if scope == "global":
        return (config_home / name).absolute()
    if project_directory is None:
        raise ValueError("Project directory is required for project-scope tables")
    return (project_directory / name).absolute()


def _detect_config_home(config_home: Path | None) -> Path:
    if config_home is not None:
        return config_home.expanduser().resolve()

    env_home = os.environ.get("KICAD_CONFIG_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    for candidate in _config_home_candidates():
        if (candidate / "sym-lib-table").is_file() or (
            candidate / "fp-lib-table"
        ).is_file():
            return candidate.resolve()
    return _config_home_candidates()[0].resolve()


def _config_home_candidates() -> list[Path]:
    home = Path.home()
    system = platform.system()
    versioned = ("10.0", "9.0", "8.0")
    candidates: list[Path] = []
    if system == "Darwin":
        base = home / "Library" / "Preferences" / "kicad"
        candidates.extend(base / version for version in versioned)
        candidates.append(base)
    elif system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = Path(appdata) / "kicad"
            candidates.extend(base / version for version in versioned)
            candidates.append(base)
    else:
        base = home / ".config" / "kicad"
        candidates.extend(base / version for version in versioned)
        candidates.append(base)
    return candidates


def _build_path_variables(
    *,
    config_home: Path,
    project_directory: Path | None,
) -> dict[str, str]:
    """Merge KiCad path variables with documented override order.

    Order (later wins on the same key):
    1. ``kicad_common.json`` ``environment.vars``
    2. project ``text_variables``
    3. synthetic ``KIPRJMOD`` / ``KICAD_CONFIG_HOME``
    4. versioned directory aliases derived from model-dir roots
    5. process environment keys starting with ``KICAD`` plus ``KIPRJMOD``
    6. aliases again so env-provided roots still fill companion dirs
    """
    variables: dict[str, str] = {}
    variables.update(_load_global_path_variables(config_home=config_home))
    variables.update(_load_project_path_overrides(project_directory=project_directory))
    if project_directory is not None:
        variables["KIPRJMOD"] = str(project_directory)
    else:
        variables.setdefault("KIPRJMOD", "")
    variables.setdefault("KICAD_CONFIG_HOME", str(config_home))
    major_version = _config_major_version(config_home)
    _apply_kicad_directory_aliases(variables, major_version=major_version)
    for key, value in os.environ.items():
        if key.startswith("KICAD") or key == "KIPRJMOD":
            variables[key] = value
    _apply_kicad_directory_aliases(variables, major_version=major_version)
    return variables


def _load_global_path_variables(*, config_home: Path) -> dict[str, str]:
    common_json_path = config_home / "kicad_common.json"
    if not common_json_path.is_file():
        return {}
    try:
        data = json.loads(common_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    environment_block = data.get("environment", {})
    if not isinstance(environment_block, dict):
        return {}
    vars_block = environment_block.get("vars", {})
    if not isinstance(vars_block, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in vars_block.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _load_project_path_overrides(*, project_directory: Path | None) -> dict[str, str]:
    project_file_path = _project_file_path(project_directory)
    if project_file_path is None:
        return {}
    try:
        data = json.loads(project_file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    text_variables = data.get("text_variables", {})
    if not isinstance(text_variables, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in text_variables.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _project_file_path(project_directory: Path | None) -> Path | None:
    if project_directory is None:
        return None
    preferred = project_directory / f"{project_directory.name}.kicad_pro"
    if preferred.is_file():
        return preferred
    candidates = sorted(project_directory.glob("*.kicad_pro"))
    if len(candidates) == 1:
        return candidates[0]
    return None


def _config_major_version(config_home: Path) -> str:
    match = re.search(r"(\d+)(?:\.\d+)?$", config_home.name)
    if match is None:
        return ""
    return match.group(1)


def _apply_kicad_directory_aliases(
    variables: dict[str, str],
    *,
    major_version: str,
) -> None:
    model_roots = _kicad_share_roots_from_model_vars(variables)
    current_root = model_roots.get(major_version, "")
    if not current_root and model_roots:
        current_root = model_roots[max(model_roots)]

    if major_version and current_root:
        variables.setdefault(
            f"KICAD{major_version}_SYMBOL_DIR",
            str(Path(current_root) / "symbols"),
        )
        variables.setdefault(
            f"KICAD{major_version}_FOOTPRINT_DIR",
            str(Path(current_root) / "footprints"),
        )

    if major_version:
        versioned_symbol_key = f"KICAD{major_version}_SYMBOL_DIR"
        versioned_footprint_key = f"KICAD{major_version}_FOOTPRINT_DIR"
        if versioned_symbol_key in variables:
            variables.setdefault("KICAD_SYMBOL_DIR", variables[versioned_symbol_key])
        if versioned_footprint_key in variables:
            variables.setdefault(
                "KICAD_FOOTPRINT_DIR", variables[versioned_footprint_key]
            )
        if "KICAD_SYMBOL_DIR" in variables:
            variables.setdefault(versioned_symbol_key, variables["KICAD_SYMBOL_DIR"])
        if "KICAD_FOOTPRINT_DIR" in variables:
            variables.setdefault(
                versioned_footprint_key, variables["KICAD_FOOTPRINT_DIR"]
            )


def _kicad_share_roots_from_model_vars(variables: Mapping[str, str]) -> dict[str, str]:
    roots: dict[str, str] = {}
    for key, raw_value in variables.items():
        match = re.fullmatch(r"KICAD(\d+)_MODEL_DIR", key)
        if match is None:
            continue
        model_dir = Path(raw_value).expanduser()
        folder_name = model_dir.name.casefold().rstrip("/")
        if folder_name != "3dmodels":
            continue
        roots[match.group(1)] = str(model_dir.parent)
    return roots


def _expand_library_uri(uri: str, path_variables: Mapping[str, str]) -> str:
    expanded = uri
    for _ in range(32):
        replaced = _URI_VARIABLE_PATTERN.sub(
            lambda match: path_variables.get(match.group(1), match.group(0)),
            expanded,
        )
        if replaced == expanded:
            break
        expanded = replaced
    return expanded


def _resolve_entry_path(
    *, uri: str, base_directory: Path, path_variables: Mapping[str, str]
) -> Path:
    location = Path(_expand_library_uri(uri, path_variables)).expanduser()
    if not location.is_absolute():
        location = base_directory / location
    return location.resolve()


def _expand_table_file(
    *,
    table_path: Path,
    library_type: LibraryType,
    scope: LibraryScope,
    base_directory: Path,
    path_variables: Mapping[str, str],
    active: set[Path],
    context: LibraryTables,
) -> list[LibraryEntry]:
    resolved_table = table_path.resolve()
    if resolved_table in active:
        return []
    # Only current ancestry counts as a cycle; completed includes replay later.
    active = active | {resolved_table}
    physical = context._table_at(table_path, library_type, scope)
    records = physical._records
    entries: list[LibraryEntry] = []
    for record in records:
        nickname = record.get("name", "").strip()
        uri = record.get("uri", "")
        entry_type = record.get("type", "")
        if not nickname or not uri:
            continue
        resolved_path = _resolve_entry_path(
            uri=uri,
            base_directory=base_directory,
            path_variables=path_variables,
        )
        if entry_type == _NESTED_ENTRY_TYPE:
            if (
                resolved_path.is_file()
                or (resolved_path.resolve(), library_type) in context._physical_tables
            ):
                entries.extend(
                    _expand_table_file(
                        table_path=resolved_path,
                        library_type=library_type,
                        scope=scope,
                        base_directory=base_directory,
                        path_variables=path_variables,
                        active=active,
                        context=context,
                    )
                )
            continue
        entries.append(
            LibraryEntry(
                library_type=library_type,
                scope=scope,
                nickname=nickname,
                uri=uri,
                entry_type=entry_type or "KiCad",
                options=record.get("options", ""),
                descr=record.get("descr", ""),
                resolved_path=resolved_path,
                table_path=resolved_table,
            )
        )
    return entries


def _records_from_source(
    text: str, *, table_path: Path, library_type: LibraryType
) -> list[dict[str, str]]:
    roots = _table_root_lists(text, table_path=table_path, library_type=library_type)
    records: list[dict[str, str]] = []
    root = roots[0]
    for lib_node in root.child_lists():
        if lib_node.head != "lib":
            continue
        record: dict[str, str] = {}
        for field in lib_node.child_lists():
            value = field.atom(1)
            if value is None or field.head is None:
                continue
            record[field.head] = value.value
        records.append(record)
    return records


def _leading_separator_start(source: str, node_start: int) -> int:
    index = node_start
    while index > 0 and source[index - 1] in " \t":
        index -= 1
    if index > 0 and source[index - 1] == "\n":
        index -= 1
        if index > 0 and source[index - 1] == "\r":
            index -= 1
    return index


def _detect_indent(source: str, lib_spans: list[SourceSpan]) -> str:
    if not lib_spans:
        if "\t" in source:
            return "\t"
        return "  "
    span = lib_spans[0]
    line_start = source.rfind("\n", 0, span.start) + 1
    prefix = source[line_start : span.start]
    if prefix and not prefix.strip():
        return prefix
    return "\t" if "\t" in source else "  "


def _format_lib_line(indent: str, record: Mapping[str, str]) -> str:
    name = quote(record.get("name", ""))
    lib_kind = quote(record.get("type", "KiCad"))
    uri = quote(record.get("uri", ""))
    options = quote(record.get("options", ""))
    descr = quote(record.get("descr", ""))
    return (
        f"{indent}(lib (name {name}) (type {lib_kind}) "
        f"(uri {uri}) (options {options}) (descr {descr}))"
    )


def _table_root_lists(
    source: str, *, library_type: LibraryType, table_path: Path
) -> tuple[ListNode, ...]:
    _require_library_type(library_type)
    try:
        document = parse(source)
    except Exception as exc:
        raise InvalidLibraryTableError(
            f"Failed to parse KiCad table {table_path}: {exc}"
        ) from exc
    roots = document.roots()
    if (
        len(roots) != 1
        or not isinstance(roots[0], ListNode)
        or roots[0].head not in _TABLE_ROOT_NAMES.values()
    ):
        raise InvalidLibraryTableError(f"Expected one library table root: {table_path}")
    return (roots[0],)


def _append_lib_record(
    *,
    table_path: Path,
    library_type: LibraryType,
    record: Mapping[str, str],
    source: str,
) -> str:
    roots = _table_root_lists(source, library_type=library_type, table_path=table_path)
    root = roots[0]
    lib_nodes = [node for node in root.child_lists() if node.head == "lib"]
    indent = _detect_indent(source, [node.span for node in lib_nodes])
    head = root.atom(0)
    assert head is not None
    insert_at = (
        lib_nodes[-1].span.end
        if lib_nodes
        else list(root.child_lists())[-1].span.end
        if root.child_lists()
        else head.span.end
    )
    multiline = "\n" in source[root.span.start : root.span.end]
    separator = ("\r\n" if "\r\n" in source else "\n") if multiline else " "
    line = _format_lib_line(indent if multiline else "", record)
    return apply_edits(
        source, [TextEdit(SourceSpan(insert_at, insert_at), separator + line)]
    )


def _delete_direct_nickname(
    *,
    table_path: Path,
    library_type: LibraryType,
    nickname: str,
    source: str,
) -> str:
    roots = _table_root_lists(source, library_type=library_type, table_path=table_path)
    target_start: int | None = None
    target_end: int | None = None
    for lib_node in roots[0].child_lists():
        if lib_node.head != "lib":
            continue
        fields = {field.head: field for field in lib_node.child_lists()}
        name_field = fields.get("name")
        if name_field is None:
            continue
        token = name_field.atom(1)
        if token is None:
            continue
        if token.value != nickname:
            continue
        target_start = _leading_separator_start(source, lib_node.span.start)
        target_end = lib_node.span.end
        break
    if target_start is None or target_end is None:
        raise MissingLibraryError(nickname)
    edited = apply_edits(source, [TextEdit(SourceSpan(target_start, target_end), "")])
    return edited


def _rename_direct_nickname(
    *,
    table_path: Path,
    library_type: LibraryType,
    old_name: str,
    new_name: str,
    source: str,
) -> str:
    roots = _table_root_lists(source, library_type=library_type, table_path=table_path)
    target_span: SourceSpan | None = None
    seen_new = False
    for lib_node in roots[0].child_lists():
        if lib_node.head != "lib":
            continue
        fields = {field.head: field for field in lib_node.child_lists()}
        name_field = fields.get("name")
        if name_field is None:
            continue
        token = name_field.atom(1)
        if token is None:
            continue
        current = token.value
        if current == new_name:
            seen_new = True
        if current == old_name and target_span is None:
            target_span = token.span
    if seen_new and old_name != new_name:
        raise ValueError(f"Target nickname already exists: {new_name}")
    if target_span is None:
        raise MissingLibraryError(old_name)
    if old_name == new_name:
        return source
    edited = apply_edits(source, [TextEdit(target_span, quote(new_name))])
    return edited
