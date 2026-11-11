# ADR 0012: Future agent tool surface (anchor)

Date: 2026-11-10, revised 2026-11-11

Status: **Proposed only.** Not accepted. Not a 1.0 gate. Not an implementation ticket. The 2026-11-11 revision records owner positions from the [external survey synthesis](../review/external-survey-synthesis-2026-11-11.md); the ADR as a whole still waits for owner acceptance.

Related: ADR 0002 (TOC), ADR 0003 (writes, as amended 2026-11-11), ADR 0005 (distribution), ADR 0006 (1.0 bar), ADR 0007 (private CLI discovery), ADR 0008 (artifacts), ADR 0009 (primitives), ADR 0011 (schematic model). Review input: [HITL comparison](../review/hitl-comparison-2026-11-10.md) and the [external survey synthesis](../review/external-survey-synthesis-2026-11-11.md).

## Problem

A long-term goal of this effort is a full-featured agent tool surface (an MCP server is the first expected form) that uses shared KiCad capabilities. Without an anchor, later work can drift in three bad directions:

1. Build agent tools that re-implement file I/O beside this package.
2. Grow an executive inside `kicad_primitives` so agents get one-shot "design the board" calls.
3. Copy a generator-first harness into the library and lose localized editing, source preservation, and multi-app reuse.

The package decision spine already says what the library is. It does not say how an agent surface sits on that spine.

## Constraints and requirements

- **Post-1.0 by default.** Public PyPI `1.0.0` and ADR 0006 capability come first unless the owner reopens scope.
- **Package stays primitives.** ADR 0008 and ADR 0009 stand. The agent surface may orchestrate. The import package must not become the orchestrator.
- **One I/O home.** Agent-surface code calls public `kicad_primitives` APIs. It does not grow a second sexpr stack.
- **Hosts vary.** Tool contracts do not assume one agent product or one transport. Skills and prompts are host-specific.
- **Donors remain first clients.** jBOM, kproj, kDoctor, Subdivision, and Railroad-shaped edits define the floor. Agent greenfield generation is extra, not a replacement ontology.
- **License boundary.** Learning from external projects is fine. Vendoring non-MIT trees needs an explicit owner decision.
- **No hidden KiCad.** Engine use stays on operations whose purpose is the engine, plus private discovery (ADR 0007).
- **Correct first.** Version 1 can be slow, simple, and inefficient, as long as it is correct. Version 2 addresses version 1's failings (owner, 2026-11-11).

## Definition of success (for this anchor)

A future implementer can answer:

1. What may an agent tool call inside the package?
2. What must stay out of the package?
3. How does a tool call map to the artifact lifecycle?
4. How do composite gates appear without violating ADR 0009?
5. What does a tool do when KiCad has the project open?
6. What evidence must a tool return so agents cannot launder a red run as green?
7. When does generator-first board-as-code enter the story, if at all?

This ADR does **not** require a working server, a tool schema freeze, or a transport choice.

## Candidates

### A. Agent surface inside the package as public modules

Ship `kicad_primitives.mcp` with tools and session state in the same distribution as file I/O.

Pros: one install; agents find tools next to the library.

Cons: forces agent-host policy into the core dependency of jBOM-class apps. Pulls prompts and workflow into ADR 0005 versioning. Re-creates an executive under a new name.

**Reject** as default shape.

### B. No design until after several consumer cutovers

Pros: real call shapes.

Cons: the goal is already stated; without an anchor, side projects invent parallel I/O. Cutover timing is not tool-surface timing (ADR 0005).

**Reject** as "no document." Accept delay of **implementation**.

### C. Sibling agent surface over public primitives, one tool contract (choose)

A separate distribution (name TBD) depends on `kicad-primitives >= 1.0.0`. Tools map to public primitives and a small set of named composites. One tool contract (inputs, result envelope, verdict vocabulary) serves several transports: MCP first, and CLI with JSON Schema output as an equal sibling. Host skills carry procedure. The library never imports the agent surface.

Survey evidence: three of five surveyed projects reach agents without MCP; kicad-happy reaches five hosts and CI through skill text plus CLIs with `--schema` output.

Pros: matches ADR 0009; keeps the MIT core clean; one contract across hosts and CI.

Cons: two artifacts to release; the agent surface can still grow a shadow executive if discipline fails.

**Proposed choice.**

### D. Adopt an external project as the agent surface

Wrap HITL, Seeed kicad-mcp-server, KiCad-AI-Assistant, or similar, and call this package only where convenient.

Cons: every surveyed project rewrites whole files, appends text, or keeps two or three parsers; none edits existing files with source preservation. Adoption undermines the reason this package exists.

**Reject** as the architecture. Keep external projects as inspiration only (§7).

