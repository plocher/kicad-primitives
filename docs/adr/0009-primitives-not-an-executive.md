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

Policy stays outside primitives:
connectivity verification, history snapshots and retention, ERC, library discovery roots, and URI style.
The package still captures recommended sequencing, but in the open, as recipes (see below).

## Candidates

### A. Keep the composite operations

Pros: the existing code and tests remain. Callers get verification and history without asking.
Cons: clients cannot pick their own sequence. Simple writes need KiCad. Close can run KiCad. Each new artifact copies the pattern. The package grows into the executive the owner does not want.

### B. Strict primitives, with no integrity checks inside

Pros: the smallest operations.
Cons: every client must reimplement conflict, link, and atomic-write checks. One careless client can corrupt a design. This moves risk to the place that is least able to handle it.

### C. Primitives with integrity inside, policy in an explicit recipe layer

Pros: matches the owner's goal statement and ADR 0008. Integrity stays in one place. Recommended sequences are visible, tested code that clients can call, copy, or ignore. KiCad runs only when a client asks for an operation that needs it.
Cons: some current behavior must be split. Clients that want today's full save call a recipe or write the sequence. ADR 0003's "verify on edit" becomes a recipe and its tests, not a hidden runtime step.

The objection to composite operations is not that sequencing exists. It is that they hide the sequencing. Prose alone does not fix that: snippets in docs are not run or tested, and each client copies and changes them. Candidate C therefore includes a code layer for policy.

## Proposed decision

Choose C.

### Recipe layer

A module, `kicad_primitives.recipes`, holds short functions that sequence public primitives for a stated purpose.
Example purpose: "check that the circuit did not change, then save".

Rules:

- **One-way dependency.** Recipes call primitives. Primitives never call recipes. A test enforces that recipe modules import only public names, never `_private` modules.
- **No hidden state or decisions.** Each recipe is one readable function. Every policy choice is a parameter or a visible line.
- **Optional.** No primitive requires a recipe. A client with a different policy writes its own sequence from the same primitives.
- **Docs point at code.** Usage pages explain the purpose and order of each recipe and link to it. They do not duplicate it.
- **Tests at the right level.** Primitive tests check one job. Recipe tests check the sequence and its outcome.

### Connectivity verification is a client sequence

The check answers one question: did the circuit stay the same?
A client captures the netlist before editing, edits, captures it again, and compares:

```python
before = project.netlist()        # pending equals saved at this point
# ... edits ...
after = project.netlist()
unchanged = connectivity_sets(before) == connectivity_sets(after)
```

All of these primitives exist today. No baseline-netlist primitive is added. Capturing "before" at the right time is the client's job.

The package does not predict or excuse expected electrical changes.
An edit that changes pin types, net names, or connections changes the circuit, and the comparison reports that.
The set of acceptable changes is large and specific to each use case. Only the client can decide which differences it accepts.

### Artifact lifecycle

Two client camps drive the package.
Read-only tools (jBOM, kproj) open a project and produce derived artifacts.
Domain editors (schematic, PCB, symbol, footprint, later worksheets and others) change a project.

Every artifact has one lifecycle: **open, read, modify, validate, write, close**.
The read-only flow is the same lifecycle with modify, validate, and write omitted.
There is no separate read-only type and no read-view versus editor split.
A clean close is a no-op for both camps (ADR 0008 as amended).

Each step is a public primitive:

- `validate()` checks that in-memory content is well formed, matches its writable format, and can be written to its destination. It raises with specifics. It does not run KiCad or compare netlists. A client can validate without writing, which is what a dry run needs.
- `save()` writes pending bytes. It runs `validate()` first, because an invalid artifact must not reach disk. It does nothing else.
- Domain editors contribute only their content: pending bytes per file.

### One file writer

One private module replaces per-artifact save code.
It takes a set of (path, old bytes, new bytes), where no old bytes means create and no new bytes means delete.
It checks each file, stages every write to a same-directory temporary file, renames in order, and deletes last.
Temporary names never end in a KiCad extension, so KiCad cannot load them.
This is the ordinary rule for replacing files safely, not policy. The existing single-file save is the one-file case of it.

