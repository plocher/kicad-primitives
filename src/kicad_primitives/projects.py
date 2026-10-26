"""Open a KiCad project and expose settings, hierarchy, variables, and schematics.

Sheetfile path walks stay private. Schematic *content* is read through
:meth:`Project.schematic` / :meth:`Project.schematics` (ADR 0002 ownership).
PCB document models remain later work.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schematics import Schematic

__all__ = [
    "InvalidProjectError",
    "Project",
    "ProjectWriteBlockedError",
]

_SHEETFILE_RE = re.compile(
    r'\(property\s+"Sheetfile"\s+"([^"]+\.kicad_sch)"',
    re.MULTILINE,
)


class InvalidProjectError(ValueError):
    """The path is not a usable KiCad project or its settings cannot be read."""


class ProjectWriteBlockedError(PermissionError):
    """A KiCad lock file blocks package writes outside an in-KiCad session."""


class Project:
    """Design context for one KiCad project directory and its root documents."""

    def __init__(
        self,
        directory: Path,
        project_file: Path,
        schematic_file: Path | None,
        pcb_file: Path | None,
        text_variables: Mapping[str, str],
        project_baseline: bytes,
    ) -> None:
        self._directory = directory
        self._project_file = project_file
        self._schematic_file = schematic_file
        self._pcb_file = pcb_file
        self._text_variables = text_variables
        self._schematics: dict[Path, Schematic] = {}
        self._project_baseline = project_baseline

    @property
    def is_modified(self) -> bool:
        """Whether any owned schematic has pending changes."""
        return any(schematic.is_modified for schematic in self._schematics.values())

    @classmethod
    def open(cls, path: str | PathLike[str]) -> Project:
        """Open a project directory or an explicit ``.kicad_pro`` file.

        Discovery requires exactly the selected ``*.kicad_pro``. Schematic and PCB
        companions are optional. ``text_variables`` are read now; missing maps are
        empty, not errors. Malformed project JSON fails before a context is returned.
        """
        location = Path(path).expanduser().absolute()
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

        directory = directory.resolve()
        project_file = directory / project_file.name
        base_name = project_file.stem
        schematic_file = _find_companion(
            directory, base_name, directory.name, ".kicad_sch"
        )
        pcb_file = _find_companion(directory, base_name, directory.name, ".kicad_pcb")
        baseline = project_file.read_bytes()
        variables = _read_text_variables(project_file, baseline)
        return cls(
            directory, project_file, schematic_file, pcb_file, variables, baseline
        )

    def save(self, *, kicad_cli: str | PathLike[str] | None = None) -> None:
        """Verify and persist changed owned schematics at their current locations.

        Preflight known failures before writing. Files are replaced separately,
        not as a crash-atomic transaction; a later I/O failure can leave earlier
        files saved. Unsaved documents retain pending changes for inspection.
        """
        from ._schematic_persist import save_schematics

        save_schematics(self, tuple(self._schematics.values()), kicad_cli=kicad_cli)

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

    @property
    def lock_file(self) -> Path:
        """Path of the KiCad ``.lck`` file for this project basename."""
        return (self._directory / f"{self.base_name}.lck").resolve()

    @property
    def is_locked(self) -> bool:
        """True when the KiCad lock file is present on disk.

        Presence means KiCad may hold unsaved state; it does not by itself
        forbid reads. Writers should call :meth:`ensure_writes_allowed`.
        """
        return self.lock_file.is_file()

    def write_is_permitted(self, *, inside_kicad: bool | None = None) -> bool:
        """Return whether filesystem writes should proceed under lock policy.

        When *inside_kicad* is omitted, the package probes for an importable
        ``pcbnew`` module (KiCad embedded Python). Callers may pass an explicit
        boolean in tests or known host contexts.
        """
        if _resolve_inside_kicad(inside_kicad):
            return True
        return not self.is_locked

    def ensure_writes_allowed(
        self,
        *,
        dry_run: bool = False,
        inside_kicad: bool | None = None,
    ) -> None:
        """Raise if a KiCad lock should block real filesystem writes.

        Policy:
        - Inside KiCad (plugin/session): always allowed (in-memory host owns state).
        - No lock file: allowed.
        - Locked + ``dry_run=True``: allowed (preview only; no package stderr).
        - Locked + ``dry_run=False``: raises :class:`ProjectWriteBlockedError`.
        """
        if self.write_is_permitted(inside_kicad=inside_kicad):
            return
        if dry_run:
            return
        lock_name = self.lock_file.name
        raise ProjectWriteBlockedError(
            f"KiCad lock file detected ({lock_name}). "
            "The project appears to be open in KiCad. "
            "Unsaved KiCad edits may be invisible to this process, and package "
            "writes may be overwritten when KiCad saves. "
            "Close KiCad before writing, or call ensure_writes_allowed(dry_run=True) "
            "only for non-writing previews."
        )

    def schematic(self, path: str | PathLike[str] | None = None) -> Schematic:
        """Open one schematic in this project (root by default).

        When *path* is given it must resolve to a file returned by
        :meth:`schematic_files`. Outsiders and missing roots fail explicitly.
        """

        if path is None:
            if self._schematic_file is None:
                raise InvalidProjectError(
                    f"No root schematic file found for project {self._project_file}"
                )
            target = self._schematic_file
        else:
            target = Path(path).expanduser().resolve()
            allowed = {p.resolve() for p in self.schematic_files()}
            if target not in allowed:
                raise InvalidProjectError(
                    f"Schematic is not part of project hierarchy: {target}"
                )
        return self._load_schematic(target)

    def _load_schematic(self, target: Path) -> Schematic:
        from .schematics import open_schematic

        key = target.resolve()
        if key not in self._schematics:
            schematic = open_schematic(target)
            object.__setattr__(schematic, "_project", self)
            self._schematics[key] = schematic
        return self._schematics[key]

    def schematics(self) -> tuple[Schematic, ...]:
        """Open every schematic in the hierarchical file list, in walk order."""
        return tuple(self.schematic(path) for path in self.schematic_files())

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


def _resolve_inside_kicad(inside_kicad: bool | None) -> bool:
    if inside_kicad is not None:
        return inside_kicad
    try:
        import pcbnew  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


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
                return min(matches).absolute()
        if pool is autosave:
            autosave_preferred = f"_autosave-{project_stem}"
            matches = [path for path in pool if path.stem == autosave_preferred]
            if matches:
                return min(matches).resolve()
            autosave_dir = f"_autosave-{directory_name}"
            matches = [path for path in pool if path.stem == autosave_dir]
            if matches:
                return min(matches).resolve()
        return min(pool).absolute()
    return None


def _read_text_variables(project_file: Path, raw: bytes) -> Mapping[str, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidProjectError(
            f"Failed to parse project file as JSON: {project_file}: {exc}"
        ) from exc
    raw_variables = payload.get("text_variables") if isinstance(payload, dict) else None
    return _coerce_text_variables(raw_variables)


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
