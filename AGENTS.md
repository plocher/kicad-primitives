# AGENTS.md

## What this project is

A general Python package for reading, editing and writing KiCad 10 projects and libraries: schematics, PCBs, symbol libraries, footprint libraries, library resolution, and connectivity.

The larger project's aspiration is to replace the need for kicad-cli, KiCad's own incomplete and limited API and to consolidate the KiCad handling that today lives in six of the owner's repos, each with its own parser and its own idea of writing. 

The consolidation is this project's job. The various per-project services become an independent package; none of those repos is blocked on this work. Each becomes a consumer when the package is better than what it has—**migration is decoupled** (see Operating model).

Read `docs/kicad-services-survey-2026-10-12.md` first. It is the founding inventory, not the current decision record. Accepted ADRs record later owner decisions and supersede conflicting survey proposals.

## Package identity (locked)

Canonical record: `docs/PACKAGE_IDENTITY.md`, ADR 0001, and its parser/Python amendment in ADR 0003. Do not invent alternate names in code or docs.

| Field | Value |
| --- | --- |
| Distribution | `kicad-primitives` |
| Import | `kicad_primitives` |
| License | MIT |
| Python | 3.11+ |
| KiCad write/edit target | 10 |
| Format contract | per-file `(version …)` |
| Older formats | read-only when cheap |
| Parser dependency | `circuitdk-lossless-sexpr==0.1.1`, private import `lossless_sexpr` |
| Home | this repo only for shared KiCad I/O |
| Dependency bar | no released donor pin before `1.0.0` on public PyPI (ADR 0005) |
| 1.0 capability bar | ADR 0006 (A/B/C surfaces, proven cores, donor floor; functional tests) |
| Pre-1.0 | informational `0.x` only; no compatibility promise |
| WIP install | `uv venv` + `uv pip install -e .`; optional Test PyPI probes; no `sys.path` |

## Sources, by what they are strongest at (survey section 1 and 2)

| Repo | Take from it | Path |
| --- | --- | --- |
| jBOM | s-expression reading (`sexpdata`), project context and discovery, project variables, lock-file and plugin runtime | `~/Dropbox/KiCad/jBOM` |
| FieldUnit-Subdivision | byte-preserving text editing of `.kicad_sch` and `.kicad_sym` (spans, node edits), the symbol-library model with units, the netlist reader, the netlist connectivity gate, the library overview page | `~/Dropbox/workspace/FieldUnit-Subdivision/tools/kicad_services`, `tools/contract` |
| kproj | the `kicad-cli` locator and facade, exporters | `~/Dropbox/KiCad/kproj` |
| EagleLib2KiCad | library tables with real `${VAR}` resolution from `kicad_common.json` | `~/Dropbox/KiCad/EagleLib2KiCad` |
| kDoctor | footprint read model, ERC/DRC interpretation, nested library tables | `~/Dropbox/KiCad/kDoctor` (same directory as `kdoctor`) |
| Railroad | consumer only: the SPCoast project, its one-off migration scripts under `SPCoast/edits/` and `symbols/edits/`, which are worked examples of bulk edits the package should make routine | `~/Dropbox/KiCad/Railroad` |

KiCad 10 is the target. The format version in the files (`(version 20251024)` today) is the
contract; older versions are supported read-only when possible.

## Scope: public functional areas

### Load and save, locks, and three levels (locked)

