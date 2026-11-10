# ADR 0012: Future MCP tool surface (anchor)

Date: 2026-11-10

Status: **Proposed only.** Not accepted. Not a 1.0 gate. Not an implementation ticket.

Related: ADR 0002 (TOC), ADR 0005 (distribution), ADR 0006 (1.0 bar), ADR 0007 (private CLI discovery), ADR 0008 (artifacts), ADR 0009 (primitives), ADR 0011 (schematic model). Review input: [HITL comparison 2026-11-10](../review/hitl-comparison-2026-11-10.md).

## Problem

A long-term goal of this effort is a full-featured agent MCP that uses shared KiCad capabilities. Without an anchor, later work can drift in three bad directions:

1. Build MCP tools that re-implement file I/O beside this package.
2. Grow an executive inside `kicad_primitives` so agents get one-shot "design the board" calls.
3. Copy a generator-first harness (for example HITL) into the library and lose edit-in-place, byte preservation, and multi-app reuse.

The package decision spine already says what the library is. It does not say how an MCP should sit on that spine when the time comes.

## Constraints and requirements

- **Post-1.0 by default.** Public PyPI `1.0.0` and ADR 0006 capability come first unless the owner reopens scope.
- **Package stays primitives.** ADR 0008 and ADR 0009 stand. MCP may orchestrate. The import package must not become the orchestrator.
- **One I/O home.** MCP server code may live in this repo later or in a sibling distribution. It must call public `kicad_primitives` APIs. It must not grow a second sexpr stack.
- **Hosts vary.** Tools must not assume one agent product (Claude Code, Warp, or other). Skills and prompts are host-specific. Tool contracts are not.
- **Donors remain first clients.** jBOM, kproj, kDoctor, Subdivision, and Railroad-shaped edits still define the floor. Agent greenfield generate is extra, not a replacement ontology.
- **License boundary.** Learning from external methods is fine. Vendoring non-MIT harness trees needs an explicit license decision.
- **No hidden KiCad.** Engine use stays on operations whose purpose is the engine (ERC, DRC, netlist, exports), plus private discovery (ADR 0007). Profile isolation is a runner concern.

## Definition of success (for this anchor)

A future implementer can answer:

1. What may an MCP tool call inside the package?
2. What must stay out of the package?
3. How do composite "gates" appear without violating ADR 0009?
4. When does generator-first board-as-code enter the story, if at all?
5. What evidence must a tool return so agents cannot launder a red run as green?

This ADR does **not** require a working MCP server, a tool schema freeze, or a transport choice (stdio, HTTP, or other).

## Candidates

### A. MCP inside the package as public modules

Ship `kicad_primitives.mcp` with tools and session state in the same distribution as file I/O.

Pros: one install; agents find tools next to the library.

Cons: forces agent-host policy into the core dependency of jBOM-class apps. Pulls prompts, tokens, and workflow into ADR 0005 versioning. Re-creates an executive under a new name.

**Reject** as default shape.

### B. No MCP design until after several consumer cutovers

Wait until donors migrate, then design tools from production call sites only.

Pros: maximum YAGNI; real call shapes.

Cons: agent MCP is already a stated long-term goal; without an anchor, side projects will invent parallel I/O. Cutover timing is not the same as tool-surface timing (ADR 0005).

**Reject** as "no document." Accept delay of **implementation**.

### C. Sibling MCP server over public primitives, with an explicit tool map (choose)

A separate distribution or repo package (name TBD) depends on `kicad-primitives >= 1.0.0` on public PyPI. Tools map to public primitives and a small set of named recipes. Host skills carry HITL-like procedure. The library never imports the server.

Pros: matches ADR 0009; keeps MIT core clean; allows host-specific skills; lets generator and distributor gates live at the server or recipe edge.

Cons: two artifacts to release; server can still grow a shadow executive if discipline fails.

**Proposed choice.**

### D. Adopt HITL (or similar) as the MCP

Wrap the HITL skeleton and skill as the product; call this package only where convenient.

Pros: fast agent demo for greenfield boards.

Cons: generator-first ontology; monolythic pipeline; Claude-specific skill; HIL-ASA license on tooling; weak fit for existing hierarchical projects. Undermines the reason this package exists.

**Reject** as the architecture. Keep HITL as **process and gate inspiration** only (see review note).

## Proposed decision (non-binding until accepted)

Choose **C**. Record the following rules as the anchor. Owner acceptance is a later act and may edit this list.

### 1. Layering

```text
Host agent (Claude Code, Warp, …)
  -> host skill / prompts / swarm policy
    -> MCP server (sibling artifact)
      -> public kicad_primitives (+ optional recipes)
        -> files, private CLI discovery, optional engine
```

- **Library:** artifact objects, integrity, format rules, one-job operations.
- **Recipes (when they exist):** visible sequences of public primitives; no private imports; optional (ADR 0009, ADR 0011 D10).
- **MCP server:** transport, sessions, tool schemas, structured envelopes, runner isolation, optional composite tools that *name* each step.
- **Host skill:** interview, cost, chain vs swarm, resume docs, standing decisions, adversarial review ritual.

### 2. Tool design rules

1. **One tool, one job** where practical. Prefer `sheet.set_attribute` over `fix_project_for_fab`.
2. **Composite tools are allowed only when:**
   - the tool name states the policy (for example `release_check` or `export_fab_if_clean`);
   - the implementation is a thin sequence of public primitives or recipes;
   - the response lists each step result;
   - the client can run the steps as separate tools instead.
