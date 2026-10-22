# ADR 0001: Package identity

Date: 2026-10-19  
Status: Accepted  
Ticket: [#2](https://github.com/plocher/kicad-primitives/issues/2)
## Amendment: 2026-10-22

[ADR 0003](0003-source-preserving-parser-and-writes.md) supersedes this record's original Python floor and conditional parser choice.
The current floor is Python 3.11+. The parser dependency is `circuitdk-lossless-sexpr==0.1.1`, not `sexpdata`.
The original options and decision below remain as history. Other identity decisions are unchanged.

## Problem

Several owner repos each implement pieces of KiCad project and library I/O. This effort puts that work in one stand-alone package. Before code ports, packaging and docs need a single identity: distribution name, import name, license, Python floor, runtime dependencies, and KiCad version contract. Wrong names or license later force renames across consumers.

## Constraints and requirements

- The package is the long-term home for shared KiCad I/O services (not a side folder under jBOM).
- kDoctor architecture already names the layer `kicad-primitives`.
- jBOM MIT direction (see jBOM #335) and kDoctor Phase 2 assume MIT for extraction.
- Owner machine and consumers use modern CPython; KiCad 10 is the active desktop target.
- Identity must be readable from README, `pyproject.toml`, and this ADR without contradiction.

## Definition of done

- One accepted identity record.
- README, `AGENTS.md`, `pyproject.toml`, and `LICENSE` match that record.
- Import package name is importable once a skeleton exists (`kicad_primitives`).

## Options

### A — Match kDoctor / survey seed

- Distribution: `kicad-primitives`
- Import: `kicad_primitives`
- License: MIT
- Python: 3.10+
- KiCad: 10 write/edit; file `(version …)` is the format contract; older formats read-only when cheap
- Runtime: `sexpdata` allowed if the chosen read parser keeps it (parser choice is a later ticket)

### B — Nested under jBOM namespace

- e.g. distribution `jbom-kicad` / import `jbom.kicad`

Rejected: implies jBOM ownership; fights stand-alone map destination and multi-consumer story.

### C — Different public name (`kicad-services`, `kicad-io`)

Rejected: renames away from existing kDoctor and survey vocabulary for no gain.

## Decision

**Option A.**

| Field | Value |
| --- | --- |
| Distribution name (PyPI / project name) | `kicad-primitives` |
| Import package | `kicad_primitives` |
| License | MIT |
| Python | `>=3.10` |
| KiCad product target | KiCad **10** for write and edit |
| Format contract | S-expression `(version …)` (and related file format versions) in each file |
| Older KiCad formats | Read-only when cheap; not a write target |
| Declared runtime dependency (conditional) | `sexpdata` — only if the accepted read parser uses it |
| Repo role | Sole long-term home for shared KiCad I/O primitives; donor repos become consumers or delete copies |

## Consequences

- Bootstrap and lift work use these names without further debate.
- Parser ADR may add or drop `sexpdata` without renaming the package.
- Consumer `pyproject` entries will depend on `kicad-primitives` once published or path-installed.
