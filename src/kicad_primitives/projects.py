"""Open a KiCad project and expose settings, hierarchy, variables, and schematics.

Schematic *content* is read through :meth:`Project.schematic`, which returns
the whole :class:`~kicad_primitives.schematics.Schematic` (ADR 0002 ownership,
ADR 0011). PCB document models remain later work.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import replace
from os import PathLike
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import TYPE_CHECKING, Literal, Self, get_args

from ._snapshot_types import ProjectSnapshot, SnapshotDocument

if TYPE_CHECKING:
    from ._erc_types import ErcReport
    from ._svg_types import SchematicSvgExport
    from .netlist import Netlist
    from .schematics import Schematic, SheetFile

__all__ = [
    "InvalidProjectError",
    "OnClose",
    "Project",
    "ProjectBackupError",
    "ProjectLifecycleError",
    "ProjectSnapshot",
    "ProjectUnsavedError",
    "SnapshotDocument",
]

OnClose = Literal["save", "discard", "raise"]


class InvalidProjectError(ValueError):
    """The path is not a usable KiCad project or its settings cannot be read."""


class ProjectLifecycleError(RuntimeError):
    """The Project is closed, or it refused to close."""


class ProjectBackupError(OSError):
    """A project backup could not be written safely; no partial archive remains."""


class ProjectUnsavedError(ProjectLifecycleError):
    """``close()`` refused because owned documents have unsaved changes.

    Raised only when the project was opened with ``on_close="raise"``.
    ``unsaved`` names each changed file. Call each document's ``save()``,
    ``revert()``, or the project's ``discard()``, then close again.
    """

    def __init__(self, message: str, unsaved: tuple[Path, ...]) -> None:
        super().__init__(message)
        self.unsaved = unsaved


class Project:
    """Design context for one KiCad project directory and its root documents."""

    def __init__(
        self,
        directory: Path,
        project_file: Path,
        root_files: tuple[Path, ...],
        pcb_file: Path | None,
        text_variables: Mapping[str, str],
        project_baseline: bytes,
        on_close: OnClose = "save",
    ) -> None:
        self._on_close: OnClose = on_close
        self._directory = directory
        self._project_file = project_file
        self._root_files = root_files
        self._schematic_file: Path | None = root_files[0] if root_files else None
        self._pcb_file = pcb_file
        self._text_variables = text_variables
        self._schematic: Schematic | None = None
        self._project_baseline = project_baseline
        self._pcb_baseline = None if pcb_file is None else pcb_file.read_bytes()
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise ProjectLifecycleError(f"Project is closed: {self._project_file}")

    @property
    def is_closed(self) -> bool:
        """Whether the artifact exited through close or terminal discard."""
        return self._closed

    @property
    def on_close(self) -> OnClose:
        """The close decision chosen at open: ``save``, ``discard``, or ``raise``."""
        return self._on_close

    def discard(self) -> None:
        """End the Project and its documents without a read or a write.

        Unsaved changes are dropped. Discard cannot fail and is idempotent.
        """
        self._closed = True

    def close(self) -> None:
        """End the Project, applying the ``on_close`` choice to unsaved changes.

        A clean Project closes without writing, whatever the choice.

        - ``save``: save every changed owned document (:meth:`save`), then
          close. If the save fails, the error propagates and the Project stays
          open with what is still unsaved.
        - ``discard``: drop all unsaved changes and close.
        - ``raise``: refuse with :class:`ProjectUnsavedError`, which names the
          changed files. The Project stays open.

        Close is idempotent.
        """
        if self._closed:
            return
        if self.is_modified:
            if self._on_close == "save":
                self.save()
            elif self._on_close == "raise":
                unsaved = tuple(f.path for f in self._sheet_files() if f.is_modified)
                names = ", ".join(str(path) for path in unsaved)
                raise ProjectUnsavedError(
                    f"Project has unsaved changes: {names}", unsaved
                )
        self.discard()

    def __enter__(self) -> Self:
        """Use the open Project as a context manager."""
        self._check_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Apply ``on_close`` on normal exit; discard when an exception exits."""
        if exc_type is None:
            self.close()
        else:
            self.discard()

    @property
    def is_modified(self) -> bool:
        """Whether any owned document has pending changes."""
        self._check_open()
        return self._schematic is not None and self._schematic.is_modified

    def _sheet_files(self) -> tuple[SheetFile, ...]:
        """Loaded sheet files, without loading the schematic."""
        if self._schematic is None:
            return ()
        return tuple(self._schematic._files.values())

    @classmethod
    def open(
        cls, path: str | PathLike[str] = ".", *, on_close: OnClose = "save"
    ) -> Project:
        """Open the project that a directory or any file in it refers to.

        *path* is a directory, or the path of any file in a directory. That
        directory must hold exactly one ``*.kicad_pro``: none means "not a
        KiCad project", several means "ambiguous". The project name is the
        stem of that file. Root sheet files come from the project's
        ``schematic.top_level_sheets`` when present, else ``<name>.kicad_sch``.
        A missing project file or root sheet file raises
        :class:`InvalidProjectError`. The PCB ``<name>.kicad_pcb`` is optional.
        ``text_variables`` are read now; missing maps are empty, not errors.

        *on_close* chooses what :meth:`close` does with unsaved changes, as
        KiCad's close-project dialog does: ``save`` (save all, the default),
        ``discard`` (do not save), or ``raise`` (cancel and name them).
        """
        if on_close not in get_args(OnClose):
            raise ValueError(f"on_close must be one of {get_args(OnClose)}")
        location = Path(path).expanduser().absolute()
        if location.is_dir():
            directory = location
        elif location.exists():
            directory = location.parent
        else:
            raise InvalidProjectError(f"Path does not exist: {location}")
        directory = directory.resolve()
        project_file = _find_project_file(directory)
        name = project_file.stem
        baseline = project_file.read_bytes()
        payload = _read_project_json(project_file, baseline)
        variables = _coerce_text_variables(payload.get("text_variables"))
        root_files = _root_files(directory, name, payload)
        pcb = directory / f"{name}.kicad_pcb"
        pcb_file = pcb if pcb.is_file() else None
        return cls(
            directory,
            project_file,
            root_files,
            pcb_file,
            variables,
            baseline,
            on_close,
        )

    def save(self) -> None:
        """Save every changed document the project owns, without closing.

        Today that is the schematic (:meth:`Schematic.save
        <kicad_primitives.schematics.Schematic.save>`). An artifact that was
        never opened is never written. The save runs no KiCad, writes no
        backup, and checks no lock (ADR 0011 D5).

        Raises:
            SchematicSaveError: some changed sheet files were not written;
                its ``results`` list what saved and what did not.
        """
        self._check_open()
        if self._schematic is not None:
            self._schematic.save()

    @property
    def backup_directory(self) -> Path:
        """KiCad's conventional backup location: ``<directory>/<name>-backups``.

        A constant naming convention, not a setting. Pass it to :meth:`backup`
        to use the project location.
        """
        return self._directory / f"{self.base_name}-backups"

    def backup(
        self,
        destination: str | PathLike[str],
        *,
        size_limit_bytes: int | None = None,
    ) -> Path:
        """Archive the project files as they are on disk now; return the ZIP path.

        The archive does not save first and does not include unsaved edits.
        Use it to archive the current state before changing anything. It
        holds every project-local KiCad file (project, schematic, PCB,
        settings, rules, drawing sheets, library tables, local libraries),
        skipping hidden entries and backup folders.

        The ZIP is ``<destination>/<name>-YYYY-MM-DD_HHMMSS.zip`` (KiCad's
        convention). A second backup in the same second gets a ``-001``
        suffix and never overwrites. *destination* is created when missing;
        its parent must exist. Use :attr:`backup_directory` for the project
        location.

        *size_limit_bytes* omitted means "do not prune". When given, the
        oldest archives of this project in *destination* are removed until
        the total size fits; the new archive is never removed. The method
        reads no settings and never decides on its own whether to run.

        Raises:
            ProjectBackupError: unsafe destination, member, or archive.
            PermissionError: unreadable members or unwritable destination.
        """
        self._check_open()
        if size_limit_bytes is not None and (
            isinstance(size_limit_bytes, bool)
            or not isinstance(size_limit_bytes, int)
            or size_limit_bytes <= 0
        ):
            raise ValueError("size_limit_bytes must be a positive integer or None")
        from ._project_backup import backup

        return backup(self, Path(destination).expanduser().absolute(), size_limit_bytes)

    def erc(self, *, kicad_cli: str | PathLike[str] | None = None) -> ErcReport:
        """Check the full pending hierarchy without saving or clearing changes.

        Return typed per-sheet findings with original-path snapshot provenance.
        Acquisition failures are exceptions, not synthetic findings. Locked
        and read-only originals remain checkable.
        Relative library URIs use this project's original directory as native CWD.
        """
        self._check_open()
        from ._erc import acquire_erc

        return acquire_erc(self, kicad_cli=kicad_cli)

    def netlist(self, *, kicad_cli: str | PathLike[str] | None = None) -> Netlist:
        """Obtain a netlist of the full pending hierarchy without saving.

        Stage the captured ``.kicad_pro`` and every hierarchy document's
        pending ``to_bytes()`` content, as save verification and :meth:`erc`
        do. Do not save source, clear pending changes, or require the write
        guard. The returned :class:`~kicad_primitives.netlist.Netlist` carries
        ``provenance`` with the project and checked-content hashes. Acquisition
        failures raise ``KicadCliNotFoundError``, ``NetlistExportError``, or
        ``NetlistParseError``. See ``docs/netlist.md``.
        """
        self._check_open()
        from ._pending_snapshot import capture_pending, staged_hierarchy
        from .netlist import _obtain_netlist

        pending = capture_pending(self, operation="Netlist obtain")
        with staged_hierarchy(
            self, pending.content, prefix="kicad-primitives-netlist-"
        ) as stage:
            # Like ERC, the original project directory is the backend CWD.
            exchange = _obtain_netlist(
                stage / pending.root.relative_to(self._directory),
                kicad_cli=kicad_cli,
                cwd=self._directory,
            )
        return replace(exchange, provenance=pending.snapshot)

    def export_svgs(
        self,
        output_dir: str | PathLike[str],
        *,
        kicad_cli: str | PathLike[str] | None = None,
    ) -> SchematicSvgExport:
        """Write SVGs of the full pending hierarchy into a new directory.

        Use the same pending snapshot as :meth:`erc` and :meth:`netlist`. Do
        not save source, clear pending changes, or require the write guard.
        *output_dir* must not exist, even as a symlink; its existing parents
        must be non-symlink, writable directories. Return each produced file
        with its proved sheet mapping and snapshot provenance.
        See ``docs/schematics.md``.

        Raises:
            FileExistsError: *output_dir* exists (including a symlink).
            FileNotFoundError: a parent of *output_dir* is missing.
            PermissionError: the parent directory is not writable.
            UnsupportedSchematicOperationError: a symlinked parent, or an
                unsupported hierarchy or project/root basename layout.
            SchematicConflictError: a hierarchy sheet is missing.
            KicadCliNotFoundError: ``kicad-cli`` discovery failed.
            SchematicSvgError: two sheets map to one page name, the backend
                fails or exceeds its 120 s timeout, produces no SVG, or omits a
                proved sheet. The output directory is not created.
            ProjectLifecycleError: the Project is closed or discarded.
        """
        self._check_open()
        from ._schematic_svg import export_schematic_svgs

        return export_schematic_svgs(self, output_dir, kicad_cli=kicad_cli)

    def save_as(self, new_path: str | PathLike[str], new_project_name: str) -> None:
        """Write the project to a new directory and name, then rebind to it.

        Write every owned document with its current unsaved content. Copy
        every other project-local file from disk with the same relative
        layout, rewriting local references and this project's identity
        (including its instance ``(project ...)`` entries). External
        references stay external and are not copied. After success the
        Project and its documents point at the copy; the original directory
        stays untouched.

        Refuse an existing or overlapping destination and the documented
        unsupported layouts. The save-as runs no KiCad, writes no backup, and
        checks no lock (ADR 0011 D8). A failure can leave an incomplete
        destination, never a rebind.
        """
        self._check_open()
        from ._project_relocate import save_as

        save_as(self, new_path, new_project_name)

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
        """The first root sheet file, or ``None`` after a save-as without one."""
        return self._schematic_file

    @property
    def root_sheet_files(self) -> tuple[Path, ...]:
        """Root sheet files of the top-level sheets, in project order."""
        return self._root_files

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
        """Native Project Manager lock path: ``~<full-project-filename>.lck``."""
        return _native_lock_path(self._project_file)

    def _lock_candidates(self) -> tuple[Path, ...]:
        sources = [self._project_file, *self._root_files]
        if self._pcb_file is not None:
            sources.append(self._pcb_file)
        sources.extend(document.path for document in self._sheet_files())
        return tuple(dict.fromkeys(_native_lock_path(path) for path in sources))

    def _present_locks(self) -> tuple[Path, ...]:
        present: list[Path] = []
        for path in self._lock_candidates():
            try:
                path.lstat()
            except FileNotFoundError:
                continue
            present.append(path)
        return tuple(present)

    @property
    def is_locked(self) -> bool:
        """True when any known native project, sheet, or PCB peer lock is present.

        Presence means KiCad may hold unsaved state for these files. This is a
        query, not a guard: no package write consults it (ADR 0009, ADR 0011
        D9). A client that wants a lock policy checks it before writing.
        """
        self._check_open()
        return bool(self._present_locks())

    def schematic(self) -> Schematic:
        """Return the project's whole schematic: every sheet tree, loaded once.

        The first call loads every reachable sheet file. Later calls return the
        same object. A missing root or child sheet file fails explicitly.
        """
        self._check_open()
        if self._schematic is None:
            if self._schematic_file is None:
                raise InvalidProjectError(
                    f"No root schematic file found for project {self._project_file}"
                )
            from .schematics import Schematic

            self._schematic = Schematic(self, self._root_files)
        return self._schematic

    def schematic_files(self) -> tuple[Path, ...]:
        """Root sheet files plus reachable child sheets in discovery order.

        Each ``Sheetfile`` property is resolved relative to the parent sheet's
        directory. Missing children are skipped. Cycles are ignored after the
        first visit. This reads paths only; :meth:`schematic` loads content.
        """
        self._check_open()
        files: list[Path] = []
        processed: set[Path] = set()
        for root in self._root_files:
            _walk_schematic(root, files, processed)
        return tuple(files)


