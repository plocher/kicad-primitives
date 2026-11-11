# HITL adversary session (setup)

Status: complete. Output: [external-survey-synthesis-2026-11-11.md](external-survey-synthesis-2026-11-11.md) (Structured-B: four external notes plus HITL, one synthesis).

Primary checkout: `/Users/jplocher/Dropbox/KiCad/kicad-primitives` is free for #78 (ADR 0010 grilling).

This worktree:

- Path: `/Users/jplocher/Dropbox/KiCad/worktrees/kicad-primitives-hitl-adversary`
- Branch: `docs/hitl-adversary-pass` (from PR #83 / `docs/hitl-mcp-anchor-2026-11-10`)
- PR under review: https://github.com/plocher/kicad-primitives/pull/83

## Mission

Short adversary pass on `docs/review/hitl-comparison-2026-11-10.md` and proposed ADR 0012.

Attack the **claims worth attacking** table and the map checks. Do not implement package code. Do not accept ADR 0012 here.

## Inputs

- `docs/review/hitl-comparison-2026-11-10.md`
- `docs/adr/0012-future-mcp-tool-surface.md`
- Locked ADRs 0002–0009, 0011; `AGENTS.md`
- Optional: HITL clone at `~/Dropbox/workspace/claude-hardware-in-the-loop`

## Expected output

One short note under `docs/review/` (for example `hitl-adversary-2026-11-10.md`) with:

1. Attacks that failed (claim holds)
2. Attacks that landed (crack + recommended follow-up: none / grill / ticket / ADR edit)
3. Whether PR #83 docs need a fix-up commit

Keep findings out of the primary #78 worktree.
