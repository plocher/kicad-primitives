# ADR 0006 acceptance reconciliation (2026-10-27)

Status: owner-reviewed reconciliation record. Evidence for [ADR 0006](../adr/0006-1.0-capability-and-releasability-bar.md). It does not change the A/B/C model.

Baseline: `main` at `86fab47` (PR #61 merged). Inputs: ADR 0006, the [lift inventory](lift-inventory-2026-10-24.md), usage pages under `docs/`, public modules under `src/kicad_primitives/`, and targeted donor checks.

## Problem

ADR 0006 defines the 1.0 bar. It does not record which parts of the bar the package meets today. Without that record, work drifts in two directions: added depth that the bar does not need, and missing items that nobody tracks.

## Method

For each ADR 0006 service row:

1. **A — Surface:** Is the functional boundary stated?
2. **B — Proven core:** Does a working implementation with functional tests exist?
3. **C — Donor floor:** Can current donor-used paths go through the package surface?

Only demonstrated gaps against the existing bar become 1.0 work. Other differences are post-1.0 TBDs.

## Result by service

### Projects — B met

Discovery and open, parent-relative hierarchy, `text_variables`, native peer-lock guards, explicit lifecycle, ZIP history, and bounded save-as (`docs/projects.md`).
A gap: no uniform surface statement ([#67](https://github.com/plocher/kicad-primitives/issues/67)).

### Schematics — B mostly met

Met: merged placed-symbol read, geometry and electrical-structure read, localized `set_attribute`, selected embedded restore, and project ERC (`docs/schematics.md`).

Gaps:

- **Attribute deletion (B repair, C).** jBOM annotate normalization removes alias properties (`normalize_schematic_properties` / `_remove_property`). [#63](https://github.com/plocher/kicad-primitives/issues/63).
- **Schematic SVG export (report/export, C).** Used by kproj `schematic_exporter` and Subdivision `render_plant_picture`. [#64](https://github.com/plocher/kicad-primitives/issues/64).

### Symbol libraries — B mostly met

Met: attribute insert/update/delete; pin add/edit/remove; symbol create, rename, delete, copy, and cross-library copy; graphics anchors (unit-0 shared body, pin placement, body text, SVG inspection) (`docs/symbol-libraries.md`).

Gap:

- **Graphics adjust.** B says authoring must create **and adjust** the harvested structures. Rectangles and body text are add-only today. Owner decision: minimal `set`/`delete` for 1.0. [#66](https://github.com/plocher/kicad-primitives/issues/66).

### Library tables and resolution — B met

Symbol and footprint table discovery, read, resolve, and write; nested tables; `${VAR}` expansion; project shadowing; add/remove/rename; KiCad-aligned URI bases (`docs/tables.md`). `design_block` tables stay thin, as ADR 0006 allows.

### Connectivity — B exchange core met; A undefined

Met: netlist exchange parse, obtain/export, and `connectivity_sets` (`docs/netlist.md`).

Gap:

- **A surface and project-owned obtain.** `obtain_netlist` takes a schematic path, not project context. Owner decision: the 1.0 minimum is a project-owned netlist obtain on the pending snapshot plus the existing exchange model. A live connectivity engine is not required. [#65](https://github.com/plocher/kicad-primitives/issues/65).

### Footprint libraries — not started

Mandatory B: read, identity, list, pad summary, and lineage-compare inputs. [#39](https://github.com/plocher/kicad-primitives/issues/39).

### PCBs — not started

Mandatory B: footprint/pad/title and BOM/fab metadata read, DRC reports, Gerber and drill export. [#34](https://github.com/plocher/kicad-primitives/issues/34).

## Defect and debt ledger

The package addresses all six starting items:

1. Sheet paths resolve relative to the parent sheet.
2. One symbol reader and one schematic reader.
3. Localized source-preserving writes, no whole-file rewrite.
4. One table parser shared by resolution and ERC context.
5. One private `kicad-cli` locator (ADR 0007).
6. Netlist exchange is documented as distinct from project-owned Connectivity.

## Post-1.0 TBDs (owner-confirmed)

These are not 1.0 gaps:

- Symbol unit split or restructure beyond `ensure_body`. Evidence is historical Railroad recipes only.
- Multi-instance sheet models and instance paths. No current donor reads them.
- Polished `design_block` table API.
- Graphics authoring beyond minimal rectangle/text `set`/`delete`.
- Broad KiCad-native capability inventory ([#62](https://github.com/plocher/kicad-primitives/issues/62)).

Existing ADR 0006 deferrals (variants, geometry editing, full artwork and footprint editors, live connectivity) are unchanged.

## Release preparation

`pyproject.toml` metadata predates current practice: version `0.0.0`, a Pre-Alpha classifier, and a description that says "kicad-cli facade", which ADR 0002 rejects. Release preparation updates it, builds and installs the distribution in a clean `uv` environment, and runs the gates before owner approval ([#68](https://github.com/plocher/kicad-primitives/issues/68)). Consumer cutover and CI epics are not gates.

## Remaining 1.0 sequence

1. Small gap tranche: [#63](https://github.com/plocher/kicad-primitives/issues/63), [#64](https://github.com/plocher/kicad-primitives/issues/64), [#65](https://github.com/plocher/kicad-primitives/issues/65), [#66](https://github.com/plocher/kicad-primitives/issues/66).
2. Surface statements: [#67](https://github.com/plocher/kicad-primitives/issues/67). PCB and footprint pages add theirs with their tickets.
3. Footprint library reads: [#39](https://github.com/plocher/kicad-primitives/issues/39).
4. PCB core: [#34](https://github.com/plocher/kicad-primitives/issues/34).
5. Release: [#68](https://github.com/plocher/kicad-primitives/issues/68).

Targeted native KiCad comparisons support each implementation ticket. They do not form a separate gate.
