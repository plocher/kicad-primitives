# Changelog

## Unreleased

- Add symbol-library pin `add_pin` / `set_pin` / `delete_pin` on existing `(unit, body_style)` bodies, preserving alternate body styles and ADR 0003 local deltas (`docs/symbol-libraries.md`; #30).
- Add symbol-library `add_property` / `delete_property` for declared fields (private modifier optional), with inheritance-safe boundaries and byte-local deltas (`docs/symbol-libraries.md`; #29).
- Lock the package documentation contract in `docs/DOCUMENTATION.md` (usage pages + docstrings + changelog; generated API reference deferred) and align existing usage pages to the shared section order.
- Add project write lock/guard hooks on `Project` (`lock_file`, `is_locked`, `write_is_permitted`, `ensure_writes_allowed`) with dry-run and in-KiCad bypass (#27).
- Add schematic geometry/electrical structure read on `Schematic` (wires, junctions, labels, global/hierarchical labels, no-connects, sheet edges) for FieldUnit-style ingest (#35).
- Add schematic placed-symbol and title-block read via `Project.schematic` / `Project.schematics` (`kicad_primitives.schematics`): merged fields, uuid, transform, unit, flags; top-level placements only; hierarchy-gated paths (#28).
- Add `kicad_primitives.projects.Project`: open a project directory or `.kicad_pro`, discover optional schematic/PCB companions, list hierarchical schematic files with parent-relative `Sheetfile` resolution, and expose read-only `text_variables` (jBOM donor gates; sheet-walk defect corrected).
- Accept private `kicad-cli` path discovery in ADR 0007: explicit path, then `KICAD_CLI`, platform defaults, `PATH`; lazy hard discovery error; no public `cli` module; `pcbnew` runtime out of scope.
- Accept the 1.0 capability and releasability bar in ADR 0006: macro service surfaces (A), proven cores (B), donor-used floor (C); FieldUnit schematic ingest and symbol authoring in B; functional tests as required evidence; cutover not a gate; deferrals separated from standing exclusions.
- Publish a current lift inventory across the seven functional areas (`docs/review/lift-inventory-2026-10-24.md`), with donor anchors, usage/defect separation, package gaps, and recommended bounded slices.
- Accept distribution and versioning rules in ADR 0005: no released donor dependency before `1.0.0` on public PyPI; pre-1.0 labels informational only; owner WIP via `uv` editable installs and optional Test PyPI probes; no donor version coupling or vendoring.
- Implement explicit-path symbol-library inspection, including private property modifiers, inheritance provenance, immutable snapshots, and unit/body-style pin membership.
- Add byte-localized existing-property edits with reparsing and explicit atomic single-file saves, conflict detection, and link/permission safeguards.
- Port donor behavior tests; add failure/preservation contracts and an opt-in real-library/KiCad gate with a hashed verification record.
- Publish a symbol-library usage recipe and installed typing information; correct ADR 0004's private-property observation.
- Ratify symbol-library inspection and localized existing-property updates as the first functional slice, with its acceptance gates, in ADR 0004 (decision recorded before implementation).
- Accept CircuitDK's source-preserving parser and write contract in ADR 0003, including the verified UUID insertion rule.
- Raise the Python floor to 3.11 and declare the verified `circuitdk-lossless-sexpr==0.1.1` dependency.
- Ratify seven public functional areas and their ownership rules in ADR 0002.
- Keep parsing, text editing, runtime safeguards, and KiCad execution internal.
- Include PCB editing in intended scope, with explicit failure for exposed unimplemented operations.
- Distinguish parity, consumer usability, and package completeness.
