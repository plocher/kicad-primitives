"""Project schematic SVG export over the shared pending-snapshot staging seam."""

from __future__ import annotations

import os
import subprocess
import unicodedata
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


def _page_name(root_stem: str, names: tuple[str, ...]) -> str:
    """Return KiCad 10's SVG page file name, NFC-normalized for comparison.

    KiCad 10.0.1 ``SCHEMATIC::GetUniqueFilenameForCurrentSheet`` joins the root
    file stem and each raw sheet name with ``-``. ``SCH_PLOTTER`` then replaces
    ``/`` and ``\\`` with ``_`` and adds ``.svg``; it applies no other sanitizing
    (kicad-source-mirror 2db9e5a72b7cf1e71bb8dff5257a88d4b41f812f,
    ``eeschema/schematic.cpp`` and ``eeschema/sch_plotter.cpp``).
    """
    stem = "-".join((root_stem, *names)).replace("/", "_").replace("\\", "_")
    return unicodedata.normalize("NFC", f"{stem}.svg")


def _expected_files(pending: PendingHierarchy) -> dict[str, tuple[str, Path]]:
    """Map KiCad's page file names to (sheet path, source).

    Two sheets with one page name would make KiCad overwrite a page, so that
    raises ``SchematicSvgError`` before the backend runs.
    """
    by_path = {document.path: document for document in pending.documents}
    expected: dict[str, tuple[str, Path]] = {}

    def visit(path: Path, names: tuple[str, ...]) -> None:
        name = _page_name(pending.root.stem, names)
        sheet_path = "/" + "".join(f"{item}/" for item in names)
        if name in expected:
            raise SchematicSvgError(
                f"Sheets {expected[name][0]!r} and {sheet_path!r} map to one "
                f"SVG page name: {name}"
            )
        expected[name] = (sheet_path, path)
        for sheet in by_path[path].sheet_symbols:
            child = (path.parent / sheet.filename).resolve()
            if child in by_path:
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
                cwd=project.directory,  # like ERC: original project directory
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
        # macOS file systems may return NFD names; compare in NFC.
        payloads = {
            unicodedata.normalize("NFC", path.name): path.read_bytes()
            for path in produced
        }
        missing = [name for name in expected if name not in payloads]
        if missing:
            raise SchematicSvgError(
                f"SVG export omits proved hierarchy sheets: {', '.join(missing)}"
            )
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
