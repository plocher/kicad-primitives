# Projects: context, save, close, backup, and save-as

## Scope

`kicad_primitives.projects.Project` is the layer-1 scope for one KiCad project directory ([ADR 0011](adr/0011-schematic-document-model-save-and-revert.md)).
It establishes design context: root sheet files, the hierarchy, and project `text_variables`.
It owns the project's documents. Today that is the schematic (see [schematics.md](schematics.md)).
`project.save()` saves every changed document the project owns and does nothing else.
`project.close()` applies the close decision chosen at open.
`project.backup()` archives the files on disk now. `project.save_as()` writes a copy and rebinds to it.
None of these operations runs KiCad, checks a lock, or verifies connectivity. Those are client choices.
`Project.erc()`, `Project.netlist()`, and `Project.export_svgs()` work on pending source without saving it.
PCB editing models remain unsupported. Library tables: [tables.md](tables.md).
The package remains pre-alpha (`0.0.0` informational).

## Surface (ADR 0006 A)

- **Supported:** open a project; root sheet files from `top_level_sheets`; read-only `text_variables`; the owned `Schematic`; `save()`, `close()` with `on_close`, `discard()`, and `with`; `backup()`; `save_as()`; lock queries; pending-snapshot `erc()`, `netlist()`, and `export_svgs()`.
- **Defined, explicit failure:** no or several `*.kicad_pro` files; a missing root sheet file; `on_close="raise"` with unsaved changes; save-as outside the bounded relocation profile.
- **1.0 work in progress:** PCB document reads, DRC reports, and Gerber/drill export ([#34](https://github.com/plocher/kicad-primitives/issues/34)). Until then there is no PCB model on `Project`.
- **Deferred:** the `KiCad` root scope and library ownership ([#78](https://github.com/plocher/kicad-primitives/issues/78)); sheet instances and per-instance data ([#79](https://github.com/plocher/kicad-primitives/issues/79)); `.kicad_pro` settings editing; variants; Git `.history` interoperability ([#58–60](https://github.com/plocher/kicad-primitives/issues/58)); PCB editing.

## Open a project

```python
from kicad_primitives.projects import Project

project = Project.open("/path/to/board")                   # the directory
project = Project.open("/path/to/board/board.kicad_sch")   # or any file in it
project = Project.open()                                   # or the current directory

print(project.directory, project.project_file, project.base_name)
print(project.root_sheet_files)  # from top_level_sheets, else <name>.kicad_sch
print(project.pcb_file)          # <name>.kicad_pcb, or None
```

A project reference is a directory or the path of any file in a directory.
That directory must hold exactly one `*.kicad_pro` (the jBOM rule).
None raises `InvalidProjectError` ("not a KiCad project"). Several raise `InvalidProjectError` ("ambiguous").
The project name is the stem of that file.
Root sheet files come from `schematic.top_level_sheets` in the project file when present, else `<name>.kicad_sch`.
A missing root sheet file raises `InvalidProjectError`. Autosave files are never used as roots.
`schematic_file` is the first root sheet file. The PCB is optional.
Malformed project JSON raises `InvalidProjectError`.

## The schematic

```python
schematic = project.schematic()  # the whole document, loaded once
for sheet_file in schematic.files:
    print(sheet_file.path)
```

`schematic()` loads every sheet file reachable from the root sheet files and returns the same object on later calls.
The [schematic usage page](schematics.md) defines the document, its sheet files, edits, save, and revert.

`schematic_files()` lists root and child paths without loading content.
Each `Sheetfile` resolves relative to its parent sheet's directory.
Missing children are skipped. Cycles stop after the first visit.

## Save

```python
schematic.files[0].symbol("R1").set_attribute("Value", "22K")
if project.is_modified:
    project.save()
```

`project.save()` saves every changed document the project owns, without closing.
Today that is the schematic: `project.save()` calls `Schematic.save()`.
An artifact that was never opened is never written.
Files that no editor changes (`.kicad_pro`, `.kicad_prl`, `.kicad_dru`, the PCB, jobsets) are never written.
A failure raises `SchematicSaveError`. Its `results` list what saved and what did not.
The [schematic usage page](schematics.md#save) defines the write set and failure policy.

To check connectivity, the client compares netlists ([netlist.md](netlist.md)):

```python
before = project.netlist()
schematic.files[0].symbol("R1").set_attribute("Value", "22K")
if project.netlist() == before:
    project.save()
```

## Close, discard, and `with`

```python
project = Project.open("/path/to/board", on_close="raise")
```

`on_close` is chosen at open, as in KiCad's close-project dialog:

- `"save"` (default): `close()` saves every changed owned document, then closes. This is "save all".
- `"discard"`: `close()` drops all unsaved changes and closes. This is "do not save".
- `"raise"`: `close()` refuses while anything is unsaved and raises `ProjectUnsavedError`. Its `unsaved` names the changed files. This is "cancel".

A clean project closes without writing, whatever the choice.
If a `"save"` close fails, `close()` raises and the project stays open with what is still unsaved.
After `"raise"`, call each document's `save()` or `revert()`, or `discard()` the project, then close again.

`discard()` ends the project and its documents without a read or a write. It cannot fail.
Owned schematic, sheet-file, placed-symbol, and embedded-symbol operations then raise.
Close and discard are idempotent.

```python
with Project.open("/path/to/board") as project:
    project.schematic().files[0].symbol("R1").set_attribute("Value", "22K")
# Normal exit: close() applies on_close.
# An exception inside the block: discard(), nothing written.
```

## Backup

```python
archive = project.backup(project.backup_directory)
archive = project.backup("/backups/board", size_limit_bytes=100 * 1024 * 1024)
```

`backup(destination)` archives the project files as they are on disk now, then returns the ZIP path.
It does not save first and does not include unsaved edits. Use it before changing anything.
It reads no settings and never decides on its own whether to run. The client owns that policy.

KiCad's conventions are constants, not settings:
`backup_directory` is `<directory>/<name>-backups`, and archives are named `<name>-YYYY-MM-DD_HHMMSS.zip`.
A second backup in the same second gets a suffix such as `-001`. Existing archives are never overwritten.
The destination is created when missing. Its parent must exist.

`size_limit_bytes` omitted means "do not prune".
When given, the oldest archives of this project in the destination are removed until the total fits.
The new archive is never removed. Unrelated ZIP files are never removed.

The archive holds every project-local file with one of these names:

- `.kicad_pro`, `.kicad_prl`, `.kicad_sch`, `.kicad_sym`, `.kicad_pcb`, `.kicad_mod`
- `.kicad_dru`, `.kicad_wks`, `.kicad_jobset`, `.json`, `.wbk`
- `fp-lib-table`, `sym-lib-table`, and `design-block-lib-table`

Hidden files and folders, `<name>-backups`, and a destination inside the project are skipped.
Unsafe or nonportable member names, links, multiply linked members, and unreadable members raise before any archive is written.
Project `.history` and Git configuration are not read or written.

## Save as a new directory and name

```python
project = Project.open("/path/to/Old.kicad_pro")
sheet = project.schematic().files[0]
project.save_as("/path/to/new-directory", "New")
assert project.schematic().files[0] is sheet
```

`save_as(destination, name)` writes every owned document with its current unsaved content.
It copies every other project-local file from disk with the same relative layout.
It rewrites local references and this project's identity, including this project's instance `(project ...)` entries.
Other projects' entries stay unchanged. External references stay external and are not copied.
After success, the project and its documents point at the copy, and `is_modified` is false.
The original directory stays untouched.
Save-as runs no KiCad, writes no backup, and checks no lock.

The destination must not exist. Overlapping source and destination trees and unsafe parent links are refused.
Destination files keep source permission modes. Read-only sources need only read permission.

The supported profile is one internal root sheet file and its child hierarchy.
The root sheet file and the project must share a basename.
Child relative layout stays unchanged. The `.kicad_pro`, root `.kicad_sch`, and optional `.kicad_pcb` take the new name.
Root/child filename collisions and extra top-level sheets fail before the destination is created.
Schematic identity edits require format `20260306`; PCB provenance edits require `20260206`.
UUIDs, library identifiers, references, and unrelated source are preserved.
Mixed own and foreign paths within one instance group are unsupported.
Known JSON members (`meta.filename`, the root `top_level_sheets` filename) change in place; other JSON bytes stay unchanged.
The local context includes worksheets, simulator workbooks, rules and UI-state files, library tables, nested native tables, and native libraries.
Unknown local plugins, nonempty design-block tables, unresolved variables, cycles, links, and local simulation or 3D dependencies fail before the destination is created.

Every captured source is checked again before each write, and every output is checked before the rebind.
A late I/O failure can leave an incomplete destination. The exception names it; the package never deletes it.
On failure, the original binding and pending edits stay.

## Electrical rule reports

```python
report = project.erc()  # optional kicad_cli path
for sheet in report.sheets:
    print(sheet.path, sheet.source_path, len(sheet.violations))
```

`erc()` checks the full pending hierarchy without saving.
The [schematic usage page](schematics.md#electrical-rule-reports) defines report values, context depth, and failures.

## Text variables

```python
for name, value in project.text_variables.items():
    print(name, value)
```

The `text_variables` object is a read-only `str`→`str` map.
Absence, `{}`, and `null` give an empty map. Non-string entries are skipped.

## Locks

Native KiCad uses `~` plus the full original filename plus `.lck`, for example `~Demo.kicad_pro.lck` and `~Demo.kicad_sch.lck`.
`lock_file` is the Project Manager lock path.
`is_locked` is true when a native lock exists for the project file, a root sheet file, the PCB, or any loaded sheet file. A dangling link counts.
Locks are queries, not guards: no package write consults them (ADR 0009).
A client that wants a lock policy checks `is_locked` before it writes.
The package never acquires, deletes, or judges a peer lock. The donor `<basename>.lck` guess is not an alias.
The native construction is pinned at
[lockfile.h:54–55](https://github.com/KiCad/kicad-source-mirror/blob/2db9e5a72b7cf1e71bb8dff5257a88d4b41f812f/include/lockfile.h#L54-L55)
and [wildcards_and_files_ext.cpp:126–127](https://github.com/KiCad/kicad-source-mirror/blob/2db9e5a72b7cf1e71bb8dff5257a88d4b41f812f/common/wildcards_and_files_ext.cpp#L126-L127).

## Limits

- Attribute edits belong to placed symbols, not project-level workflows.
- PCB document models remain unsupported.
- Sheet instances and per-instance data are #79 work.
- Closing or discarding one project-owned sheet file alone is #78 work and raises `UnsupportedSchematicOperationError`.
- No connectivity check, lock policy, or backup policy runs inside a primitive.
- Save-as supports the bounded profile above, not arbitrary relocation layouts.

## Errors

- `InvalidProjectError`: not a KiCad project, an ambiguous project, a missing root sheet file, invalid `top_level_sheets`, or unreadable project JSON.
- `ProjectUnsavedError` (a `ProjectLifecycleError`): `close()` with `on_close="raise"` and unsaved changes.
- `ProjectLifecycleError`: a closed or discarded project.
- `ProjectBackupError` (an `OSError`): unsafe backup destination, member, or archive.
- `SchematicSaveError`: `save()` or a `"save"` close did not write every changed sheet file.
- `ValueError`: an invalid `on_close` or `size_limit_bytes`.
- Ordinary `OSError` subclasses apply to underlying filesystem failures.

## Tests

Donor gates from jBOM project discovery, context, and variables tests are in `tests/functional/test_project_context.py`.
Lifecycle and `on_close` gates: `tests/functional/test_project_lifecycle.py`.
Backup gates: `tests/functional/test_project_backup.py`. Save-as gates: `tests/functional/test_project_save_as.py`.
Lock query gates: `tests/functional/test_project_write_lock.py`.
The normal suite needs no KiCad install or donor checkout:

```bash
uv run python -m unittest discover -s tests -q
```

The opt-in `tests/verify_project_lifecycle.py --kicad-cli /path/to/kicad-cli` edits a disposable real project, checks the netlist stays equal, saves, backs up, and closes.
`tests/verify_project_save_as.py --kicad-cli /path/to/kicad-cli` renames a current-format root/child/PCB project and checks the netlist stays equal.
Its native derivation and hashes are in `tests/fixtures/projects/rename-native/PROVENANCE.txt`.
