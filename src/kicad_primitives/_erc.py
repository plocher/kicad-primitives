"""Pending-project ERC acquisition, schema intake, and original UUID provenance."""

from __future__ import annotations

import hashlib
import json
import subprocess
from math import isfinite
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast

from lossless_sexpr import ListNode, parse

from ._erc_context import library_table_snapshot
from ._erc_types import (
    ErcAcquisitionError,
    ErcDocumentSnapshot,
    ErcIgnoredCheck,
    ErcItem,
    ErcPosition,
    ErcReport,
    ErcSheet,
    ErcSnapshot,
    ErcViolation,
)
from ._kicad_cli import resolve_kicad_cli
from ._pending_snapshot import capture_pending, staged_hierarchy

if TYPE_CHECKING:
    from .projects import Project
    from .schematics import Schematic


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ErcAcquisitionError("Expected an ERC JSON object")
    return cast(dict[str, object], value)


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ErcAcquisitionError(f"Ambiguous ERC JSON key: {key}")
        result[key] = value
    return result


def _json_constant(value: str) -> NoReturn:
    raise ErcAcquisitionError(f"Invalid ERC JSON constant: {value}")


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ErcAcquisitionError("Expected an ERC JSON array")
    return cast(list[object], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ErcAcquisitionError("Expected an ERC JSON string")
    return value


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ErcAcquisitionError("Expected finite numeric ERC coordinates")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ErcAcquisitionError(
            "ERC coordinate is outside finite numeric range"
        ) from exc
    if not isfinite(number):
        raise ErcAcquisitionError("Expected finite numeric ERC coordinates")
    return number


def _item(value: object) -> ErcItem:
    item = _object(value)
    position = _object(item.get("pos"))
    return ErcItem(
        _string(item.get("uuid")),
        _string(item.get("description")),
        ErcPosition(_number(position.get("x")), _number(position.get("y"))),
    )


def _violation(value: object) -> ErcViolation:
    violation = _object(value)
    excluded: bool | None = None
    if "excluded" in violation:
        raw_excluded = violation["excluded"]
        if not isinstance(raw_excluded, bool):
            raise ErcAcquisitionError("ERC excluded must be a boolean")
        excluded = raw_excluded
    return ErcViolation(
        _string(violation.get("type")),
        _string(violation.get("description")),
        _string(violation.get("severity")),
        tuple(_item(item) for item in _array(violation.get("items"))),
        excluded,
        _string(violation["exclusion_comment"])
        if "exclusion_comment" in violation
        else None,
        _string(violation["comment"]) if "comment" in violation else None,
    )


def _uuid_key(value: str) -> str:
    return "/" + value.strip("/").lower()


def _sheet_origins(
    root: Path, documents: tuple[Schematic, ...], content: dict[Path, bytes]
) -> dict[str, Path | None]:
    by_path = {document.path: document for document in documents}
    origins: dict[str, Path | None] = {}
    root_node = parse(content[root].decode("utf-8")).roots()[0]
    assert isinstance(root_node, ListNode)
    uuids = root_node.child_lists("uuid")
    if len(uuids) != 1 or uuids[0].atom(1) is None:
        return origins
    root_uuid = uuids[0].atom(1)
    assert root_uuid is not None

    def visit(path: Path, chain: str) -> None:
        key = _uuid_key(chain)
        origins[key] = path if key not in origins else None
        for sheet in by_path[path].sheets:
            if sheet.uuid:
                visit(
                    (path.parent / sheet.filename).resolve(), chain + "/" + sheet.uuid
                )

    visit(root, "/" + root_uuid.value)
    return origins


def _report(
    payload: object,
    root: Path,
    origins: dict[str, Path | None],
    snapshot: ErcSnapshot,
    stdout: str,
    stderr: str,
) -> ErcReport:
    report = _object(payload)
    schema = _string(report.get("$schema"))
    if schema != "https://schemas.kicad.org/erc.v1.json":
        raise ErcAcquisitionError("Unsupported ERC JSON schema")
    source = _string(report.get("source"))
    if source != root.name:
        raise ErcAcquisitionError("ERC report source does not match the checked root")
    units = _string(report.get("coordinate_units"))
    if units not in {"mm", "mils", "in"}:
        raise ErcAcquisitionError("Unsupported ERC coordinate units")
    included_severities = tuple(
        _string(value) for value in _array(report.get("included_severities"))
    )
    if not {"error", "warning", "exclusion"}.issubset(included_severities):
        raise ErcAcquisitionError("ERC report omits requested severity coverage")
    sheets: list[ErcSheet] = []
    for value in _array(report.get("sheets")):
        sheet = _object(value)
        uuid_path = _string(sheet.get("uuid_path"))
        sheets.append(
            ErcSheet(
                _string(sheet.get("path")),
                uuid_path,
                origins.get(_uuid_key(uuid_path)),
                tuple(_violation(item) for item in _array(sheet.get("violations"))),
            )
        )
    if not sheets:
        raise ErcAcquisitionError("ERC report omits the checked hierarchy")
    reported_paths = {_uuid_key(sheet.uuid_path) for sheet in sheets}
    if any(
        path is not None and key not in reported_paths for key, path in origins.items()
    ):
        raise ErcAcquisitionError("ERC report omits a proved hierarchy sheet")
    checks: list[ErcIgnoredCheck] = []
    for value in _array(report.get("ignored_checks")):
        check = _object(value)
        checks.append(
            ErcIgnoredCheck(
                _string(check.get("key")), _string(check.get("description"))
            )
        )
    return ErcReport(
        root,
        source,
        schema,
        _string(report.get("date")),
        _string(report.get("kicad_version")),
        units,
        included_severities,
        tuple(checks),
        tuple(sheets),
        snapshot,
        stdout,
        stderr,
    )


def acquire_erc(
    project: Project, *, kicad_cli: str | PathLike[str] | None
) -> ErcReport:
    pending = capture_pending(project, operation="ERC")
    root, documents, content = pending.root, pending.documents, pending.content
    origins = _sheet_origins(root, documents, dict(content))
    config_home, symbol_table, footprint_table = library_table_snapshot(project)
    snapshot = ErcSnapshot(
        pending.snapshot.project_file,
        pending.snapshot.project_sha256,
        tuple(
            ErcDocumentSnapshot(entry.path, entry.sha256, entry.is_modified)
            for entry in pending.snapshot.documents
        ),
        config_home,
        hashlib.sha256(symbol_table).hexdigest(),
        hashlib.sha256(footprint_table).hexdigest(),
    )
    cli = resolve_kicad_cli(None if kicad_cli is None else Path(kicad_cli))
    with staged_hierarchy(
        project,
        content,
        prefix="kicad-primitives-erc-",
        extra={"sym-lib-table": symbol_table, "fp-lib-table": footprint_table},
    ) as stage:
        output = stage / "erc.json"
        command = [
            str(cli),
            "sch",
            "erc",
            "--format",
            "json",
            "--units",
            "mm",
            "--severity-all",
            "--output",
            str(output),
            str(stage / root.name),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=project.directory,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ErcAcquisitionError(f"ERC execution failed: {exc}") from exc
        if result.returncode != 0:
            raise ErcAcquisitionError(
                f"ERC execution failed ({result.returncode}): {result.stderr or result.stdout}"
            )
        try:
            payload = json.loads(
                output.read_bytes(),
                object_pairs_hook=_json_pairs,
                parse_constant=_json_constant,
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ErcAcquisitionError(
                f"ERC report is missing or malformed: {exc}"
            ) from exc
        return _report(payload, root, origins, snapshot, result.stdout, result.stderr)
