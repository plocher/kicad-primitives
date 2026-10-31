"""Known local rules, worksheets, tables, and native-library dependency closure."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from lossless_sexpr import ListNode, TextEdit, apply_edits, parse, quote

from . import _erc_context, _project_files, _project_json, _symbol_parse, tables
from .projects import InvalidProjectError, Project
from .schematics import SchematicConflictError, SheetFile


@dataclass(frozen=True)
class _Directory:
    path: Path
    members: tuple[Path, ...]


def _footprints(path: Path) -> tuple[Path, ...]:
    if path.resolve() != path or not path.is_dir():
        raise InvalidProjectError(
            "Local footprint library must be a contained non-symlink directory"
        )
    mode = stat.S_IMODE(path.stat().st_mode)
    if not mode & 0o444 or not mode & 0o111:
        raise PermissionError("Local footprint library is unreadable")
    return tuple(sorted(p for p in path.iterdir() if p.suffix == ".kicad_mod"))


def check(directories: tuple[_Directory, ...]) -> None:
    """Reject native-library membership changes instead of refreshing a frozen copy."""
    for directory in directories:
        if _footprints(directory.path) != directory.members:
            raise SchematicConflictError(
                "Local footprint-library membership changed during save-as"
            )


def _atom(node: ListNode, index: int) -> str:
    atom = node.atom(index)
    if atom is None:
        raise InvalidProjectError("Missing known local dependency metadata")
    return atom.value


def _dependencies(root: ListNode, suffix: str) -> tuple[str, ...]:
    result: list[str] = []
    if suffix in {".kicad_sch", ".kicad_sym"}:
        owners = list(root.child_lists("symbol"))
        if suffix == ".kicad_sch":
            owners.extend(
                symbol
                for cache in root.child_lists("lib_symbols")
                for symbol in cache.child_lists("symbol")
            )
        for owner in owners:
            for prop in owner.child_lists("property"):
                first = prop.atom(1)
                key = 2 if first is not None and first.raw == "private" else 1
                if _atom(prop, key) in {"Sim.Library", "Spice_Lib_File"}:
                    result.append(_atom(prop, key + 1))
    if suffix in {".kicad_pcb", ".kicad_mod"}:
        model_owners = (
            root.child_lists("footprint") if suffix == ".kicad_pcb" else (root,)
        )
        result.extend(
            _atom(model, 1)
            for owner in model_owners
            for model in owner.child_lists("model")
        )
    return tuple(result)


def collect(
    project: Project,
    destination: Path,
    name: str,
    documents: tuple[SheetFile, ...],
    captured: dict[Path, _project_files._Input],
    outputs: dict[Path, bytes],
    targets: dict[Path, Path],
) -> tuple[_Directory, ...]:
    """Preserve only understood local dependencies, or reject before publication."""
    home = tables._detect_config_home(None)
    variables: dict[str, str] | None = None
    directories: list[_Directory] = []
    active: set[Path] = set()
    done: set[Path] = set()
    standard = re.compile(r"KICAD\d+_(?:SYMBOL_DIR|FOOTPRINT_DIR|3DMODEL_DIR)")

    def maps() -> tuple[dict[str, str], dict[str, str]]:
        nonlocal variables
        if variables is None:
            for key in project.text_variables:
                _project_json.get(project._project_baseline, ("text_variables", key))
            variables = _erc_context._variables(project, home)
        return variables, dict(variables, KIPRJMOD=str(destination))

    def resolve(uri: str, *, new: bool = False) -> Path | None:
        old_vars, new_vars = maps()
        mapping = new_vars if new else old_vars
        expanded = tables._expand_library_uri(uri, mapping)
        if "://" in expanded:
            if expanded.startswith("file://"):
                raise InvalidProjectError(
                    "File-URI dependency relocation is unsupported"
                )
            if tables._expand_library_uri(uri, old_vars) != tables._expand_library_uri(
                uri, new_vars
            ):
                raise InvalidProjectError(
                    "Context-dependent remote dependency cannot be relocated"
                )
            return None
        missing = tables._URI_VARIABLE_PATTERN.findall(expanded)
        if missing:
            if all(
                standard.fullmatch(key) and key not in project.text_variables
                for key in missing
            ):
                return None
            raise InvalidProjectError("Unresolved relocation path variable")
        if "$(" in expanded or not expanded:
            raise InvalidProjectError("Unsupported local dependency path expression")
        raw_path = Path(expanded).expanduser()
        base = destination if new else project.directory
        lexical = Path(
            os.path.abspath(raw_path if raw_path.is_absolute() else base / raw_path)
        )
        if (
            not new
            and lexical.is_relative_to(project.directory)
            and lexical.resolve() != lexical
        ):
            raise InvalidProjectError("Local dependency uses an unsafe link")
        return lexical.resolve()

    def projected(uri: str, source: Path, target: Path) -> str:
        if resolve(uri, new=True) == target:
            return uri
        if target.is_relative_to(destination):
            return "${KIPRJMOD}/" + target.relative_to(destination).as_posix()
        return str(source)

    def add(source: Path, target: Path | None = None) -> Path:
        if not source.is_relative_to(project.directory):
            raise InvalidProjectError(
                "Only local dependency files can enter the copy inventory"
            )
        if source.suffix not in {
            ".kicad_sym",
            ".kicad_mod",
            ".kicad_dru",
            ".kicad_wks",
            ".kicad_prl",
            ".wbk",
        } and source.name not in {
            "sym-lib-table",
            "fp-lib-table",
            "design-block-lib-table",
        }:
            raise InvalidProjectError(
                "Local dependency is outside the supported native copy inventory"
            )
        mapped = target or destination / source.relative_to(project.directory)
        if source not in captured:
            captured[source] = _project_files.read(project.directory, source)
        if source in targets and targets[source] != mapped:
            raise InvalidProjectError(
                "Local dependency has conflicting relocation targets"
            )
        targets[source] = mapped
        outputs.setdefault(mapped, captured[source].raw)
        return mapped

    def validate_native(source: Path) -> None:
        raw = captured[source].raw
        if source.suffix == ".kicad_sym":
            _symbol_parse.read_source(raw)
        roots = parse(raw.decode("utf-8")).roots()
        if len(roots) != 1 or not isinstance(roots[0], ListNode):
            raise InvalidProjectError("Local native dependency has no unique root")
        if source.suffix == ".kicad_mod" and roots[0].head not in {
            "footprint",
            "module",
        }:
            raise InvalidProjectError("Local footprint dependency has no native root")
        for path in _dependencies(roots[0], source.suffix):
            if not path:
                continue
            resolved = resolve(path)
            if resolved is not None and (
                resolved.is_relative_to(project.directory)
                or resolve(path, new=True) != resolved
            ):
                raise InvalidProjectError(
                    "Local/context-dependent simulation or 3D dependencies are unsupported"
                )

    def library(source: Path, kind: str) -> Path:
        if kind == "symbol":
            if source.suffix != ".kicad_sym":
                raise InvalidProjectError("Expected a local native symbol-library file")
            target = add(source)
            validate_native(source)
            return target
        if source.suffix != ".pretty":
            raise InvalidProjectError("Expected a local native .pretty library")
        members = _footprints(source)
        directories.append(_Directory(source, members))
        for member in members:
            add(member)
            validate_native(member)
        return destination / source.relative_to(project.directory)

    def table(source: Path, kind: tables.LibraryType) -> Path:
        if source in active:
            raise InvalidProjectError("Cyclic nested table dependency")
        local = source.is_relative_to(project.directory)
        if source in done:
            return targets[source] if local else source
        active.add(source)
        if local:
            target = add(source)
            raw = captured[source].raw
        else:
            item = _project_files.read(source.parent, source)
            raw, target = item.raw, source
        text = raw.decode("utf-8")
        root = tables._table_root_lists(text, library_type=kind, table_path=source)[0]
        if root.head != tables._TABLE_ROOT_NAMES[kind]:
            raise InvalidProjectError(
                "Nested table kind disagrees with its native root"
            )
        versions = root.child_lists("version")
        if len(versions) > 1 or (versions and _atom(versions[0], 1) != "7"):
            raise InvalidProjectError("Unsupported library-table format")
        edits: list[TextEdit] = []
        for row in root.child_lists("lib"):
            values: dict[str, str] = {}
            for key in ("name", "type", "uri"):
                fields = row.child_lists(key)
                if len(fields) != 1 or len(fields[0].children()) != 2:
                    raise InvalidProjectError(
                        "Ambiguous library registration identity/path"
                    )
                values[key] = _atom(fields[0], 1)
            uri = values["uri"]
            resolved = resolve(uri)
            if resolved is None:
                if values["type"] == "Table":
                    raise InvalidProjectError(
                        "Unresolvable remote table includes are unsupported"
                    )
                continue
            if values["type"] == "Table":
                options = row.child_lists("options")
                if len(options) > 1 or (options and _atom(options[0], 1)):
                    raise InvalidProjectError(
                        "Nested table options are unsupported for relocation"
                    )
                desired = table(resolved, kind)
            elif resolved.is_relative_to(project.directory):
                if values["type"] != "KiCad":
                    raise InvalidProjectError(
                        "Local non-native library plugin dependencies are unsupported"
                    )
                desired = library(resolved, kind)
            else:
                desired = resolved
            replacement = projected(uri, resolved, desired)
            if replacement != uri:
                if not local:
                    raise InvalidProjectError(
                        "External table would require editing a foreign registration"
                    )
                token = row.child_lists("uri")[0].atom(1)
                assert token is not None
                edits.append(TextEdit(token.span, quote(replacement)))
        if local:
            outputs[target] = apply_edits(text, edits).encode("utf-8")
        active.remove(source)
        done.add(source)
        return target

    pro_target = targets[project.project_file]
    for block, keys in (
        ("schematic", ("page_layout_descr_file",)),
        ("pcbnew", ("page_layout_descr_file",)),
        ("schematic", ("ngspice", "workbook_filename")),
    ):
        value = _project_json.get(project._project_baseline, (block, *keys))
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise InvalidProjectError("Known local asset path must be a string")
        source = resolve(value)
        if source is None:
            continue
        if source.is_relative_to(project.directory):
            expected = ".wbk" if keys[-1] == "workbook_filename" else ".kicad_wks"
            if source.suffix != expected:
                raise InvalidProjectError(
                    "Local worksheet/workbook dependency has an unsupported format"
                )
            desired = add(source)
        else:
            desired = source
        replacement = projected(value, source, desired)
        if replacement != value:
            if desired.is_relative_to(destination):
                replacement = desired.relative_to(destination).as_posix()
            outputs[pro_target] = _project_json.set_string(
                outputs[pro_target], (block, *keys), replacement
            )
    for filename, kind in (("sym-lib-table", "symbol"), ("fp-lib-table", "footprint")):
        path = project.directory / filename
        if path.exists() or path.is_symlink():
            table(path, kind)  # type: ignore[arg-type]
    blocks = project.directory / "design-block-lib-table"
    if blocks.exists() or blocks.is_symlink():
        target = add(blocks)
        roots = parse(captured[blocks].raw.decode("utf-8")).roots()
        if (
            len(roots) != 1
            or not isinstance(roots[0], ListNode)
            or roots[0].head != "design_block_lib_table"
            or roots[0].child_lists("lib")
        ):
            raise InvalidProjectError(
                "Nonempty/unknown design-block dependency relocation is unsupported"
            )
        outputs[target] = captured[blocks].raw
    for source in (
        project.project_file.with_suffix(".kicad_prl"),
        (project.pcb_file or project.project_file).with_suffix(".kicad_dru"),
    ):
        if not source.exists() and not source.is_symlink():
            continue
        target = add(source, destination / (name + source.suffix))
        if source.suffix == ".kicad_prl":
            outputs[target] = _project_json.set_string(
                captured[source].raw, ("meta", "filename"), target.name, create=True
            )
    for document in documents:
        roots = parse(outputs[targets[document.path]].decode("utf-8")).roots()
        assert len(roots) == 1 and isinstance(roots[0], ListNode)
        for uri in _dependencies(roots[0], ".kicad_sch"):
            if uri:
                source = resolve(uri)
                if source is not None and (
                    source.is_relative_to(project.directory)
                    or resolve(uri, new=True) != source
                ):
                    raise InvalidProjectError(
                        "Local/context-dependent simulation libraries are unsupported"
                    )
    if project.pcb_file is not None:
        validate_native(project.pcb_file)
    return tuple(directories)