3. **Mutations stay buffered.** Tools that edit call the same in-memory model as Python clients. Save, save_as, discard, revert, and close remain explicit tools. No save-on-mutate.
4. **No silent overwrite.** Conflict errors surface to the agent. `overwrite=True` is an explicit tool argument when the primitive supports it.
5. **Engine tools are explicit.** `erc`, `drc`, `netlist`, and exports never hide inside `save`.
6. **Structured evidence.** Every gate-like tool returns machine-readable counts, paths, and verdict fields. Do not rely on prose alone. Prefer content hashes that ignore known volatile headers when comparing fab outputs.
7. **Session policy is server-side.** Worktree layout, merge locks, RAM slots, and token tripwires are not library APIs.
8. **Isolation.** Server runners that invoke `kicad-cli` or process-bound engines point KiCad profile paths at a scratch home. Do not write agent runs into the engineer's GUI profile.

### 3. Suggested tool groups (illustrative, not a schema freeze)

Names are indicative. Final names follow shipped usage pages at implementation time.

| Group | Examples | Package basis |
| --- | --- | --- |
| Project | open, close, save, revert, discard, backup, list sheets, text_variables, lock query | `projects` |
| Schematic | open schematic view, list placed symbols, get/set/delete attributes, update_from_library, geometry/title read | `schematics` / ADR 0011 nouns |
| Symbols | open library, inspect, edit declared properties and pins, create/rename/copy as shipped | `symbols` |
| Footprints | library summaries, open footprint, edit as shipped | `footprints` |
| Tables | list, resolve, add/rename/set_uri/delete | `tables` |
| Connectivity | netlist obtain, compare two netlists, connectivity_sets | `netlist` + client compare |
| Checks / export | erc, drc, gerber/drill/svg/step as shipped | project/PCB services; private CLI |
| Release composites (optional) | netlist-before/after + erc + drc + explicit save; fab export only if gates pass | recipes + server |
| Generate (optional, separate) | run a board-as-code entry point owned by the **server or another package** | not layer-0 library nouns |

### 4. What stays out of `kicad_primitives`

- MCP transport and tool registry
- Agent prompts, swarm waves, usage tripwires, resume documents
- Freerouting, negotiated routers, and fab vendor opinion as core APIs
- Live distributor HTTP checks (server or BOM consumer)
- CadQuery, firmware twin, Unreal/Isaac, and other non-KiCad disciplines
- Auto-commit, auto-push, and branch promotion
- A public `pcbnew` module (any future use stays private and purpose-limited)

### 5. Generator-first boards

Allowed as a **server-side or external** workflow after 1.0 if demand exists.

Rules:

- The design source of truth for that workflow may be Python (or SKiDL, atopile, or similar).
- Generated KiCad files are outputs unless the user opens them as ordinary artifacts afterward.
- Do not redefine `SheetFile` / `Schematic` / `Project` as generator DTOs.
- Prefer "gates after netlist" over arguing one board-as-code stack inside this ADR.

### 6. Relationship to HITL

HITL informs **gates, isolation, evidence, chain defaults, and honest skill text**.

HITL does not define package nouns, write philosophy, or MCP layering.

See [docs/review/hitl-comparison-2026-11-10.md](../review/hitl-comparison-2026-11-10.md).

### 7. Versioning and dependency

- Do not publish a production MCP that depends on pre-1.0 `kicad-primitives` as a hard release pin (same spirit as ADR 0005 for donors), unless the owner explicitly allows a disposable probe.
- Pre-1.0 MCP spikes may use editable installs. They must not force package API freezes beyond existing ADRs.
- Server versioning is independent. Breaking tool schema changes do not require breaking the library if tools stay thin.

### 8. Documentation when built

- Library usage pages remain the human contract for primitives.
- MCP server keeps its own tool catalog and skill text.
- Do not duplicate the full primitive API inside skill prose. Point at usage pages and stable tool names.

## Consequences (if accepted later)

- Map work stays on ADR 0006 implementation until 1.0 unless the owner opens a deliberate MCP spike ticket.
- Adversarial reviews of the map may cite this ADR and the HITL note when testing "are we building an executive by accident?"
- First MCP implementation ticket (future) must: list tools against shipped surfaces; forbid private module imports from the server; show one composite tool's step list; state isolation behavior for CLI.
- Recipes module still appears only when a real caller needs it (ADR 0011). MCP demand can be that caller, but must say so in a recipes ADR or ticket then.
- No change to current public Python API is authorized by this proposal alone.

## Open questions (for owner grilling when MCP is scheduled)

1. Same git repo vs sibling repo for the server?
2. Distribution name?
3. Default composite gates on or off for save-like tools?
4. Is board-as-code in-scope for the first MCP release, or KiCad-artifact edit only?
5. How far may the server go with `pcbnew` while keeping the library free of it?
6. Multi-agent session model: single project lock in the server, or rely on host worktrees only?

## What "done" means for this proposal document

- The anchor exists and is indexed.
- Status remains **Proposed** until the owner accepts, revises, or rejects it.
- Implementation and schema work wait for an explicit owner decision and a post-1.0 (or explicitly reopened) ticket.
