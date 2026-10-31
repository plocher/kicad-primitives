"""Bounded Project save-as: frozen files, known identity spans, explicit publication."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

from lossless_sexpr import parse

from . import (
    _project_assets,
    _project_backup,
    _project_files,
    _project_identity,
    _project_json,
    _schematic_persist,
    _symbol_persist,
)
from ._schematic_restore import predict_restored_signature
from .netlist import export_netlist
from .projects import (
    InvalidProjectError,
    Project,
    ProjectLifecycleError,
    ProjectWriteBlockedError,
    _companion,
    _native_lock_path,
    _read_text_variables,
)
from .schematics import (
    SchematicConflictError,
    SchematicVerificationError,
    SheetFile,
    _sheet_file_from_document,
)


def _check_state(project: Project, generation: int) -> None:
    project._check_open()
    if project._generation != generation:
        raise ProjectLifecycleError(
            "A newer pending state was not included in Project save-as"
        )


def _current(
    project: Project,
    generation: int,
    inputs: tuple[_project_files._Input, ...],
    directories: tuple[_project_assets._Directory, ...],
) -> None:
    _check_state(project, generation)
    project.ensure_writes_allowed()
    _project_files.check(project.directory, inputs)
    _project_assets.check(directories)
    if _companion(project.directory, project.base_name, ".kicad_pcb") != (
        project.pcb_file
    ):
        raise SchematicConflictError(
            "Source companion membership changed during save-as"
        )
    _check_state(project, generation)


def _validate_layout(destination: Path, files: dict[Path, bytes], name: str) -> None:
    seen: set[tuple[str, ...]] = set()
    for target in files:
        relative = target.relative_to(destination)
        _project_backup._safe_name(relative.as_posix())
        if (
            any(part.startswith(".") for part in relative.parts)
            or relative.parts[0] == f"{name}-backups"
        ):
            raise InvalidProjectError(
                "Relocation output conflicts with hidden/history inventory"
            )
        key = tuple(part.casefold() for part in relative.parts)
        if key in seen:
            raise InvalidProjectError("Relocation filenames collide")
        seen.add(key)
    for key in seen:
        if any(key[:index] in seen for index in range(1, len(key))):
            raise InvalidProjectError("Relocation file and directory paths collide")


def _project_metadata(
    raw: bytes, *, project: Project, name: str, root_uuid: str | None
) -> bytes:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise InvalidProjectError("Project settings must be a JSON object")
    schematic = _project_json.get(raw, ("schematic",), default={})
    if not isinstance(schematic, dict):
        raise InvalidProjectError("Schematic settings must be a JSON object")
    top = _project_json.get(raw, ("schematic", "top_level_sheets"), default=[])
    if not isinstance(top, list) or len(top) > 1:
        raise InvalidProjectError(
            "Multiple top-level schematic roots are unsupported for relocation"
        )
    output = _project_json.set_string(
        raw, ("meta", "filename"), f"{name}.kicad_pro", create=True
    )
    if top:
        row = top[0]
        if not isinstance(row, dict) or project.schematic_file is None:
            raise InvalidProjectError("Unprovable top-level schematic metadata")
        filename = row.get("filename")
        if (
            not isinstance(filename, str)
            or Path(filename).is_absolute()
            or (project.directory / filename).resolve() != project.schematic_file
        ):
            raise InvalidProjectError(
                "Top-level metadata does not select the owned root"
            )
        if (
            "uuid" in row
            and _project_json.get(raw, ("schematic", "top_level_sheets", 0, "uuid"))
            != root_uuid
        ):
            raise InvalidProjectError(
                "Top-level UUID disagrees with the selected native root"
            )
        output = _project_json.set_string(
            output,
            ("schematic", "top_level_sheets", 0, "filename"),
            f"{name}.kicad_sch",
        )
    return output


def _write_stage(directory: Path, files: dict[Path, bytes]) -> None:
    for relative, raw in files.items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def _prove(
    project: Project,
    documents: tuple[SheetFile, ...],
    frozen: dict[Path, bytes],
    mapped: dict[Path, bytes],
    destination: Path,
    name: str,
    generation: int,
    inputs: tuple[_project_files._Input, ...],
    directories: tuple[_project_assets._Directory, ...],
    *,
    kicad_cli: str | os.PathLike[str] | None,
) -> None:
    if project.schematic_file is None:
        return
    with TemporaryDirectory(prefix="kp-project-rename-proof-") as temporary:
        root = Path(temporary)
        old = root / "source"
        new = root / "destination"
        _write_stage(
            old,
            {
                document.path.relative_to(project.directory): document._baseline
                for document in documents
            }
            | {Path(project.project_file.name): project._project_baseline},
        )
        before = _schematic_persist._electrical_signature(
            export_netlist(
                old / project.schematic_file.name,
                root / "before.net",
                kicad_cli=kicad_cli,
            ),
            include_libparts=True,
        )
        _current(project, generation, inputs, directories)
        changed = tuple(d for d in documents if frozen[d.path] != d._baseline)
        expected = predict_restored_signature(before, documents, changed)
        _write_stage(
            old,
            {
                document.path.relative_to(project.directory): frozen[document.path]
                for document in documents
            },
        )
        pending = _schematic_persist._electrical_signature(
            export_netlist(
                old / project.schematic_file.name,
                root / "pending.net",
                kicad_cli=kicad_cli,
            ),
            include_libparts=True,
        )
        if pending != expected:
            raise SchematicVerificationError(
                "Pending save-as state does not match independent electrical effects"
            )
        _current(project, generation, inputs, directories)
        _write_stage(
            new, {path.relative_to(destination): raw for path, raw in mapped.items()}
        )
        renamed = _schematic_persist._electrical_signature(
            export_netlist(
                new / f"{name}.kicad_sch", root / "renamed.net", kicad_cli=kicad_cli
            ),
            include_libparts=True,
        )
        if renamed != pending:
            raise SchematicVerificationError(
                "Renamed Project changed full electrical identity"
            )
        _current(project, generation, inputs, directories)


def _destination_locks(paths: tuple[Path, ...]) -> None:
    for source in paths:
        lock = _native_lock_path(source)
        try:
            lock.lstat()
        except FileNotFoundError:
            continue
        raise ProjectWriteBlockedError(f"Native destination peer lock detected: {lock}")


def _destination_outputs(
    outputs: dict[Path, bytes], installed: dict[Path, os.stat_result]
) -> None:
    for target, expected in installed.items():
        info = _symbol_persist._check_baseline(
            target,
            outputs[target],
            conflict_error=SchematicConflictError,
            unsupported_error=InvalidProjectError,
            label="Relocated output",
        )
        if (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns) != (
            expected.st_dev,
            expected.st_ino,
            expected.st_mode,
            expected.st_size,
            expected.st_mtime_ns,
        ):
            raise SchematicConflictError(
                "Destination output changed during publication"
            )


def save_as(
    project: Project,
    new_path: str | os.PathLike[str],
    name: str,
    *,
    kicad_cli: str | os.PathLike[str] | None,
) -> None:
    """Publish one new bounded layout, leaving originals and live identity intact on failure."""
    project._check_open()
    generation = project._generation
    if not isinstance(name, str):
        raise TypeError("new_project_name must be a filename stem")
    if (
        not name
        or name != name.strip()
        or name.startswith(".")
        or any(c in name for c in "/\\")
        or name.endswith((".kicad_pro", ".kicad_sch", ".kicad_pcb"))
    ):
        raise InvalidProjectError("new_project_name must be a portable filename stem")
    _project_backup._safe_name(name + ".kicad_pro")
    destination = Path(new_path).expanduser().absolute()
    if destination.is_relative_to(
        project.directory
    ) or project.directory.is_relative_to(destination):
        raise InvalidProjectError("Source and destination Project layouts overlap")
    _symbol_persist._check_new_destination(
        destination, unsupported_error=InvalidProjectError
    )
    project.ensure_writes_allowed()
    documents = _schematic_persist._hierarchy(project)
    project.ensure_writes_allowed()
    if any(d.version != 20260306 for d in documents):
        raise InvalidProjectError(
            "Schematic relocation requires native format 20260306"
        )
    if (
        project.schematic_file is not None
        and project.schematic_file.stem != project.base_name
    ):
        raise InvalidProjectError(
            "Relocation proof requires matching source root/project basenames"
        )
    captured = {
        project.project_file: _project_files.read(
            project.directory, project.project_file, baseline=project._project_baseline
        )
    }
    frozen = {document.path: document.to_bytes() for document in documents}
    for document in documents:
        captured[document.path] = _project_files.read(
            project.directory, document.path, baseline=document._baseline
        )
    targets = {
        document.path: destination
        / (
            f"{name}.kicad_sch"
            if document.path == project.schematic_file
            else document.path.relative_to(project.directory)
        )
        for document in documents
    }
    root_uuid, owned_paths = (
        _project_identity.ownership(documents, project.schematic_file)
        if project.schematic_file is not None
        else (None, {})
    )
    outputs = {
        targets[document.path]: _project_identity.schematic(
            frozen[document.path],
            old_name=project.base_name,
            new_name=name,
            root_uuid=root_uuid or "",
            owned_paths=owned_paths[document.path],
        )
        for document in documents
    }
    targets[project.project_file] = destination / f"{name}.kicad_pro"
    outputs[targets[project.project_file]] = _project_metadata(
        project._project_baseline, project=project, name=name, root_uuid=root_uuid
    )
    if project.pcb_file is not None:
        assert project._pcb_baseline is not None
        captured[project.pcb_file] = _project_files.read(
            project.directory, project.pcb_file, baseline=project._pcb_baseline
        )
        targets[project.pcb_file] = destination / f"{name}.kicad_pcb"
        outputs[targets[project.pcb_file]] = _project_identity.pcb(
            project._pcb_baseline,
            documents=documents,
            owned_paths=owned_paths,
            source_directory=project.directory,
            destination_directory=destination,
            targets={d.path: targets[d.path] for d in documents},
            root_uuid=root_uuid or "",
        )
    directories = _project_assets.collect(
        project, destination, name, documents, captured, outputs, targets
    )
    _validate_layout(destination, outputs, name)
    inputs = tuple(captured.values())
    _current(project, generation, inputs, directories)
    _prove(
        project,
        documents,
        frozen,
        outputs,
        destination,
        name,
        generation,
        inputs,
        directories,
        kicad_cli=kicad_cli,
    )
    snapshot = _project_backup.build(
        tuple(
            _project_backup._Member(
                source,
                target.relative_to(destination).as_posix(),
                captured[source].raw,
                outputs[target],
                captured[source].info,
            )
            for source, target in targets.items()
        )
    )
    _current(project, generation, inputs, directories)
    projections = {
        d.path: _sheet_file_from_document(
            targets[d.path], parse(outputs[targets[d.path]].decode("utf-8"))
        )
        for d in documents
    }
    for document in documents:
        updated = projections[document.path]
        for old, new in zip(document.symbols, updated.symbols, strict=True):
            if (old.uuid, old.reference, old.lib_id, old.unit) != (
                new.uuid,
                new.reference,
                new.lib_id,
                new.unit,
            ):
                raise InvalidProjectError("Relocation changed a live placed identity")
    new_variables = _read_text_variables(
        targets[project.project_file], outputs[targets[project.project_file]]
    )
    destination.mkdir(mode=0o700)
    try:
        for directory in directories:
            target_directory = destination / directory.path.relative_to(
                project.directory
            )
            target_directory.mkdir(parents=True, exist_ok=True)
        owned_targets = tuple(
            targets[source]
            for source in (
                project.project_file,
                *frozen,
                *((project.pcb_file,) if project.pcb_file else ()),
            )
        )
        installed: dict[Path, os.stat_result] = {}
        for source, target in targets.items():
            _current(project, generation, inputs, directories)
            _destination_locks(owned_targets)
            target.parent.mkdir(parents=True, exist_ok=True)
            installed[target] = _symbol_persist.save_new_source(
                target,
                outputs[target],
                mode=stat.S_IMODE(captured[source].info.st_mode),
                unsupported_error=InvalidProjectError,
            )
        _destination_outputs(outputs, installed)
        context = Project.open(destination / f"{name}.kicad_pro")
        _schematic_persist._hierarchy(context)
        _current(project, generation, inputs, directories)
        context.ensure_writes_allowed()
        _project_backup.publish(context, snapshot)
        _current(project, generation, inputs, directories)
        _destination_locks(owned_targets)
        _destination_outputs(outputs, installed)
        _current(project, generation, inputs, directories)
        old_project, old_pcb = project.project_file, project.pcb_file
        for document in documents:
            source = document.path
            updated = projections[source]
            object.__setattr__(document, "path", targets[source])
            object.__setattr__(document, "_document", updated._document)
            document._mark_saved(outputs[targets[source]])
            object.__setattr__(document, "sheet_symbols", updated.sheet_symbols)
            for old, new in zip(document.symbols, updated.symbols, strict=True):
                for field in ("path", "attributes", "value", "footprint"):
                    object.__setattr__(old, field, getattr(new, field))
            document._restore_intents.clear()
        project._directory = destination
        project._project_file = targets[old_project]
        project._project_baseline = outputs[project.project_file]
        project._text_variables = new_variables
        project._schematic_file = (
            destination / f"{name}.kicad_sch" if documents else None
        )
        project._root_files = (
            () if project._schematic_file is None else (project._schematic_file,)
        )
        project._pcb_file = None if old_pcb is None else targets[old_pcb]
        project._pcb_baseline = None if old_pcb is None else outputs[targets[old_pcb]]
        if project._schematic is not None:
            project._schematic._rebind(
                () if project._schematic_file is None else (project._schematic_file,),
                documents,
            )
        project._history_pending = False
    except Exception as exc:
        exc.add_note(
            f"Incomplete save-as destination retained at {destination}; no recursive cleanup was attempted"
        )
        raise