Canonical decision: [ADR 0010](docs/adr/0010-load-save-locks-and-three-levels.md). It replaces parts of ADR 0008, ADR 0009, and ADR 0011. Where another line in this file conflicts with it, ADR 0010 wins.
Transition: the code still has the earlier lifecycle (`open`, `close`, `discard`, `on_close`, the registry, and the checks inside `save()`). Implementation tickets move it. New work follows ADR 0010. Do not extend the earlier lifecycle. The usage pages describe the code, so each page changes with its ticket.
Load and save move data and hold nothing. Open and close take and release a lock, and do nothing else.
Every load makes a new, independent model. No registry, no shared copy, and no close on a model. A model that a client drops loses its unsaved edits.
`save()` writes the file and checks nothing. It replaces the file whole. The "changed on disk" check, the validity check, and the backup are separate calls.
Known cost: a bare `save()` can write over a file that changed on disk. "No silent overwrite" holds only when the client uses the check, the lock, or a level-2 function.
Level 0 is building blocks: one file, one model, one job per call. Level 1 is what KiCad requires: it creates and manages the in-memory model. Level 2 is convenience choices built only from the levels below.
A client at level 1 works in a model. If level-1 capabilities are insufficient or undesirable, it uses level-0 capabilities to access files.
A model is a design boundary. It carries its own methods. Its surface separates public from private, and stable from experimental.
Every KiCad file kind has a loader, or a placeholder that raises an explicit not-implemented error (table in ADR 0010 D3).
Level 1: `KiCad.begin(...)` and `Project.begin(...)` join loaded parts and read nothing. `KiCad.load()` and `Project.load(ref)` are built on them. A model joins the root by an explicit add. The worked example in ADR 0010 D4 is the logical placeholder for the conveniences.
Libraries are reached through the model: by nickname on first use, or by path, marked as not in a table. `table.add(lib, nickname)` defaults the nickname to the file stem, like KiCad.
Levels 0 and 1 have no read-only mode and no `on_close`. A dry run is a load, changes in memory, and no save.
No level-2 function ships until one is needed. The ADR 0010 D5 items are thought anchors, not proposals.
Lock code waits for the research on KiCad 10.0.7 lock files (#88). A lock of the package's own for libraries, and revert, are deferred.
Names of calls in ADR 0010 are illustrative, except load and save, open and close, and `begin`.

### Artifact-object library model (locked)

Canonical decision: [ADR 0008](docs/adr/0008-artifact-objects-and-explicit-persistence.md).
This package is a library of KiCad capabilities, not a client application or workflow engine.
Clients load an artifact, select its objects, inspect or change them, inspect pending changes, and choose save or save as.
Expose focused operations on the relevant objects, such as `PlacedSymbol.set_attribute`, rather than project-level target-selection workflows.
Mutations change in-memory content. Only an explicit save writes (ADR 0010).
Clients own selection, iteration, approvals, batch reports, and application dry-run behavior.
The library owns KiCad invariants, source preservation, change tracking, and applicable persistence safeguards.
Project ownership supplies schematic and PCB context. It does not force every edit onto `Project`.
`set_attribute` means create if absent, update if different, and exact no-op if equal. Reject ambiguity.
Reference annotation and flags have their own semantics.
ADR 0010 replaces the ADR 0008 lifecycle of `close()`, `discard()`, and `with`, and the 2026-10-29 close amendment. `SymbolLibrary`, physical `LibraryTable`, `SheetFile`, and `Footprint` keep that lifecycle in code until the implementation tickets land.
Single-file save-as refuses existing or unsafe destinations and rebinds only after success.
KiCad's symbol-library save writes a native `Foo.bak` from the bytes on disk. Under ADR 0010 that backup is a separate call. Table saves do not invent a backup.
`Project` save, backup, and save-as follow ADR 0011 as amended by ADR 0010. Save writes files only; it runs no KiCad, makes no ZIP, and checks no lock.
`is_locked` and `lock_file` are queries; no write consults them. Lock and unlock are a level-0 block under ADR 0010. Do not write lock code before the research (#88). Do not delete another session's lock.
Git-backed `.history` interoperability remains deferred research #58, owner grilling #59, and design #60.
Do not add a Git dependency, autosave scheduler, branching/merge/rollback policy, or a universal session/transaction framework.
Existing gaps are debt to fix, not precedent. No compatibility aliases for misleading pre-1.0 names without an actual consumer need.

### Primitives, not an executive (locked)

Canonical decision: [ADR 0009](docs/adr/0009-primitives-not-an-executive.md).
A public operation does one job to one artifact, runs KiCad only when that is its stated purpose, calls no other public capability as a hidden step, and makes no workflow decision for the client.
File-integrity promises inside primitives: no partial file, no stray KiCad files, and no in-memory original. ADR 0010 moves "no silent overwrite" and the native backup out of `save()` into separate calls.
Policy (connectivity verification, backup, ERC, discovery roots, URI style, peer-lock guards) lives above primitives, in client code or in plain recipe functions built only from public primitives. Primitives never call recipes. ADR 0011 D10: no recipes module ships until a recipe is needed.
Every artifact has one sequence: load, read, modify, save (ADR 0010). `validate()` is public, runs no KiCad, and is not a hidden step of `save()`. `is_modified` is a setter-maintained flag.
Connectivity verification is a client sequence: `before = project.netlist()`, edit, `after = project.netlist()`, `before == after`. The package does not predict or excuse expected electrical changes.
Peer locks are a query (`is_locked`, `lock_file`), not a write guard.
Footprint libraries are two levels: a directory with cached `summaries` and explicit `refresh()`, plus per-file `Footprint` artifacts. ADR 0010 removes their `on_close` choice. Delete, rename, create, and copy are immediate directory operations.
`update_from_library(library, name)` replaces a project's embedded copy with the library definition, in memory; the family covers symbols, footprints (#34), and worksheets (future).
The composite operations that predated ADR 0009 were split by ADR 0011 (#75, PR #81). The removed checks were removed, not moved into recipes.

### Schematic document model, save, and revert (locked)

Canonical decision: [ADR 0011](docs/adr/0011-schematic-document-model-save-and-revert.md), with owner amendments to D6 and D9, and as amended by ADR 0010.
Levels follow ADR 0010: level 0 is one file and one model; level 1 is what KiCad requires (`KiCad`, `Project`, `Schematic`); level 2 is convenience choices. Level 1 does not hide level-0 operations.
Nouns: `SheetFile` is one `.kicad_sch` (KiCad `SCH_SCREEN`); `SheetSymbol` is the box (`SCH_SHEET`); a sheet instance is one placement (`SCH_SHEET_PATH`, #79); `Schematic` is the project's set of sheet trees (`SCHEMATIC`). Do not add a bare `Sheet` class.
A project reference is a directory or any file in it, with exactly one `*.kicad_pro`. Root sheet files come from `top_level_sheets`, else `<name>.kicad_sch`, and must exist. Entry is through `Project`.
`Schematic.save()` writes only changed sheet files, children first (a deliberate deviation from KiCad's rewrite-all). ADR 0010 moves the conflict class and the retry of D4 to level 2. `project.save()` saves every changed owned document and nothing else.
ADR 0010 replaces D5: no `on_close` and no `discard()` at levels 0 and 1. `open` and `close` on a project are its lock.
`SheetFile` and `Schematic` have `revert()` today. Further revert work is deferred (ADR 0010 D7). At level 0, a new load does the same job.
No in-memory original. A fingerprint check runs `stat()` first: a different size is a change; the same size and stamp (device, inode, mtime) are no change; only otherwise is the file read and hashed. The fingerprint is the record for the "changed on disk" check.
`project.backup(destination, size_limit_bytes=None)` archives disk state with explicit arguments and no built-in policy. `project.save_as()` writes, copies, rewrites identity, and rebinds; it runs no proof and writes no ZIP.
`Netlist` equality compares component identity and typed pin-to-net connections; pin electrical types count because they affect ERC.
ADR 0010 resolves #78: a model has no close, library ownership is gone, and the `KiCad` root is a level-1 join.

### Functional ownership

Canonical TOC, responsibilities, donor basis, and exclusions: [ADR 0002](docs/adr/0002-functional-service-toc.md).
Terms: [CONTEXT.md](CONTEXT.md).

The seven areas are Projects, Schematics, PCBs, Symbol libraries, Footprint libraries, Library tables and resolution, and Connectivity.
They are not seven independent entry points or final Python namespace names.
Projects own schematic and PCB context. Checks belong to the project or document being checked.
Library resolution can work without a project. Project context adds lookup locations and variables.

Parsing, text editing, and runtime safeguards are internal details.
ADR 0003 selects one source-preserving S-expression representation for semantic reads and localized edits.
Preserve opaque content outside the operation's required understanding. Use current spans and reparse changed source before subsequent edits.
No-op saves preserve bytes. Edited output must contain the required delta and preserve untouched content.
Connectivity checks are client sequences (`project.netlist()` before and after), not hidden steps inside save.
Placed-symbol insertion follows W4-ORDER-01: UUID order within the symbol section, not coordinates or references.
Do not normalize unrelated content through a whole-file rewrite or automatic KiCad resave.
Consumer-specific compatibility adapters belong in consumers, not this package.
ADR 0004 selects the first functional slice: explicit-path symbol-library inspection and localized updates to existing, unambiguous properties declared on a selected symbol.
Keep declared and inherited values distinct, preserve unit/body-style identity and repeated properties, and follow its acceptance gates.
The first slice is implemented in `kicad_primitives.symbols`; usage and limits are in `docs/symbol-libraries.md`. It is foundation evidence, not the 1.0 completeness bar.
Project context opening, parent-relative schematic hierarchy, and `text_variables` are implemented in `kicad_primitives.projects`; usage is in `docs/projects.md`.
`Project.schematic()` returns the whole `Schematic`. Its sheet files support placed-symbol attribute edits, embedded-symbol `update_from_library`, source previews, change observation, save, and revert, plus geometry and title-block read (`kicad_primitives.schematics`); limits are in `docs/schematics.md`. Schematic write format is `20260306`, distinct from symbol-library format `20251024`.
The owner-locked 1.0 capability and releasability bar is [ADR 0006](docs/adr/0006-1.0-capability-and-releasability-bar.md): macro service surfaces (A), proven cores (B), donor-used floor (C); functional tests as required evidence; cutover is not a gate.
KiCad integration is provisional internal machinery, not a committed public CLI module. Report/export operations belong on services; backend choice (`kicad-cli` or otherwise) is implementation detail (ADR 0006). Private `kicad-cli` path discovery is [ADR 0007](docs/adr/0007-internal-kicad-cli-discovery.md): lazy resolve via explicit path, `KICAD_CLI`, platform defaults, then `PATH`. KiCad IPC/plugin Python is out of default scope.
PCB editing belongs to intended scope and follows schematic and library editing patterns.
Exposed unimplemented operations raise an explicit unsupported-operation exception before making changes.
3D models remain out of scope until requested. Variants are deferred future work under ADR 0006.

### Future agent tool surface (locked, post-1.0)

Canonical decision: [ADR 0012](docs/adr/0012-future-mcp-tool-surface.md). It schedules no work and is not a 1.0 gate.
An agent surface is a sibling artifact over public primitives: one tool contract, several transports (MCP, CLI plus JSON Schema). Nothing agent-specific enters `kicad_primitives`.
Version 1 is correct first: each call is one full lifecycle with batch and preview. Sessions and caching are version 2.
Writes refuse when KiCad holds a lock. That refusal is agent-surface policy; no package write consults a lock. Release gates are an open set with a shared verdict vocabulary.
Native backends replace `kicad-cli` one capability at a time, when an ADR 0012 section 9 trigger fires.

Inventory used, unused, and unimplemented capabilities separately from defects and exclusions.
Parity equals used capabilities. Consumer usability also needs migration recipes and documentation.
Consumer usability is not package completeness. Releasability follows ADR 0006.


## Operating model (map + agents)

Wayfinder map: [#1 Stand-alone kicad-primitives package](https://github.com/plocher/kicad-primitives/issues/1). Charting is done; work the frontier one ticket at a time.

### Session charter

> Advance **one** map ticket or **one** small PR under existing ADRs; use donor tests as the net when lifting; no CI/test-framework epic before foundation; check with the owner before any new policy.

The owner may approve related implementation tickets in one umbrella PR.
Work them serially as coherent, validated per-ticket commits under the accepted decisions.
This does not authorize parallel decision-making or reopen the one-at-a-time human decision spine.

### Human vs agent

| Role | Who | Job |
| --- | --- | --- |
| Design authority | Owner | Lock grilling tickets; merge PRs to `main`; kill scope creep; decide when a slice is good enough to *offer* to a consumer |
| Map lead | One primary agent per session | Claims **one** wayfinder ticket first; does not parallel-resolve map tickets |
| Lift / port | Same or child session after locks | Mechanical harvest under ADRs; bring donor tests with the code |
| Adversary | Separate short session | Attacks a closed decision or PR; does not implement the same ticket |

### Owner loop

- **Early** on weighty decisions (TOC, write philosophy, first slice, distribution, seams).
- **Later** when axioms and ADRs are clear—agents execute under them.
- **Always** before an agent would "decide alone and implement something large."

### Grilling and wayfinder

- `wayfinder:grilling` is HITL: one question at a time, recommended answer, **owner locks**, then write ADR/code.
- Resolve decision/grilling tickets one at a time with the owner. Related approved implementation tickets may use the serial umbrella-PR exception above.
- Resolution: comment + close + one line on the map's Decisions so far.

### Git

- Feature branches + PRs only. `main` is protected (require PR; no force-push; enforce for admins).
- No direct pushes to `main`.
- Commit coherent, validated changes regularly on feature branches using Conventional Commits. The owner authorizes this without a separate approval request for each commit.

### Package vs consumer migration

- Building and ratifying this package **does not wait** on cutting over jBOM, kproj, kDoctor, Subdivision, or others.
- Released donor packaging must **not** depend on `kicad-primitives` before **`1.0.0`** on public PyPI ([ADR 0005](docs/adr/0005-distribution-and-versioning.md)).
- When the package is ready to offer to consumer X (**at or after 1.0** unless the owner reopens policy), **open an issue on X's tracker**: list frozen local modules, require remove-and-replace with `kicad-primitives`, and give a concrete recipe. That migration is X's work and does not gate this map.
- Optional **validation probes** before 1.0 find gaps and draft recipes. Use a disposable env and `uv pip install -e` (or Test PyPI). Do not merge a pre-1.0 dependency into donor `main`. Probes are not production cutovers and do not block package progress.
- Do not vendor this tree into a donor. Do not couple jBOM (or other donor) version lines to this package before a post-1.0 cutover PR.

### Tests until foundation

- Do **not** build a CI matrix or a greenfield behave cathedral before a working foundation.
- When a service **moves into** this repo, **move its existing functional scenarios and unit tests with it**. Do not leave nets behind in the donor.
- Prefer donor test runs during thin re-export periods.
- Package-side gates: AGENTS functional gates (byte round-trip; netlist connectivity)—not full fixture worship.
- Behave step style when scenarios land here: **jBOM-like, table-driven, explicit; no hidden magic templates**. Lock details in a small testing ADR on first scenario port—not before.

### Parallelism

- **Serial** on the decision spine (grilling tickets that block each other).
- **Parallel AFK** only for research/tasks that do not invent policy (e.g. lift inventory, filing donor bugs).
- **Docs / tutorials / examples**: follower of a real public surface—not a co-equal MVP track before TOC + write model + one shipped capability.
- Sub-agents: research catalogue, donor-side fixes, adversarial review. Not parallel unbound implementation swarms.

### Defer

- Homegrown CI and coverage theater before 1.0 foundation.
- Full new behave suite unrelated to lifted donor scenarios.
- Docs factory and multi-agent ports of unbound modules.
- kDoctor product UX, jBOM fab CLI, Eagle conversion product, 3D models.

### Next-session default

1. Read map #1 Decisions + this file + survey + ADR index.
2. Claim the first open, unblocked, unclaimed frontier ticket unless the owner names another. Locked spine: ADR 0002–0012. ADR 0010 amends ADR 0008, 0009, and 0011. ADR 0012 is a post-1.0 anchor. Mainline after the decision map is bounded implementation under those ADRs (the ADR 0010 rework, Projects hierarchy, symbol authoring depth, tables, connectivity, and so on).
3. Remaining map grilling is just-in-time (`#8` job/session, `#6` post-1.0 cutover rules) when a workflow needs it—not by lowest issue number.

## Working agreements

- **Done is better than Perfect**.  The goal is a robust and functional package that enables other projects, not a mountain of unit and functional tests that worship this package.
  
- **Discussion before change.** A question from the owner gets an answer and discussion first.
  No library, document or memory edits until the owner says it is settled.
- **Proposals are ADRs.** Anything complex or that has multiple complex solutions needs the owner's decision, and should be presented in  `docs/adr/` as a proposed ADR. 
   - **ADR Form**: use STE Writing style. Start with a succinct problem statement, constraints and requirements, definition of success/done, followed by a list of proposals, an analysis of each's pro and cons, a weighing of the candidates and a proposed choice.  An ADR tells a technical story, leading from a problem, through a set of candidate proposals, an evaluation and finally a decision with enough context and rationale that future readers will understand why the decision was made.

   - `docs/adr/README.md` is the ADR index. Each entry should succinctly paraphrase the ADR's problem and selected solution (or state if not approved)

- **Functional tests** are not **Unit tests**.  Unit tests validate internal implementation choices, functional tests validate external contracts and behaviors.

   - **Functional gates, not fixtures.** A behavioural test (round-trip a real file byte for
  byte; export a netlist with `kicad-cli` before and after an edit and compare connectivity)
   - **Byte preservation is a feature, proven by tests.** An edit touches only the nodes its
  operation's scope allows; everything else round-trips unchanged. Output must also be
  schema-correct: KiCad's own save is the reference for created and changed nodes. Byte
  preservation measures "unchanged outside the scope"; it does not limit a scope the operation
  needs, and it has no role inside a whole artifact that is created or deleted (only its
  siblings stay unchanged). Prove this in functional and unit tests before release, not with
  runtime checks (ADR 0003 amendment 2026-11-11).

- **Simplicity is always better than complexity**.  Design principles like YAGNI, DRY argue that simple and correct always beats complex, because complex is often not correct.
   - **One parser.** Do not add an s-expression parser beside the one chosen; improve and extend it.
   - **Each fact has one source.** The survey records where every capability lives today; when a
  piece moves here, its old home becomes a consumer or is deleted, never a second copy.
   - **Debt is not policy.** A shortcut copied from a source repo is debt to be named and addressed, not a
  convention to be followed.
- **Conventional Commits** with scopes (`feat(text)`, `fix(cli)`, `docs:`), a "Verified:"
  section in the body, feature branches and PRs; the owner merges.
- Keep review and design notes in `docs/review/`; move superseded material to `docs/archive/`
  (commit, push, then `git rm`). `*.swp` and `__pycache__` are gitignored everywhere.

  
## Consumers and their expectations

- The consumers are mature: nothing in them waits on this package. Each will migrate when this package does its job at least as well, with its own tests passing, one consumer per PR.
- FieldUnit-Subdivision and kDoctor today reach jBOM through `sys.path` into the Dropbox checkout; `jBOM`, `kproj` are also installed on the system via PyPI and `jBOM`'s plugin is integrated into the installed KiCad.
- `kicad-primitives` is the name kDoctor's architecture already uses for this layer; the import name is `kicad_primitives`.

## Layout (proposed)

```
src/kicad_primitives/   functional services and private implementation layers
tests/                  Unit tests
features/               behave / gherkin functional scenarios
docs/                   the survey, ADRs, review notes
```

Python 3.11 or later. CircuitDK's `lossless_sexpr` is the private parser foundation under ADR 0003.

## Commands

Create a venv and install this package editable with `uv` (ADR 0005):

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
python -m unittest discover -s tests -q
```

Static checks used for the first slice: `ruff check src tests`, `ruff format --check src tests`, and `mypy --strict --follow-untyped-imports src/kicad_primitives`.
The normal suite needs neither KiCad nor donor checkouts. The opt-in `tests/verify_symbol_libraries.py` and `tests/verify_footprint_libraries.py` take explicit library paths, a new output directory, and optionally `--kicad-cli`; see `docs/symbol-libraries.md` and `docs/footprint-libraries.md`.
On this machine KiCad's CLI is `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`. The verifier may take an explicit `--kicad-cli` path (ADR 0007 step 1). Shared auto-discovery is private package machinery under ADR 0007, not a public module.
Full `uv lock` / release automation is deferred; it is not required by ADR 0005.



## Documentation contract

Canonical rules: [`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md).

- **Usage page** under `docs/` is the human API contract for each shipped public area (STE-flavored).
- **Docstrings** are required on public classes, methods, and exported exceptions.
- **CHANGELOG** records the landing; link the usage page when useful.
- A PR that adds or changes **public** surface must update the matching usage page and docstrings.
- Generated full API reference is **deferred**; do not invent a second hand-written API style.
- Docs follow a real public surface. Do not open a docs-factory epic before foundation.

## Agent skills

### Issue tracker

GitHub Issues for this repository (`gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` (when present), ADRs in `docs/adr/`, founding survey under `docs/`. See `docs/agents/domain.md`.