## Proposed decision (non-binding until accepted)

Choose **C**, with the rules below.

### 1. Layering

```text
Host agent (Claude Code, Codex, Warp, …)
  -> host skill / prompts / orchestration policy
    -> agent surface (sibling artifact; MCP and CLI transports)
      -> public kicad_primitives (+ optional recipes)
        -> files, private CLI discovery, optional engine
```

- **Library:** artifact objects, integrity, format rules, one-job operations.
- **Recipes (when they exist):** visible sequences of public primitives; optional (ADR 0009, ADR 0011 D10).
- **Agent surface:** transports, tool schemas, result envelopes, lock policy, runner isolation, named composites.
- **Host skill:** interview, cost, orchestration mode, resume notes, standing decisions, review rituals.

### 2. Calls and sessions

**Version 1: each call is one complete lifecycle.** A mutating call opens the artifacts it needs, applies its operations in memory, runs `validate()`, then saves or discards. The server holds no documents between calls. Re-opening on every call costs time and buys correctness: the fingerprint check (ADR 0011) catches outside edits on every call, and no handle can go stale.

Two features recover most of what sessions give:

- **Batch.** A mutating tool accepts a list of operations. It saves only when every operation and `validate()` pass. One call is one transaction.
- **Preview.** A `dry_run` flag returns the pending diff and validation result without saving.

A named composite may capture `project.netlist()` before and after its batch, inside the same call, and refuse to save on a difference (ADR 0009 verify pattern, no state between calls).

**Version 2: a session-oriented API**, when evidence asks for it. Sessions enable caching and predictive reads. A session start is also the natural trigger for one pre-session `project.backup()`, skipping per-call backups inside the session, with cleanup at session end. Session close maps to ADR 0011 `on_close`. Version 2 must keep version 1 semantics observable: same results, faster.

### 3. Coexistence with a running KiCad

KiCad 10 cannot save or revert a schematic over its API. A file writer beside a running editor can lose the agent's edit or the user's unsaved edit, and nothing on disk shows which.

- **Rule:** when a native KiCad lock exists for any document a call would write, the call is read-only. Mutating tools refuse with a clear message that names the locked file and asks the user to close it in KiCad.
- Read tools continue to work.
- **No lock-removal tool in version 1.** A stale lock after a KiCad crash is the user's to fix. An interactive session may ask the user to fix it.
- The library rule does not change: `is_locked` and `lock_file` stay queries (ADR 0009). The refusal is agent-surface policy.
- A KiCad plugin that runs inside KiCad is a different product with different options. It is out of scope here.

### 4. Tool design rules

1. **One tool, one job** where practical. Prefer `set_attribute` over `fix_project_for_fab`.
2. **Composite tools are allowed only when:**
   - the tool name states the policy;
   - the implementation is a thin sequence of public primitives or recipes;
   - the response lists each step with a compact record (name, verdict, artifact path);
   - the client can run the steps as separate tools instead.
