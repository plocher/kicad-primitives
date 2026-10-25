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
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from lossless_sexpr import SourceSpan, TextEdit, apply_edits, parse, quote

__all__ = [
    "AmbiguousLibraryError",
    "InvalidLibraryTableError",
    "LibraryEntry",
    "LibraryMutationResult",
    "LibraryScope",
    "LibraryTables",
    "LibraryTablesError",
    "LibraryType",
    "MissingLibraryError",
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


@dataclass(frozen=True)
class LibraryMutationResult:
    """Outcome of an add, remove, or rename on one scope table file."""

    operation: str
    library_type: LibraryType
    scope: LibraryScope
    table_path: Path
    nickname: str
    applied: bool
    details: str


class LibraryTables:
    """Global and optional project library-table context for one config home."""

    def __init__(
        self,
        *,
        config_home: Path,
        project_directory: Path | None,
        path_variables: Mapping[str, str],
    ) -> None:
        self._config_home = config_home
        self._project_directory = project_directory
        self._path_variables = path_variables

    @classmethod
    def open(
        cls,
        *,
        config_home: str | PathLike[str] | None = None,
        project_directory: str | PathLike[str] | None = None,
    ) -> LibraryTables:
        """Open tables for an optional project against a KiCad config home.

        *config_home* may be explicit. Otherwise ``KICAD_CONFIG_HOME`` wins,
        then the first platform candidate that already holds a table file,
        then the preferred versioned default path even when empty.

        *project_directory* adds project-scope tables, ``KIPRJMOD``, and
        ``.kicad_pro`` ``text_variables`` overrides. Library resolution works
        without a project.
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
        return cls(
            config_home=home,
            project_directory=project,
            path_variables=variables,
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

    def add_library(
        self,
        *,
        library_type: LibraryType,
        scope: LibraryScope,
        nickname: str,
        uri: str,
        entry_type: str = "KiCad",
        options: str = "",
        descr: str = "",
        apply: bool = False,
    ) -> LibraryMutationResult:
        """Append a leaf library row to the primary table for *scope*.

        Creates a minimal table file when missing. Refuses duplicate nicknames
        already declared as direct rows in that file (nested tables are not
        scanned for collisions). Set *apply* to write; otherwise plan only.
        """
        _require_library_type(library_type)
        _require_scope(scope)
        name = nickname.strip()
        if not name:
            raise ValueError("Nickname cannot be empty")
        uri_text = uri.strip()
        if not uri_text:
            raise ValueError("URI cannot be empty")
        table_path = self.table_path(library_type, scope)
        records = _load_direct_records(table_path, library_type=library_type)
        if any(record["name"] == name for record in records):
            raise ValueError(f"Library nickname already exists: {name}")
        records.append(
            {
                "name": name,
                "type": entry_type.strip() or "KiCad",
                "uri": uri_text,
                "options": options,
                "descr": descr,
            }
        )
        if apply:
            previous = _read_table_source_if_present(table_path)
            if previous is None:
                _write_new_table_file(
                    table_path=table_path,
                    library_type=library_type,
                    records=records,
                )
            else:
                _append_lib_record(
                    table_path=table_path,
                    library_type=library_type,
                    record=records[-1],
                    source=previous,
                )
        return LibraryMutationResult(
            operation="add",
            library_type=library_type,
            scope=scope,
            table_path=table_path,
            nickname=name,
            applied=apply,
            details="added" if apply else "planned",
        )

    def remove_library(
        self,
        *,
        library_type: LibraryType,
        scope: LibraryScope,
        nickname: str,
        apply: bool = False,
    ) -> LibraryMutationResult:
        """Remove one direct nickname row from the primary *scope* table file."""
        _require_library_type(library_type)
        _require_scope(scope)
        name = nickname.strip()
        if not name:
            raise ValueError("Nickname cannot be empty")
        table_path = self.table_path(library_type, scope)
        if not table_path.is_file():
            raise MissingLibraryError(name)
        records = _load_direct_records(table_path, library_type=library_type)
        updated = [record for record in records if record["name"] != name]
        if len(updated) == len(records):
            raise MissingLibraryError(name)
        if apply:
            previous = table_path.read_text(encoding="utf-8")
            _delete_direct_nickname(
                table_path=table_path,
                library_type=library_type,
                nickname=name,
                source=previous,
            )
        return LibraryMutationResult(
            operation="remove",
            library_type=library_type,
            scope=scope,
            table_path=table_path,
            nickname=name,
            applied=apply,
            details="removed" if apply else "planned",
        )

    def rename_library(
        self,
        *,
        library_type: LibraryType,
        scope: LibraryScope,
        old_nickname: str,
        new_nickname: str,
        apply: bool = False,
    ) -> LibraryMutationResult:
        """Rename one direct nickname in the primary *scope* table file."""
        _require_library_type(library_type)
        _require_scope(scope)
        old_name = old_nickname.strip()
        new_name = new_nickname.strip()
        if not old_name or not new_name:
            raise ValueError("Nickname cannot be empty")
        table_path = self.table_path(library_type, scope)
        if not table_path.is_file():
            raise MissingLibraryError(old_name)
        previous = table_path.read_text(encoding="utf-8")
        if apply:
            _rename_direct_nickname(
                table_path=table_path,
                library_type=library_type,
                old_name=old_name,
                new_name=new_name,
                source=previous,
            )
        else:
            records = _load_direct_records(table_path, library_type=library_type)
            if any(record["name"] == new_name for record in records):
                raise ValueError(f"Target nickname already exists: {new_name}")
            if not any(record["name"] == old_name for record in records):
                raise MissingLibraryError(old_name)
        return LibraryMutationResult(
            operation="rename",
            library_type=library_type,
            scope=scope,
            table_path=table_path,
            nickname=new_name,
            applied=apply,
            details=(
                f"{old_name} -> {new_name}"
                if apply
                else f"planned {old_name} -> {new_name}"
            ),
        )

    def _collect_leaf_entries(self, library_type: LibraryType) -> list[LibraryEntry]:
        entries: list[LibraryEntry] = []
        global_table = self.table_path(library_type, "global")
        if global_table.is_file():
            entries.extend(
                _expand_table_file(
                    table_path=global_table,
                    library_type=library_type,
                    scope="global",
                    project_directory=self._project_directory,
                    path_variables=self._path_variables,
                    visited=set(),
                )
            )
        if self._project_directory is not None:
            project_table = self.table_path(library_type, "project")
            if project_table.is_file():
                entries.extend(
                    _expand_table_file(
                        table_path=project_table,
                        library_type=library_type,
                        scope="project",
                        project_directory=self._project_directory,
                        path_variables=self._path_variables,
                        visited=set(),
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
        return (config_home / name).resolve()
    if project_directory is None:
        raise ValueError("Project directory is required for project-scope tables")
    return (project_directory / name).resolve()


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


def _resolve_entry_path(
    *,
    uri: str,
    project_directory: Path | None,
    path_variables: Mapping[str, str],
    table_path: Path,
) -> Path:
    expanded = uri
    for _ in range(8):
        replaced = _URI_VARIABLE_PATTERN.sub(
            lambda match: path_variables.get(match.group(1), match.group(0)),
            expanded,
        )
        if replaced == expanded:
            break
        expanded = replaced
    expanded_path = Path(expanded).expanduser()
    if expanded_path.is_absolute():
        return expanded_path
    # Nested and relative URIs resolve against the table file directory first
    # (kDoctor nested tables). Plain project-relative paths still work when the
    # table lives in the project directory.
    base = table_path.parent
    if project_directory is not None and base == project_directory:
        return (project_directory / expanded_path).resolve()
    return (base / expanded_path).resolve()


def _expand_table_file(
    *,
    table_path: Path,
    library_type: LibraryType,
    scope: LibraryScope,
    project_directory: Path | None,
    path_variables: Mapping[str, str],
    visited: set[Path],
) -> list[LibraryEntry]:
    resolved_table = table_path.resolve()
    if resolved_table in visited:
        return []
    visited.add(resolved_table)
    records = _load_direct_records(resolved_table, library_type=library_type)
    entries: list[LibraryEntry] = []
    for record in records:
        nickname = record.get("name", "").strip()
        uri = record.get("uri", "")
        entry_type = record.get("type", "")
        if not nickname or not uri:
            continue
        resolved_path = _resolve_entry_path(
            uri=uri,
            project_directory=project_directory,
            path_variables=path_variables,
            table_path=resolved_table,
        )
        if entry_type == _NESTED_ENTRY_TYPE:
            if resolved_path.is_file():
                entries.extend(
                    _expand_table_file(
                        table_path=resolved_path,
                        library_type=library_type,
                        scope=scope,
                        project_directory=project_directory,
                        path_variables=path_variables,
                        visited=visited,
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


def _read_table_source_if_present(table_path: Path) -> str | None:
    if table_path.is_file():
        return table_path.read_text(encoding="utf-8")
    return None


def _load_direct_records(
    table_path: Path, *, library_type: LibraryType
) -> list[dict[str, str]]:
    if not table_path.is_file():
        return []
    try:
        text = table_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidLibraryTableError(
            f"Cannot read library table {table_path}: {exc}"
        ) from exc
    return _records_from_source(text, table_path=table_path, library_type=library_type)


def _records_from_source(
    text: str, *, table_path: Path, library_type: LibraryType
) -> list[dict[str, str]]:
    try:
        document = parse(text)
    except Exception as exc:
        raise InvalidLibraryTableError(
            f"Failed to parse KiCad table {table_path}: {exc}"
        ) from exc
    root_name = _TABLE_ROOT_NAMES[library_type]
    roots: Any = document.lists(head=root_name)
    if not roots:
        # Accept either root name when reading an existing file.
        other = "fp_lib_table" if root_name == "sym_lib_table" else "sym_lib_table"
        roots = document.lists(head=other)
    if not roots:
        raise InvalidLibraryTableError(f"Library table root not found in {table_path}")
    records: list[dict[str, str]] = []
    root = roots[0]
    for lib_node in root.child_lists():
        if lib_node.head != "lib":
            continue
        record: dict[str, str] = {}
        for field in lib_node.child_lists():
            atoms = list(field.children())
            if len(atoms) < 2:
                continue
            key = str(atoms[0].value)
            record[key] = str(atoms[1].value)
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
    if prefix:
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


def _write_new_table_file(
    *,
    table_path: Path,
    library_type: LibraryType,
    records: list[dict[str, str]],
) -> None:
    root_name = _TABLE_ROOT_NAMES[library_type]
    indent = "\t"
    lines = [f"({root_name}", f"{indent}(version 7)"]
    for record in records:
        lines.append(_format_lib_line(indent, record))
    lines.append(")")
    _atomic_write_text(table_path, "\n".join(lines) + "\n")


def _table_root_lists(
    source: str, *, library_type: LibraryType, table_path: Path
) -> Any:
    root_name = _TABLE_ROOT_NAMES[library_type]
    document = parse(source)
    roots = document.lists(head=root_name)
    if not roots:
        other = "fp_lib_table" if root_name == "sym_lib_table" else "sym_lib_table"
        roots = document.lists(head=other)
    if not roots:
        raise InvalidLibraryTableError(f"Library table root not found in {table_path}")
    return roots


def _append_lib_record(
    *,
    table_path: Path,
    library_type: LibraryType,
    record: Mapping[str, str],
    source: str,
) -> None:
    roots = _table_root_lists(source, library_type=library_type, table_path=table_path)
    root = roots[0]
    lib_nodes = [node for node in root.child_lists() if node.head == "lib"]
    indent = _detect_indent(source, [node.span for node in lib_nodes])
    insert_at = root.span.end - 1
    line = _format_lib_line(indent, record)
    if source[:insert_at].endswith("\n"):
        body = f"{line}\n"
    else:
        body = f"\n{line}\n"
    edited = apply_edits(source, [TextEdit(SourceSpan(insert_at, insert_at), body)])
    _atomic_write_text(table_path, edited)


def _delete_direct_nickname(
    *,
    table_path: Path,
    library_type: LibraryType,
    nickname: str,
    source: str,
) -> None:
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
        atoms = list(name_field.children())
        if len(atoms) < 2:
            continue
        if str(atoms[1].value) != nickname:
            continue
        target_start = _leading_separator_start(source, lib_node.span.start)
        target_end = lib_node.span.end
        break
    if target_start is None or target_end is None:
        raise MissingLibraryError(nickname)
    edited = apply_edits(source, [TextEdit(SourceSpan(target_start, target_end), "")])
    _atomic_write_text(table_path, edited)


def _rename_direct_nickname(
    *,
    table_path: Path,
    library_type: LibraryType,
    old_name: str,
    new_name: str,
    source: str,
) -> None:
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
        atoms = list(name_field.children())
        if len(atoms) < 2:
            continue
        current = str(atoms[1].value)
        if current == new_name:
            seen_new = True
        if current == old_name and target_span is None:
            target_span = atoms[1].span
    if seen_new and old_name != new_name:
        raise ValueError(f"Target nickname already exists: {new_name}")
    if target_span is None:
        raise MissingLibraryError(old_name)
    edited = apply_edits(source, [TextEdit(target_span, quote(new_name))])
    _atomic_write_text(table_path, edited)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
