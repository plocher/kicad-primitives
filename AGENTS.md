# AGENTS.md

## What this project is

A general Python package for reading, editing and writing KiCad 10 projects and libraries: schematics, PCBs, symbol libraries, footprint libraries, library resolution, and connectivity.

The larger project's aspiration is to replace the need for kicad-cli, KiCad's own incomplete and limited API and to consolidate the KiCad handling that today lives in six of the owner's repos, each with its own parser and its own idea of writing. 

The consolidation is this project's job. The various per-project services become an independent package; none of those repos is blocked on this work. Each becomes a consumer when the package is better than what it has—**migration is decoupled** (see Operating model).

Read `docs/kicad-services-survey-2026-10-12.md` first. It is the founding inventory, not the current decision record. Accepted ADRs record later owner decisions and supersede conflicting survey proposals.

## Package identity (locked)

Canonical record: `docs/PACKAGE_IDENTITY.md` and ADR 0001. Do not invent alternate names in code or docs.

| Field | Value |
| --- | --- |
| Distribution | `kicad-primitives` |
| Import | `kicad_primitives` |
| License | MIT |
| Python | 3.10+ |
| KiCad write/edit target | 10 |
| Format contract | per-file `(version …)` |
| Older formats | read-only when cheap |
| `sexpdata` | declare only after parser ADR keeps it |
| Home | this repo only for shared KiCad I/O |

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

Canonical TOC, responsibilities, donor basis, and exclusions: [ADR 0002](docs/adr/0002-functional-service-toc.md).
Terms: [CONTEXT.md](CONTEXT.md).

The seven areas are Projects, Schematics, PCBs, Symbol libraries, Footprint libraries, Library tables and resolution, and Connectivity.
They are not seven independent entry points or final Python namespace names.
Projects own schematic and PCB context. Checks belong to the project or document being checked.
Library resolution can work without a project. Project context adds lookup locations and variables.

Parsing, text editing, and runtime safeguards are internal details.
KiCad integration is provisional internal machinery, not a committed public CLI module.
PCB editing belongs to intended scope and follows schematic and library editing patterns.
Exposed unimplemented operations raise an explicit unsupported-operation exception before making changes.
3D models remain out of scope until requested.

Inventory used, unused, and unimplemented capabilities separately from defects and exclusions.
Parity equals used capabilities. Consumer usability also needs migration recipes and documentation.
Consumer usability is not package completeness. The owner locks the 1.0 release bar.


## Operating model (map + agents)

Wayfinder map: [#1 Stand-alone kicad-primitives package](https://github.com/plocher/kicad-primitives/issues/1). Charting is done; work the frontier one ticket at a time.

### Session charter

> Advance **one** map ticket or **one** small PR under existing ADRs; use donor tests as the net when lifting; no CI/test-framework epic before foundation; check with the owner before any new policy.

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
- Never resolve more than one map ticket per session.
- Resolution: comment + close + one line on the map's Decisions so far.

### Git

- Feature branches + PRs only. `main` is protected (require PR; no force-push; enforce for admins).
- No direct pushes to `main`.

### Package vs consumer migration

- Building and ratifying this package **does not wait** on cutting over jBOM, kproj, kDoctor, Subdivision, or others.
- When a slice is good enough for consumer X, **open an issue on X's tracker**: list frozen local modules, require remove-and-replace with `kicad-primitives`, and give a concrete recipe. That migration is X's work and does not gate this map.
- Optional early cutovers are **validation probes** (find gaps), not milestones that block package progress.

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
2. Claim the first open, unblocked, unclaimed frontier ticket unless the owner names another. The public TOC decision is recorded in ADR 0002.
3. Optional parallel AFK: [#9 lift inventory](https://github.com/plocher/kicad-primitives/issues/9), [#13 sheet-walk filing](https://github.com/plocher/kicad-primitives/issues/13).

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
   - **Byte preservation is a feature.** An edit touches only the nodes it means to; everything
  else round-trips unchanged. KiCad's own save is the reference for formatting inserted nodes.

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

Python 3.10 or later; `sexpdata` as a runtime dependency, if the chosen parser keeps it.

## Commands

None yet. When they exist: `python3 -m unittest discover -s tests -q`, and `kicad-cli` from `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli` on this machine (set `KICAD_CLI` to override).


## Agent skills

### Issue tracker

GitHub Issues for this repository (`gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` (when present), ADRs in `docs/adr/`, founding survey under `docs/`. See `docs/agents/domain.md`.
