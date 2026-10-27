# ADR 0008: Artifact objects and explicit persistence

Date: 2026-10-26

Status: Architectural direction and independent-artifact lifecycle accepted by the owner on 2026-10-26.

Related work: [Schematic symbol attribute editing](https://github.com/plocher/kicad-primitives/issues/36).
Alignment: [Editable library and table nouns with explicit lifecycle](https://github.com/plocher/kicad-primitives/issues/54).

## Problem

The package regularizes how client applications inspect and manipulate KiCad artifacts.
It does not replace those applications.

A proposed project-level attribute setter collected target selection, batch validation, dry-run behavior, and persistence policy into one operation.
This turned a focused editing capability into an application workflow.
The owner rejected that direction and required an artifact-object pattern throughout the package.

ADR 0002 already separates functional ownership from consumer product logic.
ADR 0006 requires useful functional capabilities, not a Swiss Army knife application.
This decision makes that distinction explicit.

## Constraints and requirements

- Keep the functional areas and ownership in ADR 0002.
- Keep the source-preservation and electrical-correctness contracts in ADR 0003.
- Keep the A/B/C release model in ADR 0006.
- Open an artifact through its appropriate owning context.
- Expose its meaningful objects, content, and relationships for inspection and editing.
- Let clients select targets and sequence operations.
- Keep edits in memory until the client explicitly requests persistence.
- Let clients inspect whether their work changed an artifact or its owned content.
- Support a lifecycle in which clients choose save, save as, or discard, then close.
- Do not silently save on mutation or close.
- Use the locked vocabulary in `CONTEXT.md`.
- Do not retain misleading pre-1.0 interfaces solely for compatibility when there are no external consumers.

These requirements describe the design direction. They do not claim that every lifecycle operation already exists.
Mention of worksheets and other artifacts does not add a new 1.0 proven-core requirement.

## Definition of success

A client can express its own workflow using artifact objects.
It does not need a library-specific batch language or application job runner to edit one object.
The library owns KiCad correctness and source handling.
The client owns why, where, and when to apply the capability and persist the result.

## Candidates and evaluation

### A: Project-level application workflows

Provide methods that select targets, apply changes, report results, preview, and write.

This can shorten one known donor workflow.
It also imports donor selection policy and transaction expectations into the package.
Different clients need different selection and approval logic.
Reject this as the default public editing pattern.

### B: Detached immutable snapshots with document-level edit commands

Expose inspection snapshots and accept object identifiers on editing methods.

This keeps snapshots simple and supports explicit document ownership.
However, clients must switch interfaces between inspection and editing.
Identifiers and target-resolution rules become additional client concerns.
Snapshots remain useful as values, but they are not the default editable-object interface.

### C: Artifact-owned objects with focused operations

Expose editable domain objects through their owning artifact.
For example, a placed symbol sets an attribute while its schematic retains the source and pending changes.

Clients select objects using ordinary application logic.
The library concentrates KiCad structure, validation, and localized edits behind small interfaces.
This requires clear object identity, ownership, and change tracking.
Choose C.

## Decision

Use artifact-owned objects and explicit persistence as the package-wide editing pattern.

### Client responsibilities

Clients choose the artifact, targets, order of operations, and application-specific selection logic.
They decide whether to inspect a preview, request checks, save, save as, or discard.
They own CSV repair policy, approvals, batch reporting, and cross-artifact workflow coordination.

Repeated primitive calls do not require a package batch abstraction.
An application dry-run can use in-memory edits without requesting persistence.
Do not add a dry-run parameter to each mutation by default.

### Library responsibilities

Artifact objects provide access to symbols, geometry, footprints, sheets, relationships, and other supported content.
Object operations inspect and change the relevant content in memory.
Their owning artifacts retain source representation and expose change state.
Project change state must account for changed content owned by that project.

Use current structural information after edits.
Do not expose stale spans or make clients manage parser nodes.
Validate an operation's inputs, identity, and KiCad invariants at its natural object interface.
This does not imply batch-wide transactions across unrelated objects or files.

The editing model separates a request to change content from a request to write files.
Persistence retains applicable format, source-conflict, write-guard, and preservation safeguards.
Client ownership of workflows does not excuse corrupt output or remove ADR 0003 verification requirements.
The placement and timing of electrical verification remain an operation-specific design concern.
Do not assume that every setter must execute KiCad.

### Attribute setter meaning

An object-level `set_attribute(name, value)` establishes the requested attribute value.
It creates a missing attribute, updates a different value, and preserves bytes when the value is already equal.
It rejects ambiguous attribute identity rather than choosing a match.

Reference annotation retains its special identity and instance-consistency requirements.
A generic setter must not perform an unsafe reference change.
Flags remain distinct from named attributes.

### Context and persistence

Projects still own schematic and PCB context.
That ownership does not require every content edit to become a project method.
Independent libraries retain their own artifact context.

Clients need explicit persistence choices and observable pending changes.
The independent-artifact lifecycle below records the owner's accepted definitions.
Project relocation and multi-file backup/failure behavior remain separate bounded work.
Do not infer crash-atomic project saves, a universal session framework, or automatic file-lock acquisition from this lifecycle.

Reports and exports remain library capabilities on the relevant artifacts.
Producing a requested output is an explicit operation, not permission to save pending source edits implicitly.

### Independent-artifact lifecycle clarification
These definitions apply to independent symbol libraries and physical library-table files.
They share meanings, not a generic session, workflow, or transaction base class.

- `save()` explicitly persists current content at the current destination.
- `save_as(path)` explicitly persists one new file and rebinds this artifact only after success.
- `close()` initially errors, even for a clean artifact that has never been edited.
- Successful save/save-as authorizes close only for the current state.
- Later edits invalidate that decision. Exact no-op edits do not.
- Every failed save/save-as invalidates the decision, including a failed clean preflight after a previous success.
- `discard()` is terminal exit without writing. It is not rollback, reload, or a baseline reset for continued use.
- Close and discard invalidate owned editable handles. A later close is idempotent.
- No mutation, close, discard, or finalizer implicitly persists.

Save-as refuses an existing destination, including a symlink or racing file.
It requires existing, non-symlink, writable destination parents and does not create parent directories.
The original bytes and permissions remain unchanged.
Read-only or readable linked sources can be forked because save-as does not overwrite the source.
Independent roots still check source-byte freshness before save-as. Conflicts do not refresh pending state.
Failed persistence retains pending source and the prior path/baseline for inspection or retry.
Save-as for one physical table does not invent a combined layout for same-named global and project files.

### Native single-file symbol backup
KiCad 10.0.1 saves a changed symbol library through `saveLibrary` and `backupFile` before the library write.
The backup replaces the extension: `Foo.kicad_sym` becomes `Foo.bak`, not `Foo.kicad_sym.bak`.
A backup failure aborts the original save. A new destination has no previous file to back up.
Source evidence is pinned to commit `2db9e5a72b7cf1e71bb8dff5257a88d4b41f812f`:
[symbol editor save](https://github.com/KiCad/kicad-source-mirror/blob/2db9e5a72b7cf1e71bb8dff5257a88d4b41f812f/eeschema/symbol_editor/symbol_editor.cpp)
and [backup helper](https://github.com/KiCad/kicad-source-mirror/blob/2db9e5a72b7cf1e71bb8dff5257a88d4b41f812f/eeschema/symbol_editor/symbol_edit_frame.cpp).
No GPL implementation code is copied.

Changed independent symbol-library overwrites follow that `.bak` rule with source-preserving single-file safeguards.
Exact no-op saves need no replacement or backup.
Backups reject links, unwritable destinations, and source/destination collisions.
Prior backup content remains recoverable during a failed original save.
Recovery must not overwrite or delete a concurrent third-party backup version.
These are optimistic bounded safeguards, not a crash-atomic two-file transaction.
Native table saves have no corresponding backup hook. Do not invent a table backup.

### Project ZIP minimum and same-location lifecycle
The owner selected timestamped ZIP snapshots as the pre-1.0 safety minimum in [#55](https://github.com/plocher/kicad-primitives/issues/55).
Project save-as relocation remains the next bounded phase of [#56](https://github.com/plocher/kicad-primitives/issues/56), not an implemented capability yet.
Native Git-backed `.history` interoperability is deferred through research #58, owner grilling #59, and design #60.
ZIP support adds no Git dependency, branching/merge/rollback policy, or autosave scheduler.

`Project.save()` strictly captures the supported internal schematic hierarchy, project JSON, and optional raw PCB companion.
Existing electrical proof, source conflicts, guards, links, formats, and permission safeguards remain mandatory.
Native peer locks use `~<full-original-filename>.lck` for the project, schematic, PCB, and owned child sheets.
Default filesystem persistence checks their actual paths and never infers host ownership from an importable `pcbnew` module.
Explicit host assertions on a guard helper do not become unchecked-save tokens.
No lock acquisition or stale-lock deletion is introduced.
Unchanged source bytes/inodes need no replacement.
Project settings and PCB content remain byte-preserved, without introducing a settings writer or board editor.
Project close/discard follows the accepted terminal lifecycle above.
Document-only saves do not establish a complete Project save decision.
Actual later edits and failed saves revoke it. Frozen outputs and generation checks prevent newer pending state from being silently settled.

Native archive evidence is pinned to KiCad 10.0.1 in #55.
Use `<name>-backups/<name>-YYYY-MM-DD_HHMMSS.zip` with enabled history and the native 100 MiB default budget.
An explicit nonnegative byte budget can use zero for unlimited history.
Do not invent legacy count/day/interval caps or silently read GUI format settings.
The allowlist is `.kicad_pro/.kicad_prl/.kicad_sch/.kicad_sym/.kicad_pcb/.kicad_mod/.kicad_dru/.kicad_wks/.kicad_jobset/.json/.wbk`
and the bare `fp-lib-table`, `sym-lib-table`, and `design-block-lib-table` names.
Hidden trees and actual backup output are excluded. Required owned members must never silently disappear through filtering.

Build and validate the complete ZIP from frozen post-save bytes before original writes.
Publish only after all selected source writes succeed.
Selected document saves archive saved sibling baselines, not their pending unsaved edits.
Keep each explicit snapshot rather than copying native lossy CRC-set deduplication.
Use exclusive recognizable numeric suffixes instead of overwriting same-second archives.
Reject unreadable or unsafe included members rather than claiming a partial archive succeeded.
Prune recognized regular managed archives only after publication, oldest first, always retaining the latest.
An oversized sole latest archive makes the size budget soft.

These are bounded optimistic safeguards, not a crash-atomic Project transaction.
Advance each source baseline only after its file succeeds.
Later source/publication/retention failure can leave earlier files saved but must not authorize close.
A subsequent clean save retries complete history publication.
Usage details and failure limits are in [projects.md](../projects.md).

## Current gaps and consequences

- `SymbolLibrary` owns live Symbol/Body/Pin nouns, declared attribute upsert, source previews, explicit persistence, and the independent lifecycle.
- Resolved inheritance remains immutable inspection data, not an implicit parent-editing target.
- Physical `LibraryTable` artifacts own buffered TableEntry edits. Context resolution sees nested pending source. No `apply` or dry-run aliases remain.
- Project-owned live schematic/placed-symbol objects support attribute edits, selected embedded restore, aggregate change state, and explicit same-location verified saves.
- Project same-location persistence, native-style ZIP snapshots, and terminal discard/close are implemented.
- Project save-as relocation remains pending. Git `.history` interoperability is separately deferred.
- The proposed `Project.set_symbol_attribute(...)` batch workflow is superseded by object-level editing.

Align these areas through bounded implementation milestones with their existing behavioral tests.
Do not build an application framework or rewrite all functional areas in one change.
Usage pages must distinguish implemented operations from this architectural direction.

This clarifies ADRs 0002 and 0006. It does not replace their functional ownership, release bar, or exclusions.
