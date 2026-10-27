# Projects: context, explicit persistence, lifecycle, and ZIP history

## Scope

`kicad_primitives.projects.Project` opens one KiCad project directory or an
explicit `.kicad_pro` path.
It establishes design context: root document paths, hierarchical schematic
files, and project `text_variables`.
It opens schematic **content** through `schematic()` / `schematics()` (see
[schematics.md](schematics.md)).
Owned schematic objects edit attributes in memory.
`Project.save()` persists the supported file set and publishes a complete post-save ZIP snapshot.
Changed schematics require electrical verification. Unchanged JSON and raw PCB companions retain their bytes and inodes.
`close()` requires a current successful Project save decision, even after a clean open.
`discard()` terminally abandons the Project without writing.
PCB editing models remain unsupported. Library tables: [tables.md](tables.md).
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
The optional raw PCB baseline is captured on open.
Schematic source remains owned through existing lazy document access.
Save loads and validates the complete strict hierarchy before preparing its output.

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
Project settings still have no editing interface. Save retains their original JSON bytes.
The optional board is raw captured content, not a new PCB editor.
Its syntax/root/version must be valid. Future formats beyond native KiCad 10.0.1 `20260206` fail.
Older board content remains unchanged read-only data.
The selected companions must remain present and fresh. A changed companion selection is a conflict.
Unlike lenient path discovery, save never skips a missing sheet or silently cuts a cycle.
External, absolute, variable-based, or linked hierarchy paths and ambiguous Sheetfile identities fail explicitly.

### Current decisions and terminal exit
`project.close()` initially raises `ProjectLifecycleError`, including for a clean, never-edited Project.
A complete successful `project.save()` authorizes close only for that current state.
Later actual edits revoke that decision. Exact no-op edits do not.
Every failed save attempt revokes it, even after a previous successful clean save.
A document-only `schematic.save()` does not establish a Project-wide decision.

`project.discard()` is terminal exit without writing, not reload or rollback.
Owned schematic, placed-symbol, and embedded-symbol operations then reject access.
Diagnostic paths, `is_closed`, and previously captured immutable values remain available.
Close after terminal exit is idempotent. No mutation, discard, close, or finalizer saves implicitly.
Newer edits during verification or file I/O remain pending and do not acquire a saved decision.

### ZIP snapshots
Each explicit save publishes a complete snapshot under `<name>-backups`.
Names use `<name>-YYYY-MM-DD_HHMMSS.zip`.
Same-second collisions get an exclusive numeric suffix such as `-001`. Existing files are never truncated.
The initial implementation keeps every explicit snapshot without CRC/content deduplication.
Renaming a member with unchanged contents therefore retains a distinct history state.
Clean saves preserve source bytes/inodes and need no KiCad process, but still create ZIP history.

The native archive allowlist is:
- `.kicad_pro`, `.kicad_prl`, `.kicad_sch`, `.kicad_sym`, `.kicad_pcb`, `.kicad_mod`
- `.kicad_dru`, `.kicad_wks`, `.kicad_jobset`, `.json`, `.wbk`
- Bare `fp-lib-table`, `sym-lib-table`, and `design-block-lib-table`

The bounded inventory scans inside the Project root.
Hidden files/trees and the actual Project backup directory are excluded.
Unrelated files outside the allowlist are not copied.
A legitimate source folder that merely ends in `-backups` is not automatically excluded.
Every required owned project/schematic/PCB member must survive filtering, or save fails before source replacement.
Unsafe/nonportable member names, visible links, multiply linked members, and unreadable included inputs fail explicitly.
Members are never silently omitted. Project `.history` and Git configuration are not read or written.

ZIP bytes are built and checked from frozen planned outputs before original files change.
Publication occurs only after all selected source writes succeed.
For a document-only save, unselected pending siblings contribute their saved baseline bytes, not unsaved edits.
Native `.kicad_prl` and other included files retain their exact captured bytes.

The default total recognized-history budget is 100 MiB.
Use `Project.open(path, backup_size_limit_bytes=0)` for unlimited history, or provide a nonnegative integer byte budget.
There are no legacy count/day/interval caps, GUI format-setting discovery, or autosave scheduler.
After publication, oldest recognized regular snapshots are pruned first.
At least the just-published latest snapshot remains. A sole oversized latest archive makes the budget soft.
Unrelated ZIP files and names outside this Project's archive namespace are not pruned.

### Failures and pending save-as work
Source files are persisted separately, not as a crash-atomic Project transaction.
Their baselines advance only after each actual successful write.
A later source failure can leave earlier files saved, with unsaved documents still pending.
Compression/member-read failures normally stop before source replacement because ZIP preparation comes first.
A later publication or retention failure can leave source files saved and history incomplete.
`ProjectBackupError` reports that failure and leaves close unauthorized.
A subsequent clean save retries the full history step rather than silently settling the failed attempt.
Do not infer that `is_modified == False` authorizes close.
Final optimistic filesystem check/publication races remain possible. Do not write concurrently with another application.

Project save-as relocation is the next bounded milestone and is not implemented yet.
Native Git-backed `.history` interoperability is deferred to research/grilling/design [#58–60](https://github.com/plocher/kicad-primitives/issues/58).


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
- Project save-as relocation remains pending. ZIP history does not imply Git history or rollback APIs.
- No mutation or close action implicitly saves.

## Errors

- `InvalidProjectError`: missing project file, wrong open target, or unreadable
  project JSON.
- `ProjectWriteBlockedError`: KiCad lock blocks non-dry-run writes outside KiCad.
- `ProjectLifecycleError`: closed Project, missing current complete save decision, or a newer pending state that this save did not settle.
- `ProjectBackupError`: unsafe/incomplete snapshot or save/history I/O failure. Some source writes may already have succeeded.
- Existing schematic conflict, format, and electrical-verification errors propagate from owned-file persistence.
- Ordinary `OSError` subclasses still apply to underlying filesystem failures.

## Tests

Donor gates from jBOM project discovery, context, and variables tests are
ported under `tests/functional/test_project_context.py`, plus a nested parent-relative sheet case.
Write lock gates: `tests/functional/test_project_write_lock.py`.
Lifecycle/history/file-set/failure gates: `tests/functional/test_project_lifecycle.py`.
The normal suite still needs no KiCad install or donor checkout after package
installation:

```bash
uv run python -m unittest discover -s tests -q
```

The opt-in `tests/verify_project_lifecycle.py --kicad-cli /path/to/kicad-cli` uses disposable real schematic data and an empty native PCB.
It verifies electrical save, native PCB acceptance, exact ZIP members, stable/terminal handles, and unchanged JSON/PCB/no-op inodes.
