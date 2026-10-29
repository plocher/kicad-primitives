"""Project schematic SVG export over the shared pending-snapshot staging seam."""

from __future__ import annotations

import os
import subprocess
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING

from ._kicad_cli import resolve_kicad_cli
from ._pending_snapshot import PendingHierarchy, capture_pending, staged_hierarchy
from ._svg_types import SchematicSvgError, SchematicSvgExport, SchematicSvgFile
from ._symbol_persist import _check_new_destination, save_new_source
from .schematics import UnsupportedSchematicOperationError

if TYPE_CHECKING:
    from .projects import Project

_OUTPUT = "kicad-primitives-svg-output"


def _expected_files(pending: PendingHierarchy) -> dict[str, tuple[str, Path] | None]:
    """Map KiCad's ``root-sheet-...`` file names to (sheet path, source).

    KiCad names each page from the root file stem and the chain of sheet names.
    A colliding name maps to ``None``: the package cannot prove which sheet it is.
    """
    by_path = {document.path: document for document in pending.documents}
    expected: dict[str, tuple[str, Path] | None] = {}

    def visit(path: Path, names: tuple[str, ...]) -> None:
        stem = "-".join((pending.root.stem, *names))
        sheet_path = "/" + "".join(f"{name}/" for name in names)
        expected[f"{stem}.svg"] = (
            None if f"{stem}.svg" in expected else (sheet_path, path)
        )
        for sheet in by_path[path].sheets:
            child = (path.parent / sheet.filename).resolve()
            if sheet.name and child in by_path:
                visit(child, (*names, sheet.name))

    visit(pending.root, ())
    return expected


def export_schematic_svgs(
    project: Project,
    output_dir: str | PathLike[str],
    *,
    kicad_cli: str | PathLike[str] | None,
) -> SchematicSvgExport:
    """Render the pending hierarchy, then publish into a new output directory."""
    destination = Path(output_dir).expanduser().absolute()
    _check_new_destination(
        destination, unsupported_error=UnsupportedSchematicOperationError
    )
    pending = capture_pending(project, operation="Schematic SVG export")
    expected = _expected_files(pending)
    cli = resolve_kicad_cli(None if kicad_cli is None else Path(kicad_cli))
    with staged_hierarchy(
        project, pending.content, prefix="kicad-primitives-svg-"
    ) as stage:
        rendered = stage / _OUTPUT
        rendered.mkdir()
        command = [
            str(cli),
            "sch",
            "export",
            "svg",
            "--output",
            str(rendered),
            str(stage / pending.root.relative_to(project.directory)),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SchematicSvgError(f"SVG export execution failed: {exc}") from exc
        if result.returncode != 0:
            raise SchematicSvgError(
                f"SVG export failed ({result.returncode}): "
                f"{result.stderr or result.stdout}"
            )
        produced = sorted(
            path for path in rendered.iterdir() if path.suffix.lower() == ".svg"
        )
        if not produced:
            raise SchematicSvgError("SVG export produced no files")
        names = {path.name for path in produced}
        missing = [
            name for name, origin in expected.items() if origin and name not in names
        ]
        if missing:
            raise SchematicSvgError(
                f"SVG export omits proved hierarchy sheets: {', '.join(missing)}"
            )
        payloads = {path.name: path.read_bytes() for path in produced}
    _check_new_destination(
        destination, unsupported_error=UnsupportedSchematicOperationError
    )
    os.mkdir(destination)  # exclusive: a racing directory is never reused
    files: list[SchematicSvgFile] = []
    for name, raw in payloads.items():
        target = destination / name
        save_new_source(
            target,
            raw,
            mode=0o644,
            unsupported_error=UnsupportedSchematicOperationError,
        )
        origin = expected.get(name)
        files.append(
            SchematicSvgFile(
                target,
                None if origin is None else origin[0],
                None if origin is None else origin[1],
            )
        )
    return SchematicSvgExport(
        destination, tuple(files), pending.snapshot, result.stdout, result.stderr
    )
