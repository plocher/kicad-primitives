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
- `save()` writes the artifact's pending bytes (`to_bytes()`). It runs `validate()` first, because an invalid artifact must not reach disk. It does nothing else.
- `is_modified` is a flag. Each setter sets it after a real change; an equal-value set is a no-op and leaves it alone. The artifact does not keep a copy of the original bytes to compare against.

### Source fingerprint and the single-file writer

`open()` captures a fingerprint of the file it read (mtime, size, and content hash; the mix is an implementation detail).
The artifact holds it privately. The caller never sees it.
At write time the artifact passes the fingerprint to the private writer, which refuses when the file on disk no longer matches.
After a successful write the artifact refreshes the fingerprint from the file it wrote.
A native backup such as the symbol `.bak` copies the file on disk before replacement. It needs no in-memory original.

The writer stages to a same-directory temporary file whose name never ends in a KiCad extension, flushes, then renames atomically.
The existing single-file save already does this. It becomes the shared writer for every single-file artifact.
A multi-file writer is not needed until a document set that references itself, such as a schematic hierarchy, is split out of `Project.save()`. That is assessed in the composite-split ticket.

### Footprint libraries are two levels

A `.pretty` library is a directory of independent `.kicad_mod` files, not one file.
The model follows KiCad's footprint library editor: a cached, filterable table of contents on one side, one editor per opened footprint, edit marks, and a "save all?" decision at quit.

- `FootprintLibrary` is the directory. Opening it parses every file once into `summaries`: immutable values with name, description, tags, attributes, pad counts, and path. Clients filter and sort them as plain data without opening anything. `library.refresh()` rescans the directory and re-parses changed files. Nothing refreshes by itself, as with KiCad's refresh button, so tooling that runs alongside KiCad or other tools calls `refresh()` when it wants a current view.
- `library.footprint(name)` opens one live `Footprint` on demand and returns the same object while it is open. A live footprint holds its own open-time fingerprint; `refresh()` does not touch it, and a save over a file that changed underneath is still refused.
- `Footprint` is one file with the full lifecycle: open, read, modify, validate, write, close. `footprint.is_modified` is its edit mark. `library.is_modified` is true when any open footprint is modified. Save clears the marks.
- `create`, `copy`, `delete(name)`, and `rename(old, new)` are directory operations and take effect at once. They are not content edits. Rename follows KiCad: write under the new name, update the internal name and a Value that equalled the old name, delete the old file. Delete invalidates an open footprint handle; rename rebinds its path.
- The library has nothing of its own to write. Its close is a decision about its open footprints, chosen once at open: `FootprintLibrary.open(path, on_close="save")`. `save` (default, the owner's choice) saves every modified open footprint, then closes all of them, like "quit, save all" and like dirty close on every other artifact. `discard` throws open edits away. `raise` refuses while any footprint is modified and names them, so the client decides per footprint. A library `with` block applies the flag on normal exit and discards on an exception.

### Consequences for existing operations

Simple primitives that stay as they are:

- All read accessors, `to_bytes()`, `is_modified`, `is_locked`, `lock_file`, `schematic_files()`, `text_variables`.
- Symbol edits: attributes, pins, bodies, rectangles, texts, create, rename, delete, copy, `resolve()`.
- Table reads and edits: `libraries()`, `resolve()`, `table()`, `entries`, `add_entry`, `rename`, `set_uri`, `delete`.
- `PlacedSymbol.set_attribute` and `delete_attribute`.
- `SymbolLibrary.save()` and `save_as()`, `LibraryTable.save()` and `save_as()`: write with integrity checks only. The symbol `.bak` file is native save behavior. Both gain a public `validate()`, a flag-based `is_modified`, and the open-captured fingerprint in place of a stored byte copy.
- `discard()`, and `close()` per ADR 0008 as amended. Close calls only that artifact's own `save()`.
- `Project.erc()`, `Project.netlist()`, `Project.export_svgs()`, `SymbolLibrary.export_svgs()`, `export_netlist()`, `Netlist.open()`, `connectivity_sets()`. Running KiCad is their stated purpose. Staging pending content is how they do that one job.

Composite operations to split (follow-up ticket, owner grilling first). Each removed bundle becomes a named recipe:

1. **`Project.save()` and `Schematic.save()`.** Split into:
   - `validate()` and a write primitive: peer-lock guard, integrity checks, staged writes, no KiCad, no ZIP. Whether a hierarchy needs a multi-file writer is decided here;
   - `project.snapshot_history()` for ZIP publication and retention;
   - a recipe for the old behavior: capture netlist before edits, compare after, write, snapshot.
2. **`Project.close()`.** After the split, a dirty close calls only the write primitive. The "unpublished history" retry is removed.
3. **`Project.save_as()`.** Keep the operation that KiCad's own Save As performs: copy the project file set and rewrite project identity. Remove the built-in electrical proof and ZIP publication. A recipe can add them.
4. **`EmbeddedSymbol.restore_from()`.** The in-memory restore stays a primitive. Remove the deferred "restore intent" and the predicted pin-type signature that change later save verification. A restore that changes pin types changes the circuit. A client that compares netlists sees that difference and decides.

Borderline items for the owner to decide:

- **Peer-lock checks inside write primitives.** A write while KiCad holds the file can lose the user's work, so this proposal treats the check as integrity. `ensure_writes_allowed(dry_run=..., inside_kicad=...)` is a policy helper. It could become a plain query.
- **Process-wide open registry (#39).** The owner asked for it. It keeps one live object per file and makes no workflow decision. It passes the test.

### Library-item rename and project references (follow-up)

In KiCad 10.0.1, renaming a footprint in the editor touches only the library file.
Boards keep their own copy under the old `Lib:Name`, and a later "update from library" fails with not found.
Renaming a library nickname in the table preferences prompts to update open documents.

Three primitives cover this, and a recipe chains them:

1. Rename the item in the library (#39 for footprints; symbols already have `rename_symbol`).
2. Find every placement that references `Lib:Old` across a project's schematics and board (schematic side partly exists; board side belongs with #34).
3. Rewrite those references to `Lib:New` on each placement (a `lib_id` setter on placed symbols; placed footprints with #34).

The recipe "rename library item and repoint a project" is the first named example for the recipes layer.
The same shape applies to library nickname renames (`TableEntry.rename()` exists; the repoint primitive is the same follow-up).

### Consequences for #39

- `FootprintLibrary` and `Footprint` follow the two-level model above: cached `summaries` with explicit `refresh()`, on-demand live footprints, edit marks, and the `on_close` flag with `save` as default. `Footprint` has a public `validate()` and writes one file through the shared single-file writer. Nothing verifies or archives.
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
