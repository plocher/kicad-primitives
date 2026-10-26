# Projects: open, hierarchy, text variables, and write guards

## Scope

`kicad_primitives.projects.Project` opens one KiCad project directory or an
explicit `.kicad_pro` path.
It establishes design context: root document paths, hierarchical schematic
files, and project `text_variables`.
It opens schematic **content** through `schematic()` / `schematics()` (see
[schematics.md](schematics.md)).
Owned schematic objects edit attributes in memory. `Project.save()` explicitly persists their pending changes with electrical verification.
PCB document models remain unsupported. Library tables: [tables.md](tables.md).
`Project.erc()` returns full-hierarchy electrical rule reports against pending source without saving it.
The package remains pre-alpha (`0.0.0` informational).

## Open a project

```python
from kicad_primitives.projects import Project

project = Project.open("/path/to/board")          # directory with *.kicad_pro
# or: Project.open("/path/to/board/board.kicad_pro")

print(project.directory)
print(project.project_file)
print(project.base_name)
print(project.schematic_file)  # optional
print(project.pcb_file)        # optional
```

Discovery requires a selected `*.kicad_pro`.
When several project files exist in a directory, the stem that matches the
directory name wins; otherwise the alphabetically first candidate is used.
Root schematic and PCB companions prefer the project file stem, then the
directory name, then non-autosave files, then autosave-only fallbacks.
Companions are optional.

## Hierarchical schematic files

```python
for path in project.schematic_files():
    print(path)
```

`schematic_files()` returns the root schematic plus reachable child sheets in
discovery order.
Each `(property "Sheetfile" "…")` value is resolved **relative to the parent
sheet directory**, matching KiCad's sheet path rule.
That corrects the jBOM donor habit of joining every child to the project root.
Missing children are skipped. Cycles stop after the first visit. Without a
root schematic the result is empty.

This list is path discovery only.
Sheet instance paths and multi-instance sheet models remain later work.
Placed-symbol and title-block read: [schematics.md](schematics.md).

## Owned documents and explicit persistence

Repeated `schematic()` and `schematics()` accesses reuse owned documents.
Retained placed-symbol handles observe pending edits.
`project.is_modified` is true when any owned schematic differs from its opened or saved baseline.
`schematic.to_bytes()` previews that document without disk writes or KiCad execution.

```python
sheet = project.schematic()
symbol = sheet.symbol("R1")
symbol.set_attribute("Value", "22K")
if project.is_modified:
    project.save()  # explicit, same-location persistence
```

`save(kicad_cli=...)` accepts an optional explicit KiCad executable path.
Changed saves stage the complete hierarchy and project settings, then verify named nets and component identities.
No CLI runs per setter. There is no unchecked-save option.
Save preflights all sources and the project guard before original writes.
Each changed document saves separately. This is not a crash-atomic multi-file transaction.
The [schematic usage page](schematics.md#save-explicitly) defines checks, errors, and supported staging limits.
The `.kicad_pro` remains read-only and serves as verification context.


## Electrical rule reports

```python
report = project.erc()  # optional explicit kicad_cli path
for sheet in report.sheets:
    print(sheet.path, sheet.source_path, len(sheet.violations))
```

Reports preserve per-sheet findings, affected item UUIDs/positions, severities, exclusions, and check metadata.
Original paths and checked-content hashes identify the captured pending snapshot.
Locked and read-only originals remain checkable. No source save or dirty-state reset occurs.
Native local symbol/footprint registrations retain their original variables, paths, raw flags, and effective precedence.
Unsupported context or acquisition failures raise exceptions, not findings.
Document-only `Schematic.erc()` is explicitly unsupported.
The [schematic usage page](schematics.md#electrical-rule-reports) defines report values, context depth, and failures.

## Text variables

```python
for name, value in project.text_variables.items():
    print(name, value)
```

`.kicad_pro` is JSON. The `text_variables` object is exposed as a read-only
`str`→`str` map.
Absence, `{}`, and `null` are normal and yield an empty map—not a diagnostic.
Non-string entries are skipped.
Malformed project JSON raises `InvalidProjectError` on open.

## Write lock and guards

KiCad creates ``<basename>.lck`` while a project is open.

```python
project = Project.open("/path/to/board")
print(project.lock_file, project.is_locked)
if project.write_is_permitted():
    project.ensure_writes_allowed()  # raises ProjectWriteBlockedError if locked
# Preview-only callers:
project.ensure_writes_allowed(dry_run=True)  # locked still OK; do not write
# In-KiCad plugin hosts:
project.ensure_writes_allowed(inside_kicad=True)
```

`is_locked` is presence of the lock file only. Reads are always allowed.
`ensure_writes_allowed` implements the package write policy: bypass inside
KiCad, allow dry-run previews when locked, otherwise raise
`ProjectWriteBlockedError` (a `PermissionError`). The package does not print
to stderr.

## Limits

- Attribute edits belong to placed symbols, not project-level target-selection workflows.
- PCB document models remain unsupported.
- Sheet instance paths and multi-instance sheet models remain later work.
- Library table resolution is a different area.
- Lock guards do not coordinate with KiCad beyond detecting the `.lck` file.
- Save-as relocation and general close/discard/session interfaces are later work.
- No mutation or close action implicitly saves.

## Errors

- `InvalidProjectError`: missing project file, wrong open target, or unreadable
  project JSON.
- `ProjectWriteBlockedError`: KiCad lock blocks non-dry-run writes outside KiCad.
- Ordinary `OSError` subclasses still apply to underlying filesystem failures.

## Tests

Donor gates from jBOM project discovery, context, and variables tests are
ported under `tests/functional/test_project_context.py`, plus a nested parent-relative sheet case.
Write lock gates: `tests/functional/test_project_write_lock.py`.
The normal suite still needs no KiCad install or donor checkout after package
installation:

```bash
uv run python -m unittest discover -s tests -q
```
