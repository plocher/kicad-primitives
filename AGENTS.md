# AGENTS.md

## What this project is

A general Python package for reading, editing and writing KiCad 10 projects and libraries: schematics, symbol libraries, footprints, library tables, netlists, and the `kicad-cli` facade. 

The larger project's aspiration is to replace the need for kicad-cli, KiCad's own incomplete and limited API and to consolidate the KiCad handling that today lives in six of the owner's repos, each with its own parser and its own idea of writing. 

This last part, the consolidation, that is this session's focus.  The various per-project services become an independent project: none of those repos is blocked on this work, and each becomes a consumer when the package is better than what it has.

Read `docs/kicad-services-survey-2026-10-12.md` first. It is the brief: the inventory of what each source repo can do, the overlaps, the gaps, the two options considered, and the owner's pending decisions (its section 6). Nothing in this file overrides it.

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

## Scope: the API areas (survey section 5, Option A's table of contents)

1. `sexp`: read a file to a data structure; typed accessors; version probe.
2. `text`: byte-preserving edits; node-level helpers (set, delete, rename a property; rename a symbol or pin; add a pin; split units; copy a symbol between libraries); a formatter for inserted nodes; a round-trip gate.
3. `symbols`: the library model: symbols, units (unit 0 is common to all), pins per unit with numbers and positions, properties, `extends`, `ki_locked`; write in KiCad's sorted order.
4. `netlist`: the `kicadsexpr` netlist model and the connectivity diff.
5. `schematic`: placed objects: symbol instances with fields, uuid, transform, unit, instance paths; wires, labels, junctions, sheets; the embedded `lib_symbols`.
6. `project`: `.kicad_pro`, sheet tree with instance paths, project libraries and settings.
7. `cli`: find `kicad-cli` (env `KICAD_CLI`, then PATH, then the app bundle), run netlist, ERC, DRC, symbol SVG and upgrade exports, filter the Fontconfig noise.
8. `tables`: sym, fp and design-block library tables, global and project scope, `${VAR}` resolution.
9. `footprints`: a read model for `.pretty` libraries.
10. `runtime`: lock files, running-KiCad detection, plugin mode.
11. `checks`: ERC and DRC report interpretation.

Non-goals until a consumer asks: PCB editing, 3D models.

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
src/kicad_primitives/   one subpackage per API area above
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