3. **No silent overwrite.** Conflict errors surface to the agent. `overwrite=True` is an explicit tool argument where the primitive supports it.
4. **Engine tools are explicit.** ERC, DRC, netlist, and exports never hide inside a save.
5. **Freshness.** A tool may reuse a derived engine result (netlist, ERC report) only when the source fingerprints still match. The response names the result it used and its provenance (`Project.netlist()` already returns content hashes). Version 1 does not cache; this rule binds version 2 caching.
6. **Structured evidence.** Gate-like tools return machine-readable verdicts, counts, and paths. Prose alone is not evidence. Prior art: KiCadAI (`pass | warn | failed | blocked | skipped | not_run | error`; evidence states `verified | inferred | missing | failed`; confidence only goes down at later stages; a `claim_boundary` field) and kicad-happy (schema'd envelopes, diagnostics, quarantine of uncited claims).
   - **Dispatch-only tools** (for example a GUI action) report `dispatched`, never a verdict.
   - **Staged adoption.** A tool that cannot yet produce the vocabulary is wrapped. Its evidence reports `unknown`. `unknown` stays visible, lowers downstream confidence, and never counts as a pass.
7. **No runtime byte checks.** Source preservation and schema correctness are proven by functional and unit tests before release (ADR 0003 as amended). Tools do not make the user absorb the project's lack of confidence.
8. **Isolation.** Runners that invoke engines that write KiCad profile state point that state at a scratch home. The exact scope of this rule (all `kicad-cli` calls, or only engines that write settings) is an open question.
9. **Sheet paths.** Tools accept any file in the project directory and resolve the project, as `Project.open()` does.

### 5. Release gates are an open set

Netlist parity is necessary, not sufficient. A release check is a composable list of named gates, owned outside the library. Each gate returns the §4.6 vocabulary. Known members:

- schematic connectivity: `netlist()` before and after;
- ERC;
- DRC with schematic parity (catches physical-only breaks a netlist cannot see);
- inventory and BOM completeness;
- supply chain (part resolves to the named MPN; stock; lifecycle);
- errata tracking;
- fab-capability rules.

The list grows by adding gates, not by widening a primitive.

### 6. What stays out of `kicad_primitives`

- Agent transports and tool registry
- Agent prompts, orchestration waves, usage tripwires, resume notes
- Lock-refusal policy (the library only answers the query)
- Routers and fab-vendor opinion as core APIs
- Distributor and parts-registry clients
- Non-KiCad disciplines (CAD, firmware, simulation hosts)
- Auto-commit, auto-push, branch promotion
- A public `pcbnew` module, and KiCad IPC. Either stays private to the agent surface and limited to one stated purpose. KiCad's API is incomplete today; expect to re-implement what it cannot do.

### 7. Relationship to external KiCad-agent projects

Reviews live in `docs/review/`. Popularity accepts nothing. Each project informs a different layer:

- **HITL (claude-hardware-in-the-loop):** gates, isolation, evidence files, chain-over-swarm orchestration, honest skill text.
- **kicad-happy:** host skills and domain gates over a deep read model; skill plus CLI plus JSON Schema as a transport; recorded-oracle tests.
- **Seeed kicad-mcp-server:** what a stateless MCP looks like in practice, including hidden-step and stale-result failures.
- **KiCad-AI-Assistant:** in-app agents, KiCad API limits, snapshot and rollback policy, context management.
- **KiCadAI:** evidence and refusal vocabulary; KiCad canonical-token tests for generated output.

A second survey wave should cover reusable library peers (`kiutils`, `kicad-skip`, `kicad-python`).

### 8. Generator-first boards

Allowed as an agent-surface or external workflow after 1.0 if demand exists.

- The design source of truth for that workflow may be Python (or SKiDL, atopile, or similar).
- **Generators write through public layer-0 creation primitives** (new sheet file, add placed symbol, wire, label, sheet), never through their own writers. Whether item creation is in the ADR 0006 bar is a separate grill.
- Do not redefine `SheetFile`, `Schematic`, or `Project` as generator data objects.

### 9. Native backends

The project aims to replace the need for `kicad-cli` and KiCad's incomplete API (AGENTS). `kicad-cli` is the backend today; ADR 0006 already makes the backend an implementation detail. Move one capability (netlist, ERC, connectivity, and so on) to a native implementation when one of these triggers fires:

1. hosts without KiCad matter for that capability (CI, cloud agents, the agent surface itself);
2. `kicad-cli` or KiCad's API gives a wrong, partial, or missing answer;
3. a recorded-oracle test exists: `kicad-cli` output captured as fixtures, and the native result must match it.

`kicad-cli` stays the reference oracle after a move. Each move needs its own small ADR.

### 10. Versioning and dependency

- No production agent surface pins pre-1.0 `kicad-primitives`, unless the owner allows a disposable probe.
- Pre-1.0 spikes may use editable installs. They do not force package API freezes beyond existing ADRs.
- The agent surface versions independently. Thin tools keep schema changes from forcing library breaks.

### 11. Documentation when built

- Library usage pages remain the human contract for primitives.
- The agent surface keeps its own tool catalog and skill text, pointing at usage pages.

## Consequences (if accepted later)

- Map work stays on ADR 0006 implementation until 1.0 unless the owner opens a deliberate spike.
- The first implementation ticket must: list tools against shipped surfaces; forbid private imports; implement §2 version 1 (per-call lifecycle, batch, preview); implement §3 lock refusal; show one composite's step list; state isolation behavior.
- The recipes module still appears only when a real caller needs it. The agent surface can be that caller and must say so then.
- No change to the public Python API is authorized by this proposal.

## Open questions (for owner grilling when the agent surface is scheduled)

1. Same repo or sibling repo? Distribution name?
2. Version 2 session trigger: what evidence (speed, multi-call atomicity) starts it?
3. Rule 8 scope: isolate every `kicad-cli` call, or only engines that write profile state?
4. Is schematic item creation in the 1.0 bar or post-1.0 (§8)?
5. How far may the agent surface go with `pcbnew` and KiCad IPC while the library stays free of them?
6. Which capability moves to a native backend first, and which trigger fires (§9)?

## What "done" means for this proposal document

- The anchor exists and is indexed.
- Status remains **Proposed** until the owner accepts, revises, or rejects it.
- Implementation waits for an explicit owner decision and a post-1.0 (or explicitly reopened) ticket.
