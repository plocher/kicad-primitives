"""Open a KiCad project and expose settings paths, hierarchy, and text variables.

Parsing of schematic content beyond Sheetfile references stays private and minimal.
This service does not open schematic or PCB documents for edit; that remains later work.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from types import MappingProxyType

__all__ = [
    "InvalidProjectError",
    "Project",
]

_SHEETFILE_RE = re.compile(
    r'\(property\s+"Sheetfile"\s+"([^"]+\.kicad_sch)"',
    re.MULTILINE,
)


class InvalidProjectError(ValueError):
    """The path is not a usable KiCad project or its settings cannot be read."""


class Project:
    """Design context for one KiCad project directory and its root documents."""

    def __init__(
        self,
        directory: Path,
        project_file: Path,
        schematic_file: Path | None,
        pcb_file: Path | None,
        text_variables: Mapping[str, str],
    ) -> None:
        self._directory = directory
        self._project_file = project_file
        self._schematic_file = schematic_file
        self._pcb_file = pcb_file
        self._text_variables = text_variables

    @classmethod
    def open(cls, path: str | PathLike[str]) -> Project:
        """Open a project directory or an explicit ``.kicad_pro`` file.

        Discovery requires exactly the selected ``*.kicad_pro``. Schematic and PCB
        companions are optional. ``text_variables`` are read now; missing maps are
        empty, not errors. Malformed project JSON fails before a context is returned.
        """
        location = Path(path).expanduser().resolve()
        if location.is_file():
            if location.suffix.lower() != ".kicad_pro":
                raise InvalidProjectError(
                    f"Expected a project directory or .kicad_pro file, got: {location}"
                )
            directory = location.parent
            project_file = location
        elif location.is_dir():
            directory = location
            project_file = _find_project_file(directory)
        else:
            raise InvalidProjectError(f"Path does not exist: {location}")

        project_file = project_file.resolve()
        base_name = project_file.stem
        schematic_file = _find_companion(
            directory, base_name, directory.name, ".kicad_sch"
        )
        pcb_file = _find_companion(directory, base_name, directory.name, ".kicad_pcb")
        variables = _read_text_variables(project_file)
        return cls(directory, project_file, schematic_file, pcb_file, variables)

    @property
    def directory(self) -> Path:
        """Absolute project directory that holds the ``.kicad_pro`` file."""
        return self._directory

    @property
    def project_file(self) -> Path:
        """Absolute path of the opened ``.kicad_pro`` file."""
        return self._project_file

    @property
    def schematic_file(self) -> Path | None:
        """Root schematic companion when present, else ``None``."""
        return self._schematic_file

    @property
    def pcb_file(self) -> Path | None:
        """Board companion when present, else ``None``."""
        return self._pcb_file

    @property
    def base_name(self) -> str:
        """Stem of the project file (KiCad's usual shared basename)."""
        return self._project_file.stem

    @property
    def text_variables(self) -> Mapping[str, str]:
        """Read-only ``text_variables`` map from the project file."""
        return self._text_variables

    def schematic_files(self) -> tuple[Path, ...]:
        """Root schematic plus reachable child sheets in discovery order.

        Each ``Sheetfile`` property is resolved relative to the parent sheet's
        directory. Missing children are skipped. Cycles are ignored after the
        first visit. Without a root schematic the result is empty.
        """
        if self._schematic_file is None:
            return ()
        files: list[Path] = []
        processed: set[Path] = set()
        _walk_schematic(self._schematic_file, files, processed)
        return tuple(files)


def _find_project_file(directory: Path) -> Path:
    candidates = sorted(directory.glob("*.kicad_pro"))
    if not candidates:
        raise InvalidProjectError(
            f"No project files found (expected exactly one *.kicad_pro in {directory})"
        )
    if len(candidates) == 1:
        return candidates[0]
    matching = [path for path in candidates if path.stem == directory.name]
    if len(matching) == 1:
        return matching[0]
    return candidates[0]


def _find_companion(
    directory: Path,
    project_stem: str,
    directory_name: str,
    suffix: str,
) -> Path | None:
    files = list(directory.glob(f"*{suffix}"))
    if not files:
        return None

    normal = [path for path in files if not path.name.startswith("_autosave-")]
    autosave = [path for path in files if path.name.startswith("_autosave-")]

    for pool in (normal, autosave):
        if not pool:
            continue
        for preferred in (project_stem, directory_name):
            matches = [path for path in pool if path.stem == preferred]
            if matches:
                return min(matches).resolve()
        if pool is autosave:
            autosave_preferred = f"_autosave-{project_stem}"
            matches = [path for path in pool if path.stem == autosave_preferred]
            if matches:
                return min(matches).resolve()
            autosave_dir = f"_autosave-{directory_name}"
            matches = [path for path in pool if path.stem == autosave_dir]
            if matches:
                return min(matches).resolve()
        return min(pool).resolve()
    return None


def _read_text_variables(project_file: Path) -> Mapping[str, str]:
    try:
        payload = json.loads(project_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidProjectError(
            f"Failed to parse project file as JSON: {project_file}: {exc}"
        ) from exc
    raw = payload.get("text_variables") if isinstance(payload, dict) else None
    return _coerce_text_variables(raw)


def _coerce_text_variables(raw: object) -> Mapping[str, str]:
    if not isinstance(raw, dict):
        return MappingProxyType({})
    coerced: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            coerced[key] = value
    return MappingProxyType(coerced)


def _walk_schematic(
    schematic_path: Path,
    files: list[Path],
    processed: set[Path],
) -> None:
    resolved = schematic_path.resolve()
    if resolved in processed or not schematic_path.exists():
        return
    processed.add(resolved)
    files.append(resolved)
    for sheet_name in _extract_sheet_files(schematic_path):
        child = (schematic_path.parent / sheet_name).resolve()
        if child.exists():
            _walk_schematic(child, files, processed)


def _extract_sheet_files(schematic_path: Path) -> list[str]:
    try:
        content = schematic_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return _SHEETFILE_RE.findall(content)