After staging, only a concurrent writer or a system failure can stop the commit.
Each rename is atomic, so every file is either old or new, never partial.
The error names the files that did not commit, baselines advance only for committed files, and `save()` again finishes the rest.
There is no rollback layer. For independent files, such as a `.pretty` library, this is low probability, low impact, and easy to repair.
Multi-file documents that reference each other, such as a schematic hierarchy, are assessed in the composite-split ticket.

### Consequences for existing operations

Simple primitives that stay as they are:

- All read accessors, `to_bytes()`, `is_modified`, `is_locked`, `lock_file`, `schematic_files()`, `text_variables`.
- Symbol edits: attributes, pins, bodies, rectangles, texts, create, rename, delete, copy, `resolve()`.
- Table reads and edits: `libraries()`, `resolve()`, `table()`, `entries`, `add_entry`, `rename`, `set_uri`, `delete`.
- `PlacedSymbol.set_attribute` and `delete_attribute`.
- `SymbolLibrary.save()` and `save_as()`, `LibraryTable.save()` and `save_as()`: write with integrity checks only. The symbol `.bak` file is native save behavior. Both gain a public `validate()` and move onto the shared file writer when it exists.
- `discard()`, and `close()` per ADR 0008 as amended. Close calls only that artifact's own `save()`.
- `Project.erc()`, `Project.netlist()`, `Project.export_svgs()`, `SymbolLibrary.export_svgs()`, `export_netlist()`, `Netlist.open()`, `connectivity_sets()`. Running KiCad is their stated purpose. Staging pending content is how they do that one job.

Composite operations to split (follow-up ticket, owner grilling first). Each removed bundle becomes a named recipe:

1. **`Project.save()` and `Schematic.save()`.** Split into:
   - `validate()` and a write primitive on the shared file writer: peer-lock guard, integrity checks, staged writes, no KiCad, no ZIP;
   - `project.snapshot_history()` for ZIP publication and retention;
   - a recipe for the old behavior: capture netlist before edits, compare after, write, snapshot.
2. **`Project.close()`.** After the split, a dirty close calls only the write primitive. The "unpublished history" retry is removed.
3. **`Project.save_as()`.** Keep the operation that KiCad's own Save As performs: copy the project file set and rewrite project identity. Remove the built-in electrical proof and ZIP publication. A recipe can add them.
4. **`EmbeddedSymbol.restore_from()`.** The in-memory restore stays a primitive. Remove the deferred "restore intent" and the predicted pin-type signature that change later save verification. A restore that changes pin types changes the circuit. A client that compares netlists sees that difference and decides.

Borderline items for the owner to decide:

- **Peer-lock checks inside write primitives.** A write while KiCad holds the file can lose the user's work, so this proposal treats the check as integrity. `ensure_writes_allowed(dry_run=..., inside_kicad=...)` is a policy helper. It could become a plain query.
- **Process-wide open registry (#39).** The owner asked for it. It keeps one live object per file and makes no workflow decision. It passes the test.

### Consequences for #39

- `FootprintLibrary` follows the lifecycle above. It adds the shared file writer, contributes only its pending bytes per file, and has a public `validate()`. Its `save()` does not verify or archive.
- `LibraryTables.find_libraries()` requires explicit roots.
- `LibraryTables.portable_uri(path)` returns the `${VAR}` form of a path. Clients register with `add_entry(nickname, uri)`. There is no `add_library` helper that chooses a nickname or URI style.

### Relationship to earlier ADRs

- This ADR amends ADR 0003. "Connectivity-preserving edits verify unchanged connectivity" becomes a recipe, its tests, and a client choice. It is no longer a hidden step inside save. "Intentional electrical edits verify their requested changes" is withdrawn: the package reports differences and does not judge them.
- This ADR clarifies ADR 0008. "Persistence safeguards" means file integrity, not verification or history policy.
- ADR 0006 release scope does not change. Verification, ERC, and history remain capabilities. Only their packaging changes.

## Rollout

1. The owner accepts, changes, or rejects this ADR.
2. #39 follows it from the start.
3. A separate ticket splits the existing composites, with owner grilling on each split. Each split adds its recipe. Tests move with the behavior: save-verification tests become recipe tests.
