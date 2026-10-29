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
`close()` on a clean Project writes nothing. A dirty `close()` runs `save()` first.
`discard()` terminally abandons the Project without writing.
PCB editing models remain unsupported. Library tables: [tables.md](tables.md).
`Project.erc()` returns full-hierarchy electrical rule reports against pending source without saving it.
`Project.netlist()` obtains a full-hierarchy netlist of pending source with provenance; see [netlist.md](netlist.md).
`Project.export_svgs()` writes pending-source schematic SVGs to a new directory; see [schematics.md](schematics.md#svg-export).
The package remains pre-alpha (`0.0.0` informational).

## Surface (ADR 0006 A)

- **Supported:** open and discover a project; hierarchical schematic files; read-only `text_variables`; owned schematic documents; `save()`, `save_as()`, `discard()`, and `close()` with ZIP history; native peer-lock guards; pending-snapshot `erc()`, `netlist()`, and `export_svgs()`.
- **Defined, explicit failure:** save or save-as outside the bounded hierarchy and relocation profile; persistence while a native peer lock exists, including the save that a dirty close runs.
- **1.0 work in progress:** PCB document reads, DRC reports, and Gerber/drill export ([#34](https://github.com/plocher/kicad-primitives/issues/34)). Until then there is no PCB model on `Project`.
- **Deferred past 1.0:** `.kicad_pro` settings editing, sheet instance paths and multi-instance sheets, variants, Git `.history` interoperability ([#58–60](https://github.com/plocher/kicad-primitives/issues/58)), and PCB editing.

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

### Close, discard, and `with`
`project.close(kicad_cli=...)` on a clean Project writes nothing, runs no KiCad process, and creates no ZIP.
Open, read, and close is therefore safe for read-only clients such as BOM generators.
A dirty `close()` runs the full `project.save(kicad_cli=...)`, including verification and ZIP history, then exits.
Close also saves when an earlier save wrote source files but did not publish ZIP history.
If that save fails, `close()` raises and the Project stays open with its pending state.
Then fix the cause and retry, `save_as()` elsewhere, or `discard()`.

`project.discard()` is terminal exit without writing, not reload or rollback.
Owned schematic, placed-symbol, and embedded-symbol operations then reject access.
Diagnostic paths, `is_closed`, and previously captured immutable values remain available.
Close after exit is idempotent. Mutations, discard, and finalizers never write.
Newer edits during verification or file I/O remain pending and are not silently settled.

```python
with Project.open("/path/to/board") as project:
    project.schematic().symbol("R1").set_attribute("Value", "22K")
# Normal exit: close() saved (kicad-cli found through ADR 0007 discovery).
# An exception inside the block: discard(), nothing written.
```

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
Pruning removes only snapshots older than this save's own archive.
Known newer snapshots from another writer are also protected, so concurrent protected history can exceed the budget.
Unrelated ZIP files and names outside this Project's archive namespace are not pruned.

### Failure limits
Source files are persisted separately, not as a crash-atomic Project transaction.
Their baselines advance only after each actual successful write.
A later source failure can leave earlier files saved, with unsaved documents still pending.
Compression/member-read failures normally stop before source replacement because ZIP preparation comes first.
A later publication or retention failure can leave source files saved and history incomplete.
`ProjectBackupError` reports that failure. The Project records that history is incomplete.
A subsequent save, or `close()`, retries the full history step rather than silently settling the failed attempt.
Final optimistic filesystem check/publication races remain possible. Do not write concurrently with another application.

Native Git-backed `.history` interoperability is deferred to research/grilling/design [#58–60](https://github.com/plocher/kicad-primitives/issues/58).

## Save as a new directory and name
`project.save_as(new_path, new_project_name, kicad_cli=...)` creates a new directory with a validated project filename stem.
The destination must not exist. Existing-tree merges, overlapping source/destination trees, and unsafe parent links are refused.
Original source bytes, inodes, and permissions remain unchanged. Read-only sources need readability, not overwrite permission.
Destination files inherit source permission modes.

```python
project = Project.open("/path/to/Old.kicad_pro")
sheet = project.schematic()
placed = sheet.symbol("R1")
project.save_as("/canonical/new-directory", "New")
assert project.schematic() is sheet
assert sheet.symbol("R1") is placed
project.close()
```

The supported profile is one internal root schematic and its strict child hierarchy.
Root/project source basenames must match for the existing verification backend.
Descendant relative layout remains unchanged. Primary `.pro`, root `.sch`, and optional `.pcb` names follow the requested stem.
Root/child filename collisions and unknown extra top-level roots fail before destination publication.
Schematic identity edits require format `20260306`; PCB provenance edits require `20260206`.
The operation preserves UUIDs, library identifiers, references, foreign project groups, and all unrelated source.
Only proved current-project instance labels change. Mixed owned/foreign paths within one group are explicitly unsupported.
PCB direct sheetfile and legacy Sheetfile properties change only with uniquely proved placement UUID provenance.
Human Sheetname values do not change merely because the project filename changes.

Known JSON string members use JSONDecoder-derived spans, not a whole-object rewrite.
`meta.filename` is updated or created. The selected `schematic.top_level_sheets[].filename` follows the root name.
Unrelated JSON, MRU paths, whitespace, BOM/CRLF spelling, and human labels remain untouched.
The ordinary local context includes worksheets, simulator workbooks, sibling rules/UI-state files, symbol/footprint tables, nested native tables, and native libraries.
Copying retains relative layout and KIPRJMOD meaning. Required local URI changes replace only their atoms, preserving raw table flags and opaque metadata.
Intentional stable external references stay external.
Unknown local plugins, nonempty design-block dependencies, unresolved variables, cycles/links, and local/context-dependent simulation or 3D dependencies fail explicitly before destination creation.
This is not arbitrary directory copying or asset vendoring.

Before publication, staged exports prove the requested pending electrical effects, then compare the renamed layout with the validated pending state.
Proof retains named nets, component identity, every endpoint/type, and full exported library pin inventories.
Exact output bytes and the complete destination ZIP are prepared before the destination is reserved.
Files publish with no-clobber writes; native source and destination peer locks remain enforced.
Project/document/placed/embedded identities and path caches rebind only after all files and destination ZIP succeed.
A late I/O failure may leave an incomplete destination. The exception identifies that retained directory; the library never recursively deletes it.
Original live identity and pending source remain available on failure.


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

Native KiCad uses `~` plus the full original filename plus `.lck`:
- `~Demo.kicad_pro.lck` for Project Manager
- `~Demo.kicad_sch.lck` for the schematic editor
- `~Demo.kicad_pcb.lck` for the PCB editor
- Child schematic locks beside their actual child files

`lock_file` reports the canonical Project Manager lock path.
`is_locked` detects any native lock on the known project, root schematic, PCB, and loaded owned schematic paths.
Save strictly loads the hierarchy and checks child locks before source or history writes.
Companions with a different basename use their actual filenames, not a project-stem guess.
Any lock-path presence blocks default persistence, including a dangling link.
The package never acquires, deletes, or decides that a peer lock is stale.
The donor `<basename>.lck` guess is not a compatibility alias.
The native construction and constants are pinned at
[lockfile.h:54–55](https://github.com/KiCad/kicad-source-mirror/blob/2db9e5a72b7cf1e71bb8dff5257a88d4b41f812f/include/lockfile.h#L54-L55)
and [wildcards_and_files_ext.cpp:126–127](https://github.com/KiCad/kicad-source-mirror/blob/2db9e5a72b7cf1e71bb8dff5257a88d4b41f812f/common/wildcards_and_files_ext.cpp#L126-L127).

```python
project = Project.open("/path/to/board")
print(project.lock_file, project.is_locked)
if project.write_is_permitted():
    project.ensure_writes_allowed()  # raises ProjectWriteBlockedError if locked
# Preview-only callers:
project.ensure_writes_allowed(dry_run=True)  # locked still OK; do not write
# Explicit assertion for this helper, not a filesystem-save permission token:
project.ensure_writes_allowed(inside_kicad=True)
```

Reads and ERC remain allowed while locked.
`inside_kicad=None` is conservative filesystem mode, even when `pcbnew` is importable.
Importability does not prove ownership of KiCad's unsaved buffers.
An explicit `inside_kicad=True` remains a caller assertion for the guard query only.
It does not authorize a later filesystem save, which performs its own default native peer-lock checks.
`dry_run=True` permits preview-only validation. There is no save force/allow-locked flag.
Blocked saves raise `ProjectWriteBlockedError` (`PermissionError`) before unsafe persistence.
Locks are checked again before each source replacement and before ZIP publication.
If a new peer lock appears after an earlier file succeeded, completed baselines remain advanced and history stays incomplete.
A later `close()` retries that save and raises `ProjectWriteBlockedError` while the lock remains.
The guard does not remove the final check/write race or coordinate with another process.
The package does not print diagnostics to stderr.

## Limits

- Attribute edits belong to placed symbols, not project-level target-selection workflows.
- PCB document models remain unsupported.
- Sheet instance paths and multi-instance sheet models remain later work.
- Library table resolution is a different area.
- Lock guards detect actual native peer paths but do not acquire locks or coordinate processes.
- Save-as supports the bounded ordinary internal-project profile above, not arbitrary relocation layouts.
- ZIP history does not imply Git history or rollback APIs.
- No mutation, discard, or finalizer saves. A dirty `close()` saves by design.

## Errors

- `InvalidProjectError`: missing project file, wrong open target, or unreadable
  project JSON.
- `ProjectWriteBlockedError`: KiCad lock blocks non-dry-run writes outside KiCad.
- `ProjectLifecycleError`: closed or discarded Project, or a newer pending state that this save did not settle.
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
`tests/verify_project_save_as.py --kicad-cli /path/to/kicad-cli` adds one repeatable current-format root/child/PCB rename proof.
Its native QA derivation and hashes are in `tests/fixtures/projects/rename-native/PROVENANCE.txt`.
