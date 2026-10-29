# ADR 0009: Primitives, not an executive

Date: 2026-10-29

Status: Proposed. Awaiting owner review.

Related: [ADR 0003](0003-source-preserving-parser-and-writes.md), [ADR 0008](0008-artifact-objects-and-explicit-persistence.md), footprint libraries [#39](https://github.com/plocher/kicad-primitives/issues/39).

## Problem

The package must be a small set of simple KiCad primitives.
A client must be able to build an executive from these primitives.
The primitives must not be that executive.

Some operations already act as an executive.
One call runs several capabilities in a fixed sequence that the package chose.
For example, `Project.save()` checks locks, runs `kicad-cli` twice, compares connectivity, writes files, builds a ZIP, publishes it, and prunes old ZIPs.
A client cannot write without also verifying and archiving.
A client cannot verify or archive without writing.
`Project.close()` inherits that whole sequence.
Design proposals for #39 continued the drift: default discovery roots, URI rewriting inside a registration helper, and a close step that retries history.

ADR 0008 already says that the library owns KiCad invariants and the client owns workflow.
Later work read "persistence safeguards" too broadly. This ADR draws the line.

## Constraints and requirements

- Keep ADR 0002 functional ownership and ADR 0006 release scope.
- Keep ADR 0003 byte preservation. An edit changes only the nodes it means to change.
- Keep the ADR 0008 artifact-object model and the 2026-10-29 close amendment.
- A primitive must be cheap to understand from its name and signature.
- A client must be able to rebuild every current composite behavior from public primitives.
- Do not lose data-integrity protection that only the library can give.

## Definition of success

- Each public operation passes the primitive test below, or the ADR names it as a deliberate exception.
- Today's composite behaviors are possible as short client sequences of public primitives.
- Usage pages describe each operation as one capability.

## The primitive test

A public operation is a primitive when all of these are true:

1. It does one thing to one artifact, or it reads one artifact and returns one result.
2. It runs an external tool only when running that tool is its stated purpose (`erc()`, `netlist()`, `export_svgs()`).
3. It does not call other public capabilities as hidden steps.
4. It makes no workflow decision for the client: what to check, what to keep, where to look, or what to do next.

Two kinds of protection stay inside primitives, because a client cannot provide them safely:

- **File integrity:** byte preservation, source-conflict and link checks, permission checks, staged writes with atomic replacement, refusal to write an unsupported format.
- **Native file behavior that is part of the KiCad operation itself:** for example, the `.bak` file that KiCad's symbol-library save writes.

Policy stays outside primitives and is offered as separate primitives:
connectivity verification, history snapshots and retention, ERC, library discovery roots, and URI style.

## Candidates

### A. Keep the composite operations

Pros: the existing code and tests remain. Callers get verification and history without asking.
Cons: clients cannot pick their own sequence. Simple writes need KiCad. Close can run KiCad. Each new artifact copies the pattern. The package grows into the executive the owner does not want.

### B. Strict primitives, with no integrity checks inside

Pros: the smallest operations.
Cons: every client must reimplement conflict, link, and atomic-write checks. One careless client can corrupt a design. This moves risk to the place that is least able to handle it.

### C. Primitives with integrity inside, policy as separate primitives

Pros: matches the owner's goal statement and ADR 0008. Integrity stays in one place. Clients compose verification, history, and checks in any order. KiCad runs only when a client asks for an operation that needs it.
Cons: some current behavior must be split. Clients that want today's full save must call three primitives. ADR 0003's "verify on edit" becomes a test contract plus a client choice, not a hidden runtime step.

## Proposed decision

Choose C.

### Consequences for existing operations

Simple primitives that stay as they are:

- All read accessors, `to_bytes()`, `is_modified`, `is_locked`, `lock_file`, `schematic_files()`, `text_variables`.
- Symbol edits: attributes, pins, bodies, rectangles, texts, create, rename, delete, copy, `resolve()`.
- Table reads and edits: `libraries()`, `resolve()`, `table()`, `entries`, `add_entry`, `rename`, `set_uri`, `delete`.
- `PlacedSymbol.set_attribute` and `delete_attribute`.
- `SymbolLibrary.save()` and `save_as()`, `LibraryTable.save()` and `save_as()`: write with integrity checks only. The symbol `.bak` file is native save behavior.
- `discard()`, and `close()` per ADR 0008 as amended. Close calls only that artifact's own `save()`.
- `Project.erc()`, `Project.netlist()`, `Project.export_svgs()`, `SymbolLibrary.export_svgs()`, `export_netlist()`, `Netlist.open()`, `connectivity_sets()`. Running KiCad is their stated purpose. Staging pending content is how they do that one job.

Composite operations to split (follow-up ticket, owner grilling first):

1. **`Project.save()` and `Schematic.save()`.** Split into:
   - a write primitive: peer-lock guard, integrity checks, staged writes, no KiCad, no ZIP;
   - connectivity verification, which a client builds from `netlist()` before and after edits plus `connectivity_sets()`, or a thin `verify_connectivity(baseline)` primitive if that is worth it;
   - `project.snapshot_history()` for ZIP publication and retention.
2. **`Project.close()`.** After the split, a dirty close calls only the write primitive. The "unpublished history" retry is removed.
3. **`Project.save_as()`.** Keep the operation that KiCad's own Save As performs: copy the project file set and rewrite project identity. Remove the built-in electrical proof and ZIP publication. Clients call them if they want them.
4. **`EmbeddedSymbol.restore_from()`.** The in-memory restore stays a primitive. The deferred "restore intent" that changes later save verification is cross-operation coupling. It moves to the verification primitive's inputs.

Borderline items for the owner to decide:

- **Peer-lock checks inside write primitives.** A write while KiCad holds the file can lose the user's work, so this proposal treats the check as integrity. `ensure_writes_allowed(dry_run=..., inside_kicad=...)` is a policy helper. It could become a plain query.
- **Process-wide open registry (#39).** The owner asked for it. It keeps one live object per file and makes no workflow decision. It passes the test.

### Consequences for #39

- `FootprintLibrary.save()` checks every file, stages every write, then commits. It does not verify or archive.
- `LibraryTables.find_libraries()` requires explicit roots.
- `LibraryTables.portable_uri(path)` returns the `${VAR}` form of a path. Clients register with `add_entry(nickname, uri)`. There is no `add_library` helper that chooses a nickname or URI style.

### Relationship to earlier ADRs

- This ADR amends ADR 0003. "Connectivity-preserving edits verify unchanged connectivity" becomes a functional-test contract and an available client primitive. It is no longer a hidden step inside save.
- This ADR clarifies ADR 0008. "Persistence safeguards" means file integrity, not verification or history policy.
- ADR 0006 release scope does not change. Verification, ERC, and history remain capabilities. Only their packaging changes.

## Rollout

1. The owner accepts, changes, or rejects this ADR.
2. #39 follows it from the start.
3. A separate ticket splits the existing composites, with owner grilling on each split. Tests move with the behavior: verification tests become tests of the verification primitive and of client sequences.
