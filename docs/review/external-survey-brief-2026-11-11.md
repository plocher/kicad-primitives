# External KiCad-agent survey brief (2026-11-11)

Status: research brief for four parallel review notes. Not an ADR. Not policy.

Method: Structured-B. Four research agents each review one external project with the same rubric. The lead then writes one synthesis matrix and one critical review of `kicad-primitives`. HITL is already reviewed (`docs/review/hitl-comparison-2026-11-10.md`) and is the fifth input.

## Subjects

| Name | Local clone (read-only) | Upstream |
| --- | --- | --- |
| kicad-happy | `~/Dropbox/workspace/kicad-happy` | https://github.com/aklofas/kicad-happy |
| kicad-mcp-server (Seeed) | `~/Dropbox/workspace/kicad-mcp-server` | https://github.com/Seeed-Studio/kicad-mcp-server |
| KiCad-AI-Assistant | `~/Dropbox/workspace/KiCad-AI-Assistant` | https://github.com/paul356/KiCad-AI-Assistant |
| KiCadAI | `~/Dropbox/workspace/KiCadAI` | https://github.com/dshills/KiCadAI |

## Our side (read these first, briefly)

In this worktree (`/Users/jplocher/Dropbox/KiCad/worktrees/kicad-primitives-hitl-adversary`):

- `AGENTS.md` (locked package rules)
- `docs/adr/README.md` (ADR index)
- `docs/adr/0003`, `0008`, `0009`, `0011` (write model, artifacts, primitives, schematic model)
- `docs/adr/0012-future-mcp-tool-surface.md` (proposed MCP anchor, not accepted)
- `docs/review/hitl-comparison-2026-11-10.md` (exemplar: copy its shape and tone)

## Rules

1. Read-only on the external clone. Do not install, build, or run its servers. Running a read-only script or test only when cheap and safe is allowed but not required.
2. Write exactly one file: your assigned note path. Do not edit any other file.
3. Do not run git commands that change state (no add, commit, checkout, stash, branch). The lead commits.
4. Do not edit `src/`, ADRs, AGENTS, CHANGELOG, or the HITL note.
5. Describe and pressure-test. Do not propose package redesigns. Recommendations name a follow-up kind only: none, grill, ticket, or ADR 0012 wording.
6. Separate fact from inference. Cite file paths (and line ranges when useful) in the external repo for every load-bearing claim. Mark README-only claims as "README claim, not verified in code".
7. STE-flavored prose: short sentences, active voice, no marketing words.
8. Time box: aim for a complete note, not an exhaustive audit. Breadth on the rubric beats depth on one module.

## Required note sections (in this order)

1. **Title and status line** (`Status: research input for Structured-B synthesis. Not an ADR.`)
2. **What it is** — product shape (skill pack / MCP server / KiCad plugin / generator / other), language, license, KiCad version target, activity, maturity signals.
3. **How it touches KiCad** — parse model (own sexpr parser? regex? sexpdata? KiCad API?), `kicad-cli` use, `pcbnew` / SWIG use, KiCad IPC use, direct file generation, write vs read-only, byte preservation, hierarchy support, library tables and `${VAR}`, netlist / connectivity method. State limits.
4. **API / tool surface** — the agent-facing surface (skills, MCP tools, plugin commands, CLI). List the main tools or commands with one line each. Note granularity: one-job vs composite.
5. **Agent and tooling glue** — what lives in prompts/skills versus code; gates and refusal behavior; evidence shape returned to the agent (structured vs prose); session state; versioning/rollback; token or context management.
6. **Comparison matrix** — same axes as the HITL note: product shape, design home, write model, lifecycle, executive vs primitives, hierarchy, library tables, connectivity, reuse, agent host concerns, license.
7. **Pressure on our decisions** — two tables like the HITL note: "Claims that hold" and "Claims worth attacking" against ADR 0003, 0008, 0009, 0011, and proposed 0012. Include a column "what would change if the crack is real".
8. **Steal list** and **Reject list** (outside or beside the package; never "pull into kicad_primitives" without saying which layer).
9. **Overlap with our donors** — where it duplicates jBOM, kproj, kDoctor, EagleLib2KiCad, or FieldUnit-Subdivision jobs (one short table).
10. **Sources read** — table of paths actually read, and what was only skimmed.
11. **Confidence and gaps** — what you could not verify and why.

## Output paths

| Agent | Note path (relative to the worktree) |
| --- | --- |
| kicad-happy | `docs/review/ext-kicad-happy-2026-11-11.md` |
| seeed-mcp | `docs/review/ext-seeed-kicad-mcp-server-2026-11-11.md` |
| ai-assistant | `docs/review/ext-kicad-ai-assistant-2026-11-11.md` |
| kicadai | `docs/review/ext-kicadai-2026-11-11.md` |

## Handoff

When done, send the lead a short completion message:

- the note path
- the five most important findings (one line each)
- the top two "claims worth attacking" for our ADRs
- anything you could not verify