def _native_lock_path(source: Path) -> Path:
    return source.with_name(f"~{source.name}.lck")


def _find_project_file(directory: Path) -> Path:
    """Apply the jBOM rule: the directory holds exactly one ``*.kicad_pro``."""
    candidates = sorted(
        path for path in directory.glob("*.kicad_pro") if path.is_file()
    )
    if not candidates:
        raise InvalidProjectError(
            f"Not a KiCad project: no *.kicad_pro file in {directory}"
        )
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise InvalidProjectError(
            f"Ambiguous KiCad project: several *.kicad_pro files in {directory}: {names}"
        )
    return candidates[0]


def _companion(directory: Path, name: str, suffix: str) -> Path | None:
    """Return KiCad's ``<name><suffix>`` companion when it is a file."""
    path = directory / f"{name}{suffix}"
    return path if path.is_file() else None


def _read_project_json(project_file: Path, raw: bytes) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise InvalidProjectError(
            f"Failed to parse project file as JSON: {project_file}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise InvalidProjectError(f"Project file is not a JSON object: {project_file}")
    return payload


def _root_files(
    directory: Path, name: str, payload: Mapping[str, object]
) -> tuple[Path, ...]:
    """Root sheet files from ``top_level_sheets``, else ``<name>.kicad_sch``."""
    schematic = payload.get("schematic")
    rows = schematic.get("top_level_sheets") if isinstance(schematic, dict) else None
    if rows is None or rows == []:
        filenames = [f"{name}.kicad_sch"]
    elif isinstance(rows, list) and all(
        isinstance(row, dict)
        and isinstance(row.get("filename"), str)
        and row["filename"]
        for row in rows
    ):
        filenames = [row["filename"] for row in rows]
    else:
        raise InvalidProjectError("Invalid schematic.top_level_sheets in project file")
    roots: list[Path] = []
    for filename in filenames:
        path = Path(os.path.normpath(directory / filename))
        if not path.is_file():
            raise InvalidProjectError(f"Missing root sheet file: {path}")
        if path not in roots:
            roots.append(path)
    return tuple(roots)


def _read_text_variables(project_file: Path, raw: bytes) -> Mapping[str, str]:
    payload = _read_project_json(project_file, raw)
    return _coerce_text_variables(payload.get("text_variables"))


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
    from lossless_sexpr import ListNode, ParseError, parse

    from .schematics import _sheet_filename

    try:
        raw = schematic_path.read_bytes()
    except OSError:
        return []
    try:
        roots = parse(raw.decode("utf-8")).roots()
    except (UnicodeError, ParseError, RecursionError) as exc:
        raise InvalidProjectError(
            f"Invalid hierarchy source: {schematic_path}"
        ) from exc
    if (
        len(roots) != 1
        or not isinstance(roots[0], ListNode)
        or roots[0].head != "kicad_sch"
    ):
        raise InvalidProjectError(
            f"Expected one schematic hierarchy root: {schematic_path}"
        )
    return [_sheet_filename(node) for node in roots[0].child_lists("sheet")]
