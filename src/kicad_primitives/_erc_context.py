"""Faithful native local library registrations for a temporary ERC project."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from lossless_sexpr import AtomNode, ListNode, ParseError, parse, quote

from . import tables
from ._erc_types import ErcContextError

if TYPE_CHECKING:
    from .projects import Project


def _variables(project: Project, home: Path) -> dict[str, str]:
    common = home / "kicad_common.json"
    variables: dict[str, str] = {}
    if common.exists():
        try:
            payload = json.loads(common.read_bytes())
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ErcContextError(
                f"Cannot capture KiCad path variables: {common}"
            ) from exc
        if not isinstance(payload, dict):
            raise ErcContextError("KiCad configuration must be a JSON object")
        environment = payload.get("environment", {})
        if not isinstance(environment, dict):
            raise ErcContextError("Invalid KiCad environment configuration")
        raw = environment.get("vars", {})
        if not isinstance(raw, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in raw.items()
        ):
            raise ErcContextError("Invalid KiCad path-variable map")
        variables.update(raw)
    # Do not let LibraryTables' directory discovery choose a different .pro.
    variables.update(project.text_variables)
    variables["KIPRJMOD"] = str(project.directory)
    variables.setdefault("KICAD_CONFIG_HOME", str(home))
    major = tables._config_major_version(home)
    tables._apply_kicad_directory_aliases(variables, major_version=major)
    variables.update({k: v for k, v in os.environ.items() if k.startswith("KICAD")})
    tables._apply_kicad_directory_aliases(variables, major_version=major)
    return variables


def _field(node: ListNode, head: str) -> AtomNode:
    children = node.child_lists(head)
    if len(children) != 1:
        raise ErcContextError(f"Library row requires one {head}")
    atom = children[0].atom(1)
    if atom is None or len(children[0].children()) != 2:
        raise ErcContextError(f"Invalid library row {head}")
    return atom


def _path(uri: str, variables: dict[str, str], project: Project) -> Path:
    expanded = tables._expand_library_uri(uri, variables)
    if not expanded.strip() or "${" in expanded or "$(" in expanded:
        raise ErcContextError("Unresolved or empty library URI in original context")
    if "://" in expanded:
        raise ErcContextError("ERC context supports local filesystem library URIs only")
    return tables._resolve_entry_path(
        uri=expanded, base_directory=project.directory, path_variables={}
    )


def _snapshot_kind(
    project: Project,
    home: Path,
    variables: dict[str, str],
    table_name: str,
    root_name: str,
    suffix: str,
) -> bytes:
    winners: dict[str, str] = {}

    def expand(table: Path, active: set[Path]) -> None:
        table = table.resolve()
        if table in active:
            raise ErcContextError(f"Cyclic nested library table: {table}")
        if not table.is_file():
            raise ErcContextError(f"Missing nested library table: {table}")
        try:
            source = table.read_bytes().decode("utf-8")
            document = parse(source)
        except (OSError, UnicodeError, ParseError, RecursionError) as exc:
            raise ErcContextError(f"Cannot capture library table: {table}") from exc
        roots = document.roots()
        if (
            len(roots) != 1
            or not isinstance(roots[0], ListNode)
            or roots[0].head != root_name
        ):
            raise ErcContextError(f"Expected one native {root_name}: {table}")
        active.add(table)
        if len(roots[0].child_lists("version")) > 1:
            raise ErcContextError("Ambiguous library-table format")
        for node in roots[0].children()[1:]:
            if not isinstance(node, ListNode):
                raise ErcContextError("Invalid library-table row")
            if node.head == "version":
                value = node.atom(1)
                if value is None or value.value != "7" or len(node.children()) != 2:
                    raise ErcContextError("Unsupported library-table format")
                continue
            if node.head != "lib":
                raise ErcContextError("Unsupported library-table context metadata")
            name, kind, uri = (
                _field(node, "name"),
                _field(node, "type"),
                _field(node, "uri"),
            )
            for scalar in ("options", "descr"):
                if node.child_lists(scalar):
                    _field(node, scalar)
            if not name.value.strip() or name.value != name.value.strip():
                raise ErcContextError("Empty or indeterminate library nickname")
            location = _path(uri.value, variables, project)
            if kind.value == "Table":
                if any(
                    not isinstance(c, ListNode)
                    or c.head not in {"name", "type", "uri", "options", "descr"}
                    for c in node.children()[1:]
                ) or any(
                    _field(node, "options").value for _ in node.child_lists("options")
                ):
                    raise ErcContextError("Nested table modifiers are unsupported")
                expand(location, active)
            elif kind.value == "KiCad" and location.suffix.lower() == suffix:
                raw = source[node.span.start : node.span.end]
                start, end = (
                    uri.span.start - node.span.start,
                    uri.span.end - node.span.start,
                )
                # Preserve ALL other leaf metadata, even flags unknown to LibraryEntry.
                winners[name.value] = raw[:start] + quote(str(location)) + raw[end:]
            else:
                raise ErcContextError(
                    "ERC context supports native local KiCad libraries only"
                )
        active.remove(table)

    for primary in (home / table_name, project.directory / table_name):
        if primary.exists() or primary.is_symlink():
            expand(primary, set())
    raw = (
        f"({root_name}\n  (version 7)\n"
        + "".join("  " + row + "\n" for row in winners.values())
        + ")\n"
    )
    return raw.encode("utf-8")


def library_table_snapshot(project: Project) -> tuple[Path, bytes, bytes]:
    """Flatten native effective leaves while preserving raw metadata and context."""
    home = tables._detect_config_home(None)
    variables = _variables(project, home)
    return (
        home,
        _snapshot_kind(
            project, home, variables, "sym-lib-table", "sym_lib_table", ".kicad_sym"
        ),
        _snapshot_kind(
            project, home, variables, "fp-lib-table", "fp_lib_table", ".pretty"
        ),
    )
