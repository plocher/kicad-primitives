# ADR 0011: Schematic document model, save, and revert

Date: 2026-10-30

Status: Accepted by the owner on 2026-10-31. Decisions grilled with the owner on [#75](https://github.com/plocher/kicad-primitives/issues/75) on 2026-10-30.

Related: [ADR 0008](0008-artifact-objects-and-explicit-persistence.md), [ADR 0009](0009-primitives-not-an-executive.md), [#78](https://github.com/plocher/kicad-primitives/issues/78) (KiCad and Project scopes), [#79](https://github.com/plocher/kicad-primitives/issues/79) (sheet model and per-instance data).

Evidence: [eeschema schematic file handling research](../review/eeschema-schematic-file-handling-2026-10-30.md).
KiCad source claims were checked against tag `10.0.7` of the KiCad source mirror.

## Problem

ADR 0009 lists composite operations to split: `Project.save()`, `Schematic.save()`, `Project.close()`, `Project.save_as()`, and `EmbeddedSymbol.restore_from()`.
It asks for owner grilling on each split before implementation.

The grilling found a second problem under the first.
The package names do not match KiCad's model of a schematic.

- The public class `Schematic` is one `.kicad_sch` file. In KiCad, the schematic is the whole hierarchy of sheets.
- The public class `SheetInstance` is the box on a parent sheet. In KiCad, a sheet instance is one placement in the hierarchy.
- `Schematic.save()` writes one file. KiCad has no such product action. KiCad saves the whole schematic.
- `Project.save()` acts as the schematic save and also checks locks, runs `kicad-cli`, writes a ZIP, and prunes old ZIPs.

A split that keeps the wrong nouns encodes the confusion into every later API, document, and client.
This ADR fixes the nouns and the save, revert, close, backup, and save-as behavior together.

## Constraints and requirements

- Keep ADR 0002 functional ownership, ADR 0003 byte preservation, and ADR 0006 release scope.
- Keep the ADR 0009 primitive test and write promises (no silent overwrite, no partial file, no stray KiCad files, no in-memory original).
- Mimic KiCad behavior and vocabulary. Record each deliberate deviation and its reason.
- A primitive does one job. Policy, such as connectivity checks, backups, and lock guards, stays outside primitives.
- Settings values come from KiCad configuration files at runtime. Do not hard-code them.
- Pre-1.0: rename misleading interfaces. Do not keep compatibility aliases.

## Definition of success

- Package nouns map one to one onto KiCad concepts that users see.
- `save()` writes files and does nothing else.
- Every removed behavior is possible as a short client sequence of public primitives.
- Each deviation from KiCad is named here and on the usage page.

## Layers

This ADR uses the three-layer frame that the owner locked in [#78](https://github.com/plocher/kicad-primitives/issues/78).

- **Layer 0: files.** One file with a data model limited to what that file says. Every layer-0 artifact keeps the full lifecycle: open, read, modify, validate, save, revert, discard, close.
- **Layer 1: the joined-up view.** Scopes (`Project`, later `KiCad`) and cross-file documents (`Schematic`) join layer-0 artifacts with KiCad's cross-file rules. A scope drives the lifecycle of the artifacts it owns.
- **Layer 2: policy.** Plain functions built from layers 0 and 1.

Clients use the layer that fits. Layer 1 adds joining-up. It does not hide or replace layer-0 operations.

## KiCad facts that drive the decisions

- KiCad's `SCHEMATIC` holds a hierarchy. Opening it loads every reachable sheet. A file used by several sheet boxes loads once as one `SCH_SCREEN`.
- KiCad 10 lists peer top-level sheets in `schematic.top_level_sheets` in the `.kicad_pro` file. There is no single root that users see.
- Save and Save As act on the whole schematic (`SCH_EDIT_FRAME::SaveProject`). When the schematic has changes, KiCad rewrites every sheet file. On a failure, it continues with the other sheets.
- KiCad's per-sheet save actions write a copy elsewhere. They do not write the original file alone.
- File → Close Project and File → Exit ask about every unsaved document, one decision per document. That is KiCad's indirect save-all.
- Revert exists at every level, in memory: one symbol, one symbol library, all libraries, one footprint, and the schematic.
- The symbol editor's Save of one symbol calls `saveLibrary` and writes the whole library file.
- Per-instance data lives in `(instances (project NAME (path ...)))` entries. Symbol references, units, DNP, and exclusion flags are on the placed symbol in the child file. A child sheet's page number is on the box in the parent file. Several projects can share one sheet file, each with its own entries.
- `CreateNewProject` always writes `<name>.kicad_pro`, `<name>.kicad_sch`, and a stub `<name>.kicad_pcb`.
- Backup settings are in `kicad_common.json` under `auto_backup`: `enabled`, `format` (`INCREMENTAL` or `ZIP`), `location`, and `limit_total_size`.
- The schematic editor never reads a sheet file's modification time.

## Decisions

Each decision lists the candidates, the evaluation, and the choice.

### D1. Nouns: SheetFile, SheetSymbol, SheetInstance, Schematic

Candidates:

- A. Keep the current names. No churn. Every client learns a model that contradicts KiCad.
- B. Use KiCad's internal class names (`Screen`, `Sheet`, `SheetPath`). Exact, but users never see these names.
- C. Use names that users see, with KiCad's class names in the glossary.

Choose C.

| Package noun | Meaning | KiCad |
| --- | --- | --- |
| `SheetFile` | One `.kicad_sch` file. One object per file, even when several boxes use it. | `SCH_SCREEN` |
| `SheetSymbol` | The box on a parent sheet file, with its pins and a pointer to a target file. | `SCH_SHEET` |
| `SheetInstance` | One placement in the hierarchy, identified by its UUID path. It has no storage of its own. | `SCH_SHEET_PATH` |
| `Schematic` | The project's set of sheet trees. | `SCHEMATIC` |

- Do not add a bare `Sheet` class. That word caused the confusion.
- A schematic is a set of trees. The package does not invent a hidden root.
- A child instance gets its name, UUID, and pins from its `SheetSymbol`. A top-level instance gets its name and UUID from its `top_level_sheets` entry. A top-level sheet never appears as a `SheetSymbol` on another sheet.

Scope split:

- This ADR renames today's `Schematic` class to `SheetFile` and today's `SheetInstance` class to `SheetSymbol`. It adds the new `Schematic` with `files`.
- #79 owns instance trees, per-instance data, `SymbolInstance`, the box as the instance's port interface, sheet-symbol add, change, and delete, and `sheet_file.duplicate()`.
- `SheetFile.symbol(reference)` and `PlacedSymbol.reference` stay as documented debt until #79 replaces them with instance lookups.

Layers:

- `SheetFile` is a layer-0 artifact with the full lifecycle, including `SheetFile.open(path)` and `save()`. `SheetFile.open(path)` replaces the free function `open_schematic()`.
- A `SheetFile` knows nothing about the hierarchy. It cannot keep parent sheet-symbol pins matched with its hierarchical labels. Its usage page states this limit.
- `Schematic` is a layer-1 document. `Schematic.save()` applies D3 and D4 over the `SheetFile` saves.
- This reverses an earlier grilling lock that single-sheet save is not public. With layers, single-file I/O is public layer-0 behavior, and the hierarchy save is the layer-1 operation.

### D2. Project reference, validity, and entry

- A project reference is a directory (default `.`) or the path of any file in a directory. That directory must hold exactly one `*.kicad_pro`. None means "not a KiCad project". Several means "ambiguous". The project name is the stem of that file. This is the jBOM rule.
- `Project.open` raises `InvalidProjectError` when the `.kicad_pro` file or a root sheet file is missing. Root files come from `top_level_sheets` when present, else from `<name>.kicad_sch`. The PCB stays optional.
- `project.schematic()` returns the whole `Schematic`. `project.schematics()` is removed.
- There is no `Schematic.open` and no `Pcb.open`. Entry is through `Project`.
- The `KiCad` root scope, with `Project.open` as a wrapper over it, belongs to #78. This ADR does not depend on it.

### D3. What Schematic.save() writes

Candidates:

- A. Do what KiCad does: when anything is unsaved, rewrite every sheet file.
- B. Write only the sheet files that have unsaved changes.

KiCad's rewrite-all behavior comes from its formatter. It gives no benefit to a byte-preserving writer.
An unchanged file written back is identical, so A only adds work and risk.
A adds conflict, permission, and format exposure on every file.
It forces an unasked format upgrade or a failure on an unchanged older-format sheet.
It changes modification times, which breaks other open handles' fingerprints and triggers tools that watch times.

Choose B. This is a deliberate deviation from KiCad.

- `Schematic.save()` writes only changed sheet files. It does not touch the others: no rewrite and no time change.
- A clean save writes nothing.

### D4. Schematic.save() failure policy

Candidates:

- A. Stop at the first failure.
- B. Continue past failures, as KiCad does.
- C. Classify failures and handle each class in its own way.

Choose C.

| Failure | When found | Behavior |
| --- | --- | --- |
| Our content is invalid (source, unsupported format) | `validate()` on every changed sheet, before any write | Write nothing. Raise and name the sheets. No retry. |
| Conflict (the disk file is not the file we read) | Before any write, and again before each replace | Never retry. Never overwrite. That sheet stays unsaved and is reported as a conflict. |
| Permissions | Before any write, for every changed sheet | Write nothing. Raise and name the sheets. |
| Permissions change during the save | During a write | Report. Do not retry. |
| Short-lived system error (interrupted call, busy file, sync-tool hold, timeout) | During a write | Continue with other sheets. At the end, retry the failed sheets once after a short wait. Check for conflicts again first. |
| Lasting system error (disk full, read-only volume, hard I/O error) | During a write | Stop at once. Write no more sheets. |

- `Schematic.save()` is the layer-1 operation. It runs this policy over the layer-0 `SheetFile` saves.
- Write child sheets before their parents. A parent on disk then never names a child file that does not exist.
- Written sheets become saved. All other sheets stay unsaved.
- `SchematicSaveError` lists each sheet as written, conflict, or failed, with the reason.
- A later `save()` writes only what is still unsaved.
- The retry bound is a fixed, documented internal value. It is not a parameter.
- `save(overwrite=True)` is the explicit way through a conflict (ADR 0009).
- `schematic.validate()` is public. It runs the content checks without a write.

### D5. Project save and close, and who ends things

Candidates:

- A. Keep ADR 0008: a dirty close always saves.
- B. Choose the close decision at open, as `FootprintLibrary` does (ADR 0009).

Choose B. It maps onto KiCad's close-project dialog.

- `Project.open(ref, on_close="save" | "discard" | "raise")`. The default is `"save"`.
  - `save`: save every changed document the project owns, then close. This is "save all".
  - `discard`: drop all unsaved edits and close. This is "do not save all".
  - `raise`: refuse to close while anything is unsaved, and name it. This is "cancel". The client then calls each named document's `save()`, `revert()`, or `discard()` and closes again.
- `project.save()` saves every changed document the project owns, without closing. Today that is the schematic. The PCB and project-table libraries join it later. It does not run `kicad-cli`, write a ZIP, or check locks. Its error lists what saved and what did not.
- A `with` block applies `on_close` on normal exit. It discards when an exception exits it.
- The "unpublished history" retry in close is removed.
- Every artifact keeps the full layer-0 lifecycle, including `close()` and `discard()`.
- A scope drives the lifecycle of the artifacts it owns. `project.close()` calls each owned artifact's validate, save, and close according to `on_close`. This is the layer-1 usage model. Layer-0 clients call the artifact operations directly.
- `kicad.close()` and `kicad.discard()` follow with #78.
- What happens when code calls `close()` on an artifact that a scope also holds is decided in #78.
- Library ownership follows the library's type, not how a client reached it. Project-table libraries belong to that project. Global-table and table-less libraries belong to the `KiCad` scope. This part is implemented with #78.
- Deviation: KiCad's close-project also settles global libraries, because KiCad has one project open at a time. The package can hold several projects. A client that wants KiCad's exact behavior calls `project.close()`, then `kicad.close()`.

Project scope. `project.save()` writes every open, project-owned artifact that has unsaved changes, and nothing else.

| Artifact | Project-owned when | Saved by `project.save()` |
| --- | --- | --- |
| Schematic (sheet files) | Always | Now |
| `.kicad_pro` | Always | When a settings editor exists. None exists today, so it is never changed. |
| PCB | Always | When a board editor exists |
| Project library tables (`sym-lib-table`, `fp-lib-table` in the project directory) | Always | When opened through the project (#78) |
| Libraries | Listed in the project's table | #78 |
| Drawing sheets (`.kicad_wks`) | Referred to by the project's settings | When a worksheet artifact exists |

- Global-table libraries, table-less libraries, and global drawing sheets belong to the `KiCad` scope. `project.save()` never writes them.
- An artifact that was never opened is never written.
- Files that no editor changes (`.kicad_prl`, `.kicad_dru`, jobsets) are never written.
- A library listed in both the project table and the global table is to be decided in #78. The proposal is that the project owns it, because the project table wins in KiCad's nickname resolution.

### D6. Revert

- Every artifact has `revert()`, beside `discard()`. Revert drops unsaved edits and reloads from disk.
- After a revert, the object keeps its identity, and `is_modified` becomes false. Handles to things inside it become invalid. Clients get fresh ones.
- Revert and discard have different jobs:
  - `revert()` starts the artifact over from disk, and the client keeps using it. It reads the disk, so it can fail (missing file, fingerprint mismatch, permissions).
  - `discard()` ends the artifact without a read or a write, so it cannot fail (ADR 0008).
  - Error paths use `discard()`: a `with` block that exits on an exception, and `on_close="discard"`. A revert there could replace the original error with a conflict error, or stop a close part-way.
- Save and revert differ in granularity on purpose. Save writes files, so its unit follows storage. Revert changes only memory, so it works at any level.

| | Schematic | Library | Item |
| --- | --- | --- | --- |
| `save()` | Changed sheet files | The library | Footprint: its own file. Symbol: the library file, with other changed symbols in it. |
| `revert()` | The whole hierarchy | Every item in it | That item only |

- No in-memory original. An artifact keeps a fingerprint (modification time, size, and content hash) of what it read, refreshed after each save. While the fingerprint matches, the disk file is the original, and revert reads from it.
- If the fingerprint does not match, revert raises a conflict. It does not mix two versions.
- `is_modified` is a flag that setters keep (ADR 0009). The package does not compare against a stored copy.
- Footprint create, copy, delete, and rename are immediate file-system operations (ADR 0009). Revert never undoes them. Symbol create, delete, and rename are pending edits in the library file, so `symbol.revert()` undoes them.
- Undo is a finer-grained revert. It is not designed or requested now. The no-copy rule does not block it, because undo records edits, not a second copy.
- In this ADR's scope: `Schematic.revert()`. Library and item revert belong to #78.

### D7. project.backup()

- `project.backup()` archives the project files as they are on disk now. It does not save first. It does not include unsaved edits. Use: archive the current state before changing anything.
- It is a capability with no policy inside. Destination and size limit are explicit arguments with no built-in default values. An omitted limit means "do not prune". It never reads settings and never decides whether to run.
- KiCad's format conventions are constants, not policy: `<name>-backups/` and `<name>-YYYY-MM-DD_HHMMSS.zip`. `backup()` can use them when the caller asks for the project location.
- `Project.open(backup_size_limit_bytes=...)` is removed.
- KiCad's `auto_backup` settings become data that the `KiCad` scope exposes (#78). The client decides whether to call `backup()`.

### D8. project.save_as()

- Project documents (schematic, PCB, project file) have no `save_as` of their own. They exist only inside a project, so `project.save_as(destination, name)` is how they move.
- Libraries keep their own `save_as`. They are independent artifacts that can exist without a project (`SymbolLibrary.save_as()`, `Footprint.save_as()`).
- `project.save_as()` writes every open owned document with its current unsaved content.
- It copies every other project-local file from disk with the same relative layout. This is the ordinary local context in `docs/projects.md`: UI state, rules, drawing sheets, simulator workbooks, local and nested library tables, and local libraries.
- It rewrites local URIs where needed. External references (global libraries, paths outside the project directory) stay external and are not copied.
- It rewrites project identity, including this project's instance `(project ...)` entries. Other projects' entries stay unchanged.
- After success, it rebinds the `Project` and its documents to the copy. The original directory stays untouched.
- It keeps the file-integrity rules: it refuses an existing destination, and it keeps the documented limits on relocatable layouts.
- It no longer runs the electrical check, writes a ZIP into the new directory, or checks locks.
- `save_as` keeps one meaning across the package: write this artifact to a new place and rebind to it.
- `sheet_file.duplicate(new_name)` is a different operation. The original stays the edited copy. It belongs to #79.

### D9. ADR 0009 items that this ADR implements without change

- `EmbeddedSymbol.restore_from()` becomes `update_from_library(library, name)`. The deferred restore intent and the predicted pin-type check are removed.
- `ensure_writes_allowed()` and `write_is_permitted()` are removed. `is_locked` and `lock_file` stay as queries. No write consults them.
- `Netlist.__eq__` compares electrical content: component identity and every pin-to-net connection. Export order and net codes do not count. `connectivity_sets()` stays as a helper that shows differences.
- `SymbolLibrary` and `LibraryTable` get a public `validate()`, a flag-based `is_modified`, a fingerprint instead of a stored byte copy, and `save(overwrite=True)`.

### D10. Recipes

Candidates:

- A. Ship one recipe per removed behavior, as ADR 0009's rollout says.
- B. Ship one recipe to prove the layer works.
- C. Ship no recipes until one is needed.

A and B both presume a before/after connectivity check that a client may never use.
Netlist state capture is also too complex for a first example.
Short sequences, such as "save if modified", belong in client code and in usage-page examples.

Choose C.

- Recipes are plain functions in their own isolated namespace. Their contents are to be decided.
- This ADR ships no recipe and no recipes module.
- The test that recipes import only public names arrives with the first recipe.
- The checks removed from save are removed, not moved.
- Today's save-verification tests become functional tests of the primitives that remain. `Netlist.__eq__` reports no change after an attribute edit and a change after an electrical edit. `save()` writes without running KiCad.

## Glossary changes (CONTEXT.md)

Add:

- **Schematic**: the project's set of sheet trees, opened, saved, and reverted as one document. KiCad `SCHEMATIC`.
- **Sheet file**: one `.kicad_sch` file. Content edits to it reach every instance of it. KiCad `SCH_SCREEN`. _Avoid_: sheet, schematic, for one file.
- **Sheet symbol**: the box on a parent sheet file that points at a target sheet file. Its pins are the electrical interface of the instance. KiCad `SCH_SHEET`.
- **Sheet instance**: one placement of a sheet file in the hierarchy, identified by its UUID path. It holds per-placement data. KiCad `SCH_SHEET_PATH`.
- **Revert**: drop unsaved edits of an artifact or item and reload it from disk. The object stays open.
- **Scope**: a layer-1 owner of artifacts that drives their lifecycle. Closing a scope applies its `on_close` choice to its unsaved artifacts. Today: `Project`. Later: `KiCad` (#78).
- **Layer 0 / Layer 1 / Layer 2**: files / the joined-up view / policy (#78).

Close and Discard keep their ADR 0008 meanings.

## Relationship to earlier ADRs

- Amends ADR 0008:
  - "A dirty close always saves" becomes the `on_close` choice for scopes.
  - Adds `revert()` beside the terminal `discard()`, which is unchanged.
  - The Project ZIP and same-location lifecycle section is replaced by D3 to D8.
- Amends ADR 0009:
  - Refines composite splits 1 to 3: save, close, and save-as.
  - Withdraws the rollout rule "each split adds its recipe".
  - Adds the three-layer frame (#78). The ADR 0009 artifact lifecycle becomes the layer-0 lifecycle, plus `revert()`.
- Does not change ADR 0002, ADR 0003, or ADR 0006.

## Consequences and implementation order

Implement under #75 on one feature branch, as serial validated commits:

1. Nouns. Rename `Schematic` to `SheetFile` and `SheetInstance` to `SheetSymbol`. Add `Schematic` with `files`. Add `project.schematic()`. Remove `project.schematics()`. Update `CONTEXT.md`.
2. Project reference and validity check. Remove `backup_size_limit_bytes`.
3. `SheetFile` layer-0 lifecycle: public `SheetFile.open(path)` (replaces `open_schematic()`), fingerprint, flag-based `is_modified`, `validate()`, `save()`, `revert()`, `discard()`, and `close()`.
4. `Schematic.save()` with the D3 write set, the D4 failure policy, and `overwrite`. `project.save()` as the umbrella. Remove the electrical check, ZIP, and lock check from save.
5. `on_close` and `Schematic.revert()`. Remove the history retry.
6. `project.backup()`.
7. Trim `project.save_as()`.
8. `update_from_library`. Remove restore intents and the pin-type prediction.
9. Remove `ensure_writes_allowed()` and `write_is_permitted()`.
10. `Netlist.__eq__`.
11. `SymbolLibrary` and `LibraryTable`: `validate()`, flag-based `is_modified`, fingerprint, `overwrite`, and `revert()`.
12. Move tests, update the usage pages (`projects.md`, `schematics.md`, `netlist.md`, `symbol-libraries.md`, `tables.md`), and update `CHANGELOG.md`.

Each step keeps the suite green and records its verification in the commit body.
