# ADR 0008: Artifact objects and explicit persistence

Date: 2026-10-26

Status: Architectural direction accepted by the owner on 2026-10-26. Detailed lifecycle interfaces remain to be designed.

Related work: [Schematic symbol attribute editing](https://github.com/plocher/kicad-primitives/issues/36).

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
Exact names, save-as relocation rules, close/discard behavior, and multi-file failure handling require bounded designs before implementation.
Do not infer crash-atomic project saves, a universal session framework, or automatic file-lock acquisition from this lifecycle.

Reports and exports remain library capabilities on the relevant artifacts.
Producing a requested output is an explicit operation, not permission to save pending source edits implicitly.

## Current gaps and consequences

- `SymbolLibrary` already separates in-memory edits from `save()`, but edits are library commands over immutable symbol snapshots.
- Schematic and placed-symbol objects are currently read-only snapshots.
- `LibraryTables` mutations use `apply` and can write directly. They do not yet follow the pending-edit lifecycle.
- General project change tracking, save-as, discard, and close interfaces are not implemented.
- The proposed `Project.set_symbol_attribute(...)` batch workflow is superseded by object-level editing.

Align these areas through bounded implementation milestones with their existing behavioral tests.
Do not build an application framework or rewrite all functional areas in one change.
Usage pages must distinguish implemented operations from this architectural direction.

This clarifies ADRs 0002 and 0006. It does not replace their functional ownership, release bar, or exclusions.
