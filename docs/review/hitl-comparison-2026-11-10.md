# HITL comparison (2026-11-10)

Status: research and adversarial input. Not an ADR. Does not change accepted decisions.

Subject: [claude-hardware-in-the-loop](https://github.com/Kemerd/claude-hardware-in-the-loop) (local clone `~/Dropbox/workspace/claude-hardware-in-the-loop`), compared with this package's ADRs and map.

Purpose: stress-test the decision spine and the wayfinder map against a real agent-driven hardware harness. Record what to steal, what to reject, and which claims need attack in a later adversarial pass.

Related: ADR 0002–0009, ADR 0011; founding survey; proposed [ADR 0012](../adr/0012-future-mcp-tool-surface.md) (MCP tool surface, post-1.0, not accepted).

## What HITL is

HITL is a **method**, a **Claude Code skill**, and a **project skeleton**. It is not a reusable KiCad I/O library and not an MCP server.

| Layer | Job |
| --- | --- |
| `docs/` | Method doctrine (PCB, CAD, firmware, twin, swarm, lessons) |
| `skills/hardware-in-the-loop/` | Agent procedure: cost warning, interview, scaffold, work modes |
| `templates/` | CI, audits, board pipeline, twin, CAD, swarm scripts copied into a project |

The published tree is a starting cage. A project is meant to rewrite the templates.

## How HITL uses KiCad

**Generator-first.** A board is a Python script that declares parts, nets, outline, placement, net classes, and pours. One shared pipeline writes schematic, board, checks, and fab outputs. Agents do not edit `.kicad_sch` or `.kicad_pcb` by hand. The generator is the design.

**Backend stack inside one executive:**

1. Text S-expression write for schematic, symbol library, project, lib tables, and footprint localization (string and regex edits on `.kicad_mod`, not a lossless sexpr model).
2. `pcbnew` under KiCad's bundled Python for board build, zones, remnant cleanup, and route import.
3. `kicad-cli` for ERC, DRC with schematic parity, Gerbers, STEP, and related exports.
4. External routers: Freerouting (default) or a negotiated PathFinder-style router.
5. Live distributor (LCSC) verify before fab files exist.

**Operational rules that matter:**

- Isolate KiCad config, documents, cache, and temp away from the user profile (`kicad_env.isolate()` before `import pcbnew`).
- Force determinism where possible (`PYTHONHASHSEED=0`, uuid5 schematic IDs, seeded KIIDs). Freeze Freerouting SES because the router is not bit-stable.
- Never `Remove()` footprint graphics under live SWIG wrappers (heap corruption).
- Never demote DRC severities. Write fab only when ERC, final DRC, and distributor match are clean.
- Keep a board-owned footprint library so runs do not depend on random machine tables.
- Return structured results JSON (`hil-board-results/1`) with step counts, hashes, and verdict even on red runs.

**Public agent-facing board API (shape only):** `Board`, `part`, `place`, `outline`, `hole`, `netclass`, `pour`, `stitch`, `custom_footprint`, `net_limits`, `run`. Everything else is internal pipeline.

## How agent and tooling are glued

Prompt and skill own procedure. Machines own refusal.

| Prompt / skill side | Tool / gate side |
| --- | --- |
| Cost warning and mode choice (chain default, swarm optional) | CI matrix; exit 0 **and** a required summary line |
| Owner interview into `DECISIONS.md` / `QUESTIONS.md` | No-shortcut audit (stubs, guesses, canned success) |
| Stages, render-and-look, hand placement | ERC and DRC at KiCad default severities; live MPN match |
| Chain briefs, skeptics, structured reports | Machine slots, detach + watchers, WIP backup, merge lock |
| Standing rules in `AGENT_RULES.md` | Portability and citation checks |

Git cage: worktrees per lane, every lane lands on `dev` (red included), `main` only on green CI with zero regressions vs last main report.

Token lesson they paid for: a full swarm day burned on the order of **4–5 million tokens**, mostly by waking large contexts. Default became a **chain**: one long lead, fresh subagent per bounded card, one or two at a time. Skeptics get diff and report, not the lead's narrative. Resume documents beat chat memory.

## Comparison matrix

| Axis | HITL | This package (locked ADRs) |
| --- | --- | --- |
| Product shape | Method + skill + per-project skeleton | Installable library of KiCad capabilities |
| Design home | Python generator | KiCad files plus project and library context |
| Write model | Full generate / rewrite of outputs | Source-preserving localized edit (ADR 0003) |
| Lifecycle | Pipeline run is the unit | Open, read, modify, validate, write, close (ADR 0008, 0011) |
| Executive | `Board.run()` sequences many jobs | Primitives only; client or recipes own sequence (ADR 0009) |
| Hierarchy / existing trees | Weak; greenfield flat generate | Core project and schematic model |
| Library tables / `${VAR}` | Minimal seed tables for CLI | First-class area (ADR 0002) |
| Connectivity | Buried in parity and gates | Client before/after `netlist()` compare |
| Reuse across apps | Copy templates into each repo | One package, many consumers after 1.0 |
| Agent host concerns | In-repo swarm, slots, hooks | Out of package; host or MCP server owns them |
| License | HIL-ASA-1.0 (not OSI; tooling share-alike) | MIT |

## Adversarial pressure on our decisions

Use this section in a short adversary session. Attack the claim, not the prose.

### Claims that hold under HITL pressure

| Claim | Why HITL does not overturn it |
| --- | --- |
| ADR 0003 lossless sexpr core | HITL's string writers work for generate-only boards and still carry format-drift and SWIG footguns. They are not a substitute for edit-in-place donors. |
| ADR 0008 / 0011 artifact lifecycle | HITL has no open/edit/discard/revert story for living multi-sheet projects. Our donors need that story. |
| ADR 0009 primitives, not an executive | HITL's strength for agents is a monolythic pipeline. That strength is exactly why it cannot be this package. Clients must compose gates. |
| ADR 0002 functional TOC | HITL folds PCB generate, fab, CAD fit, and distributor into one board story. Our consumers split BOM, ERC, tables, and edits across products. |
| ADR 0005 / 0006 package-first, cutover later | HITL copies a skeleton per project. Shared I/O still needs one home or each app relearns KiCad footguns. |
| ADR 0007 private CLI discovery | HITL rediscovers install roots and env names inside the skeleton. Confirms the need for one private rule; does not justify a public `cli` module. |
| Serial decision spine / limited swarm | HITL's token autopsy supports our bias against unbound parallel implementation swarms on policy work. |

### Claims worth attacking (do not treat as settled by this note)

| Pressure | Possible crack | What would change if the crack is real |
| --- | --- | --- |
| "Nobody needs generator-first in this estate" | Agents and greenfield breakouts may want board-as-code without living in eeschema | A **consumer or post-1.0 recipe family**, not a change to the artifact model. Keep generate out of layer-0 nouns. |
| "Recipes module can wait forever" (ADR 0011 D10) | HITL shows agents need named, fail-closed sequences or they invent hidden executives | Still no recipes until a real caller needs one. When needed, prefer visible recipes over buried `save()` policy. Adversary should check whether MCP forces the date earlier. |
| "pcbnew stays out of default scope" (ADR 0006) | HITL board build and zone work depend on `pcbnew` | PCB **edit** and some exports may need a documented exception later. Do not smuggle `pcbnew` into symbol or schematic cores. |
| "Peer lock is only a query" | Agent fleets racing the GUI need stronger social rules | Package rule can stay query-only. Host or MCP session policy may refuse writes when locked. Do not silently re-bundle lock into `save()`. |
| "Connectivity verify is only client sequence" | HITL refuses fab without parity; agents skip steps under pressure | Keep compare as client or recipe. MCP composite tools must make the gate **visible** and default-on for release paths, not hidden inside primitive save. |
| Map has no agent/MCP ticket | Long-term goal is a full-featured agent MCP; map #1 is package foundation | Post-1.0 anchor is ADR 0012 (proposed). Do not open a MCP implementation epic before 1.0 capability bar unless the owner reopens scope. |
| Isolation is "just ops" | Without profile isolation, headless agents corrupt the GUI home | Package may grow a **private** isolate helper used by engine-backed ops and by a future MCP server runner. Not a public workflow API. |
| Structured gate evidence is out of scope | Chat claims of "DRC clean" are unreliable | Results-shaped return values belong at MCP and CI edges. Primitives already return typed objects; do not invent a second report framework inside the library. |

### Map and operating-model checks

| Map / AGENTS rule | HITL signal | Adversary question |
| --- | --- | --- |
| One ticket / serial decision spine | Chain default after swarm cost | Are we still tempted to parallelize grilling because "agents are cheap"? |
| Donor tests move with lifts | HITL freezes SES and results JSON as evidence | Do our functional gates leave machine-readable artifacts agents can re-read without chat? |
| No CI cathedral before foundation | HITL ships a full CI matrix in the skeleton | Are we under-investing in **portable** gate scripts at the consumer edge, or correctly deferring them? |
| Discussion before large policy | HITL encodes protection rules as machine checks after human misses (TVS-02 lesson) | Which of our DESIGN-level rules exist only in prose and would go green while wrong? |
| Primitives never call recipes | HITL pipeline is the anti-pattern | Has any recent PR re-bundled verify or backup into write? (Re-check ADR 0009 split status.) |
| macOS is a first-class owner machine | HITL is Windows-first, Linux second, macOS light | Do engine-backed tests and docs assume paths we do not run? |

## Steal list (apply outside or beside the package)

1. **Fail-closed release path** — separate inspect from emit-orderables; compose gates in the open.
2. **Structured results** — step verdicts, counts, content hashes; strip volatile Gerber timestamps when comparing.
3. **Headless KiCad isolation** — private runner concern for CLI and any future `pcbnew` use.
4. **Frozen non-deterministic outputs** — router SES or equivalent when generate exists.
5. **No-shortcut audit** — agent hygiene at host or MCP layer (stubs, guesses, empty suites, missing summary lines).
6. **Chain orchestration default** — narrow tools, bounded cards, fresh context, spot-check numbers from files.
7. **Decision ledger** — standing decisions file; do not re-interview every session (aligns with grilling + ADRs).
8. **Adversarial review pass** — second agent with files, not conclusions, before fab or merge of layout-heavy work.
9. **Distributor MPN live check** — domain gate next to BOM tools; not a KiCad file primitive.
10. **Honest skill text** — state cost and what green does **not** mean.

## Reject list (do not pull into this package)

1. Generator-first as the **ontology** of boards and schematics.
2. Monolythic `Board.run()` (or equivalent) as public library API.
3. In-repo swarm harness, usage tripwires, merge locks, overnight chains as package features.
4. Stringly S-expression writers as the shared parse/edit core.
5. "Nobody edits KiCad files" as product truth for SPCoast / FieldUnit / kDoctor worlds.
6. Vendoring large HITL template trees into a commercial MCP without a license review (HIL-ASA-1.0).
7. Windows-only assumptions in core library code.

## Implications for a future MCP (pointer only)

Full tool-surface sketch: [ADR 0012](../adr/0012-future-mcp-tool-surface.md) (proposed, non-binding).

Short form: MCP tools stay thin over public primitives and a few named recipes. HITL-like playbooks live in the MCP server or host skill, not in `kicad_primitives`. Generator-first is one optional workflow, not the document model.

## Sources

| Path | Use |
| --- | --- |
| HITL `README.md`, `docs/METHOD.md`, `docs/PCB.md`, `docs/TOOLS.md`, `docs/LESSONS.md`, `docs/SWARM.md` | Method and lessons |
| HITL `skills/hardware-in-the-loop/SKILL.md` | Agent procedure and mode defaults |
| HITL `templates/pcb/tools/{board_pipeline,kicad_env}.py`, `example_board/gen_example_board.py` | KiCad interaction shape |
| HITL `templates/harness/swarm/AGENT_RULES.md` | Binding agent cage rules |
| This repo `docs/adr/0002`–`0009`, `0011`; `AGENTS.md` | Locked package decisions |

## What this note does not do

- Does not file map tickets or change ADR status.
- Does not authorize `pcbnew`, recipes, or MCP implementation work.
- Does not evaluate HITL as a product to adopt whole.
- Does not replace owner grilling on any crack listed above.
