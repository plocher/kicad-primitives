# ADR 0010: Load and save, locks, and three levels

Date: 2026-11-11

Status: Proposed. The owner agreed the direction in the grilling session on [#78](https://github.com/plocher/kicad-primitives/issues/78) on 2026-11-11. Not accepted.

Related: [ADR 0008](0008-artifact-objects-and-explicit-persistence.md), [ADR 0009](0009-primitives-not-an-executive.md), [ADR 0011](0011-schematic-document-model-save-and-revert.md), [ADR 0012](0012-future-mcp-tool-surface.md), [#79](https://github.com/plocher/kicad-primitives/issues/79) (sheet model and per-instance data).

Evidence:

- [eeschema schematic file handling research](../review/eeschema-schematic-file-handling-2026-10-30.md).
- KiCad source that the session read in a local checkout of the KiCad source mirror at `10.99.0-5580-gd4f4523276` (master). The session did not compare tag `10.0.7`. A research ticket checks the lock facts against `10.0.7` before any lock code is written.

Names of calls in this ADR are illustrative. The word pairs load and save, open and close, and the name `begin` are part of the decision.

## Problem

Ticket #78 asked for four things: the `KiCad` root scope, library ownership, library and item revert, and a rule for closing an artifact that a project also holds.

The grilling found a deeper problem under those questions.

- The package says `open` and `close` for objects that hold no resource. An `open` reads a file into memory. No file handle stays open.
- `close` had no job of its own. Earlier ADRs gave it jobs: save on close, an `on_close` choice, and removal from a registry.
- Each of those jobs made a new question. What does a second open return? Who closes a shared object? What does close do on one part of a project? What are the defaults, and who can change them?
- `save()` does more than a write. It checks validity, checks for a conflict, makes a backup for a symbol library, and retries after a short-lived error. Those are choices hidden in a primitive.
- The discussions mixed three kinds of rule: what one file operation does, what KiCad requires, and what is convenient.

A first pass in the same session kept `open` and `close`. It produced eleven locks about modes, close behavior, and defaults. Each lock needed an exception. The owner stopped that pass and changed the frame.

## Constraints and requirements

- Keep ADR 0002 functional ownership, the ADR 0003 write contract, and ADR 0006 release scope.
- Keep the ADR 0009 primitive test: one operation does one job and calls no other public capability as a hidden step.
- Follow KiCad behavior and vocabulary. Record each deliberate deviation.
- The package is a set of primitives, not an executive. A primitive can do damage when a client uses it wrongly. Protection is a choice above the primitive.
- A test or a converter must work on a machine with no KiCad configuration, from explicit inputs.
- Libraries are costly to load. Load them on demand.
- Pre-1.0: remove and rename misleading interfaces. Do not keep aliases.

## Definition of success

- A unit test can state what each level-0 call does in one sentence.
- Each protection that leaves a primitive is still available, as a separate call or as a level-2 function.
- A client at level 1 works in a model. It names files only when it wants to.
- Each rule belongs to one level.

## KiCad facts that drive the decision

- KiCad uses two word pairs. `LoadSchematicFile` and `SaveSchematicFile` read and write data. `OpenProjectFiles` and `CloseProject` start and end an editor session, and `OpenProjectFiles` takes the lock (research document, sections 2, 3, 7, and 9).
- One KiCad process has one editor frame per type. `KIWAY::Player` returns the frame that exists (`common/kiway.cpp:401-415`).
- The symbol editor keeps one working buffer per library and makes it on first use (`eeschema/symbol_library_manager.h:419`). It has save and revert. It has no "close this library".
- The schematic editor has no "close this sheet". It saves and closes the whole schematic.
- A standalone editor still loads the settings and the global library tables (`common/single_top.cpp:363-424`).
- KiCad's lock is a sibling file, `~name.ext.lck`, with a JSON record. On master, KiCad also holds an operating-system lock on that file while it runs (`include/lockfile.h`).
- KiCad locks the opened root schematic and the board (`eeschema/files-io.cpp:121`, `pcbnew/files.cpp:321`), and the project file (research document, section 7). The session found no lock call in the symbol editor or the footprint editor code.

## Candidates

### A. Scopes that own artifacts

This is the starting point of #78 and of ADR 0011 D5.
`KiCad` and `Project` are scopes. A scope owns the artifacts that it opens, and it closes them. A registry returns one object per file.

Pros:

- It follows the owner direction that #78 recorded before the session.
- It changes little shipped code.

Cons:

- "Owner" is not a KiCad idea.
- It needs a rule for an artifact with no owner and a rule for a close on an owned artifact.
- It needs a rule for a library in two tables and a rule for ownership that moves when a library joins a table.
- The owner said that the result felt foreign to KiCad.

### B. One copy, modes, and a close choice on every open

This is the first pass of the session. Its main rules were:

- One working copy per file per process. A later open returns it.
- Every open has a mode. Read-only is the default. A read-write project open takes KiCad's locks.
- Every open has an `on_close` choice of discard, raise, or save. `set_defaults()` sets the defaults.
- A library opened with a table is under the object that the table came from.

Pros:

- Writes are explicit.
- A read-only tool is safe by default.
- A dry run in memory works.

Cons:

- Every rule attaches to `close`, and `close` releases nothing.
- Each rule needed another rule: the mode of the first open, use after close, and a double open with one close.
- The opens that the package makes itself needed defaults, and the defaults needed a setter.
- The protections stay inside the primitives.
- The package starts to act as an executive.

### C. Load and save for data, open and close for locks, three levels

Data operations are load and save. They hold nothing.
Open and close exist only where a lock is held.
Every load makes a new model.
`save()` writes and does nothing else.
The checks are separate calls.
Three levels separate the building blocks, the KiCad rules, and the convenience choices.

Pros:

- Each call does one job.
- The hidden state goes away: no registry, no shared copy, no close on a model.
- The words match KiCad.
- Tests become simple. Load, change, save a copy elsewhere, and compare the files. Or load twice, change one model, and compare the two.
- Level 1 can focus on the in-memory model.

Cons:

- It reworks code that shipped under ADR 0008, ADR 0009, and ADR 0011.
- A bare `save()` can write over a file that changed on disk. See [Known cost](#known-cost-a-bare-save-can-overwrite).
- A client that wants protection must ask for it.

### Evaluation

A and B both try to give `close` a meaning for objects that hold nothing. A does it with ownership. B does it with modes and defaults. Each needs a growing set of rules, and the rules are not KiCad's.

C removes the cause. Most of the questions in A and B cannot be asked in C. The protections of B remain possible as level-2 functions, so no capability is lost.

The cost of C is rework and one weaker default. The package is pre-1.0 and has no released consumer (ADR 0005), so the rework is affordable now and is not affordable later.

Choose C.

## Decision

### D1. Vocabulary

- **Load** reads one file into a model. **Save** writes a model to a file. Nothing is held between them.
- **Open** takes a lock. **Close** releases it. They do nothing else.
- A model has no close. When a client stops using a model, nothing happens.
- Unsaved edits in a model that a client drops are gone. This is the only close behavior at levels 0 and 1.

### D2. Three levels

- **Level 0: building blocks.** One file and one model. Each call does one job. Nothing here knows about another file.
- **Level 1: required to be like KiCad.** It creates and manages the in-memory model that a client works in. The model is the focus. Level 0 hides the on-disk structures below it. The rules at this level are facts about KiCad, not choices.
- **Level 2: convenience choices.** Functions built only from the levels below. A client can disagree with any of them and write its own.

This keeps the three layers that the owner locked on #78 and sharpens their meanings.

### D3. Level 0: building blocks

1. **Load one file** into a model of that file: the settings, a library table, a library, a sheet file, a project file, and later a board. Each load takes an explicit path. Every load makes a new, independent model.
2. **Change** the model in memory with the edit operations that exist today.
3. **Save** writes the file. It checks nothing. It replaces the file whole, so a reader sees the old file or the new file. Saving to another path is part of this block.
4. **Separate calls** answer "has the file changed on disk since the load?", check that the model is valid to write, and make the backup.
5. **Lock and unlock** (`open`, `close`). `open` fails when another session holds the lock. No save consults a lock.
6. **Table edits with explicit values:** `add_entry(nickname, uri)`. URI-to-path and path-to-URI are pure functions of the values given.
7. **Find the configuration directory**, as its own call.

Levels 0 and 1 have no read-only mode. A tool that does not call `save()` writes nothing.
A dry run is a load, changes in memory, and no save.

A sheet file has a level-0 load because it is a file. It has no open and no close.

### D4. Level 1: the model

- **The root.** `KiCad.begin(settings, symbol_table, footprint_table)` joins parts that are already loaded. It reads nothing. A test harness passes its own parts. `KiCad.load()` is built on `begin`: it finds the configuration directory, loads the three files, and joins them.
- **A project** is an association of files: the project file, the sheet files, the tables, the board, and the settings for fabrication. `Project.load(ref)` finds the project file, walks the sheet hierarchy, loads each sheet once, and joins them. The project tables go over the global tables. The reference rule of ADR 0011 D2 stays.
- **Parts are single inside one model.** A part reached twice is the same object. Two loads of the same project are two models.
- **Libraries are reached through the model.** By nickname, a library loads on first use. Listing nicknames loads no library. By path, a library joins the same collection, marked as not in a table. The table file does not change.
- **Adding a library to a table** is `table.add(lib, nickname)` on an explicit table. The URI takes the form that fits that table. Like KiCad, the nickname defaults to the file stem.
- **The project lock.** `open` takes the locks that KiCad takes for a project session. `close` releases them. This uses the level-0 lock block.
- **Project save** writes the files that changed, children before parents. The ADR 0011 D3 deviation from KiCad stays.
- **Settings are plain data** read from the configuration, such as `auto_backup`.
- **Netlist, ERC, and SVG** stay with KiCad for now. A netlist made from the model is a future aim, because the model already holds the data. ERC and DRC stay with KiCad. ADR 0012 section 9 governs each move.

A client that works at level 1 reaches sheets as parts of the project. It does not load a sheet file itself.

### D5. Level 2: convenience choices

These are candidates. The owner keeps or drops each one later.

- `save_safely()`: validity check, backup, save, and retry.
- `save_if_safe()`: lock, check for a change on disk, save, and unlock.
- A wrapper that refuses a save unless the project is open.
- "Read-write if possible, else read-only."
- The first-pass session behavior as one optional wrapper: read-only by default, a close choice of discard, raise, or save, and `set_defaults()`.

Dry-run reporting stays with the client.

ADR 0011 D10 said that no recipes module ships until a recipe is needed. `save_safely()` and `save_if_safe()` are the first ones that the owner named.

### D6. What this removes

- The process-wide registry of open objects, and "one copy per file per process".
- `close()`, `discard()`, and `with` support on models, and the errors for use after close.
- The `on_close` choice at levels 0 and 1.
- The checks inside `save()`: the conflict check and its `overwrite` argument, the validity check, the symbol `.bak` copy, and the retry. They become the separate calls of D3 and the functions of D5.
- The library open that takes a nickname-or-path string, and its hidden lookup in the default tables.
- "Library ownership follows type" and "one `KiCad` object per config home per process".
- The special error for a close on one sheet file of a project.

### D7. Deferred work and research

- **Research:** what KiCad `10.0.7` does with its lock files. The lock block and the project lock wait for it.
- **Deferred:** a lock of the package's own for libraries. It needs a reliable design first.
- **Deferred:** revert. At level 0 it is a new load. Inside a level-1 model, the earlier rule on #78 needs a second look.

## Known cost: a bare save can overwrite

ADR 0009 promised "no silent overwrite". Every save refused when the file on disk was not the file that the artifact read.

Under this ADR, a bare `save()` writes over the file on disk. That includes a change that KiCad's editor or a sync tool made after the load. A package lock does not cover those writers.

The promise now holds only when the client asks for it: with the check of D3, with the lock, or with a level-2 function. Two models of one file are safe only on the same condition.

The owner accepts this cost. The other ADR 0009 write promises stay: no partial file, no stray KiCad files, and no in-memory original.

## Not decided here

- The names of the calls.
- How a project gets its root: as an argument, or loaded behind `Project.load(ref)`.
- What a save of several files reports when one file fails. This is the part of ADR 0011 D4 that is not the conflict class or the retry.
- Whether a `with` block marks the span of a lock.
- Which level-2 functions ship, and in which order.

## Relationship to earlier ADRs

- **ADR 0008.**
  - Keeps: artifact-owned objects, edits in memory, explicit save, the `set_attribute` meaning, and save to a new path.
  - Replaces: the independent-artifact lifecycle of `close()`, `discard()`, and `with`, and the 2026-10-29 amendment "close persists pending changes".
- **ADR 0009.**
  - Keeps: the primitive test, policy above primitives, the write promises other than "no silent overwrite", and the two-level footprint library with immediate directory operations.
  - Replaces: the lifecycle "open, read, modify, validate, write, close", which becomes load, read, modify, and save. `save()` no longer runs `validate()` first.
  - Replaces: "no silent overwrite" inside save and the `overwrite=True` argument.
  - Withdraws: the process-wide open registry.
  - Amends: "peer lock is a query, not a write guard". The queries stay, and no write consults a lock. The package can now take and release a lock.
  - Replaces: the `on_close` choice of `FootprintLibrary`.
- **ADR 0011.**
  - Keeps: the nouns of D1, the project reference of D2, the write set of D3, `backup()` of D7, `save_as()` of D8, and the netlist equality of D9.
  - Replaces: the conflict class and the retry of D4, which move to level 2.
  - Replaces: D5, `on_close`, and who ends things.
  - Replaces: the `discard()` half of D6. Revert is deferred. The fingerprint stays as the record for the "changed on disk" check.
  - Renames: the layer-0 `SheetFile.open(path)` of D1 becomes a load.
  - Meets: the condition of D10 for the first level-2 functions.
- **ADR 0012.**
  - Section 3 stays agent-surface policy. Its sentence "the library rule does not change" needs new wording, because the package gains lock and unlock.
  - Section 2 maps onto load, change, validate, and save without a change of intent.
- **Ticket #78.** This ADR replaces the owner locks in its comments about scopes that close, library ownership, and the save and revert table. It answers the open point there about the nickname: it defaults to the file stem.

## Consequences and implementation order

This ADR authorizes no code. Implementation tickets follow acceptance.

On acceptance:

- Update `AGENTS.md` and `CONTEXT.md`.
- Update the index and mark the replaced parts of ADR 0008, ADR 0009, ADR 0011, and ADR 0012.
- Close #78 and add its line to the map.

A possible order for the implementation tickets:

1. Split save at level 0: the bare save, the "changed on disk" check, the validity check, and the backup.
2. Remove the registry, `close()`, `discard()`, `with`, and `on_close` from models. Rename the file opens to loads.
3. Add the lock block, after the research.
4. Add the root: find the configuration directory, load the settings, `KiCad.begin`, and `KiCad.load`.
5. Add the library collection on the model, and `table.add`.
6. Move `Project` to `load`, with `open` and `close` as its lock.
7. Add the first level-2 functions.

ADR 0006 scope does not change. The shipped surfaces of Projects, Schematics, Symbol libraries, Footprint libraries, and Tables change, so their usage pages change with each ticket.

## Glossary changes (CONTEXT.md, on acceptance)

Add:

- **Model**: the in-memory content of one file, or of an association of files.
- **Load**: read one file into a new model.
- **Level 0 / Level 1 / Level 2**: building blocks / required to be like KiCad / convenience choices.

Change:

- **Save**: write a model to a file. It checks nothing.
- **Open**: take a lock.
- **Close**: release a lock.

Remove:

- **Discard**, and the `on_close` sentence under Close.
- **Scope**, as an owner of artifacts.
