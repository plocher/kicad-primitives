# Lift inventory (2026-10-24)

Status: research asset for [#9](https://github.com/plocher/kicad-primitives/issues/9). Catalogue only. No code lift.

Baseline: founding survey [`docs/kicad-services-survey-2026-10-12.md`](../kicad-services-survey-2026-10-12.md) (historical evidence; not rewritten).

Governing decisions: ADR 0001–0005. Public TOC: ADR 0002. Write model: ADR 0003. First shipped slice: ADR 0004 (`kicad_primitives.symbols`). Dependency bar: ADR 0005 (no released donor pin before `1.0.0`).

Method: re-check survey harvest paths against live donor checkouts on 2026-10-24; map each ADR 0002 area to donor behavior, tests, defects, package presence, and usage. Usage labels follow ADR 0002: **used** / **unused** / **unimplemented**. Defects are a separate column—not silent policy.

## How to read this document

| Label | Meaning |
| --- | --- |
| Used | Implemented in a donor (or this package) and consumed by a current client workflow |
| Unused | Implemented somewhere, not consumed by a current client |
| Unimplemented | Intended by ADR 0002 scope, absent or only sketched |
| Defect / shortcut | Known wrong behavior or debt; must not be copied as package policy |
| In package | Present in `kicad-primitives` today under accepted ADRs |

This inventory supports later slice choices and an owner-selected 1.0 bar. It does **not** select 1.0 scope, migrate consumers, or authorize lifts.

## Snapshot: package today

Public surface is only `kicad_primitives.symbols.SymbolLibrary` (plus exported error/snapshot types).

| Capability | Status in package |
| --- | --- |
| Explicit-path `.kicad_sym` open | Used foundation (package tests + usage recipe) |
| Declared inspection (properties, pins, bodies/units, private modifier) | Shipped (ADR 0004) |
| Effective inheritance with provenance | Shipped |
| Localized existing-property edit + `to_bytes` / `save` | Shipped |
| Symbol rename, pin edit, property insert/delete, unit split, cross-library copy | Unimplemented (deferred by ADR 0004) |
| Projects, schematics, PCBs, footprints, tables, connectivity | Unimplemented public services |
| Public parser / text / CLI modules | Out of public TOC (private internals only) |

Tests here: `tests/functional/test_symbol_{inspection,editing,persistence}.py`, `tests/unit/test_symbol_internals.py`, opt-in `tests/verify_symbol_libraries.py`, record `docs/review/first-symbol-slice-results.json`.

Donor symbol readers remain in Subdivision/kDoctor; no consumer cutover (ADR 0005).

## Checkout drift vs survey (2026-10-24)

All primary survey harvest paths still exist except:

| Path | Note |
| --- | --- |
| Subdivision `tools/contract/lint_libraries.py` | **Missing** (survey still cites it; `lint_symbol_fields.py` and `symbol_contact_sheet.py` remain) |
| Subdivision `tests/test_contract_lint.py` | **Missing** |

Railroad bulk recipes still at `Railroad/symbols/edits/2026-10-12-four-libraries.py` and `2026-10-13-head-set.py`.

---

## 1. Projects

**Remit (ADR 0002):** design context; settings; access to schematics/PCBs; project-wide operations.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| Discover/resolve `.kicad_pro`, autosave, input shapes | jBOM `project_discovery.py`, `project_file_resolver.py`, `application/pcb_project_loader.py` | jBOM loader/discovery tests under `tests/` (multiple application tests; discovery covered via project loader paths) |
| Hierarchical schematic file list | jBOM `project_context.py` (`get_hierarchical_schematic_files`, lock awareness) | Exercised via BOM/project flows; sheet-walk defects noted below |
| `.kicad_pro` `text_variables` | jBOM `project_variables_reader.py` | `tests/unit/test_project_variables_reader.py` |
| Thin project metadata facade | kproj `kicad_project_reader.py` | Via kproj publish/read paths |
| Lock / plugin write guard | jBOM `common/kicad_runtime.py` | Annotation/write paths; `tests/unit/test_annotate_repairs.py` adjacent |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Project discovery / single-pro directory rules | **Used** (jBOM, kproj) | No |
| Hierarchy file list | **Used** (jBOM BOM/hierarchy) | No |
| text_variables read | **Used** (jBOM) | No |
| Full `.kicad_pro` model (sheets, libraries, ERC settings, variants) | **Unimplemented** | No |
| Sheet instance paths / multi-instance sheets / `sheet_instances` | **Unimplemented** | No |
| Unified project lock API for all writers | Partial **used** in jBOM; prose-only elsewhere | No |

### Defects and shortcuts (not policy)

- jBOM resolves `Sheetfile` children from the **project directory**, not the parent sheet directory (survey §2). Wrong for nested sheet folders.
- Nobody reads sheet instance paths or UUIDs as a first-class model (survey §2–3).
- Map task [#13](https://github.com/plocher/kicad-primitives/issues/13) still open: file/fix sheet-walk defects in jBOM and kproj.

### Lift note

Bring project discovery + variables + hierarchy **with** tests; do not copy the wrong resolution base. Sheet-tree correctness is a prerequisite for honest schematic and connectivity work.

---

## 2. Schematics

**Remit:** inspect/edit schematic content in project context (placed symbols, embedded defs, hierarchy, electrical checks).

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| BOM-oriented placed symbols + title block | jBOM `schematic_reader.py` | `tests/services/readers/test_schematic_reader.py` |
| Property annotation writer (tree + `sexpdata.dumps`) | jBOM `annotation_service.py` | `tests/unit/test_annotate_repairs.py` |
| Placement transform reader | Subdivision `schematic_reader.py` (`SchematicPlacementReader`) | Used by plant parsers; limited direct unit tests |
| Text span helpers on sch/sym | Subdivision `sch_text.py` | No dedicated tests (survey §1.6, §3.1) |
| Symbol instance transfer / renumber power | kDoctor `sch_symbol_transfer.py`, `renumber_power_refs.py` | Scripts; verification notes, not a suite |
| Title-block convention audit | kproj `metadata_analyzer.py`; kDoctor `check_metadata_conventions.py` | kproj service tests / scripts |
| ERC run + JSON findings | kproj `design_analyzer.py` | `tests/contract/test_kicad_cli_erc.py` |
| ERC interpretation / nearest ref | kDoctor `erc_drc_summary.py` | Pathfinding scripts/reports |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Read placed symbol fields for BOM | **Used** (jBOM) | No |
| Read placement transform | **Used** (Subdivision plant tools) | No |
| Annotate/repair fields via whole-file rewrite | **Used** (jBOM annotate CLI) | No (and wrong write philosophy for this package) |
| Wires, labels, junctions, no-connects, sheets nodes | **Unimplemented** as a model | No |
| Placed unit, pins, `instances` paths | **Unimplemented** | No |
| Embedded `lib_symbols` edit/cache sync | **Unimplemented** | No |
| Project-scoped ERC as schematic/project operation | Runner **used** (kproj); ownership model not packaged | No |

### Defects and shortcuts

- Three partial views of one placed-symbol node (jBOM / Subdivision / kDoctor); none is complete (survey §2).
- jBOM write path reformats the entire schematic (`sexpdata.dumps`)—unsuitable as package write policy (ADR 0003).
- kproj sheet token `(sheetfile` does not match KiCad 10 `(property "Sheetfile" ...)` (survey §1.3, §2).
- `sch_text` quote/`\"` truncation and tab-depth coupling (survey §3.1)—partially superseded for **libraries** by this package; still relevant if ported for schematics.

### Lift note

Prefer a **read** merge of BOM fields + transform + identity first. Edits must use ADR 0003 localized writes, not jBOM dumps. Schematic electrical checks belong with project/schematic services, not a public `checks` module (ADR 0002).

---

## 3. PCBs

**Remit:** inspect/edit board content in project context; DRC ownership on the board/project.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| Footprints, pads, layers, origins, title | jBOM `pcb_reader.py` | `tests/unit/test_pcb_reader.py` |
| DRC JSON runner | kproj `design_analyzer.py` | `tests/contract/test_kicad_cli_drc.py` |
| DRC interpretation | kDoctor `erc_drc_summary.py` | Scripts |
| PCB exports (gerber/render/step) | jBOM `gerber_service.py`; kproj `pcb_exporter.py` | kproj `tests/contract/test_pcb_exporter.py` |
| Zone fill via `pcbnew` | jBOM plugin only | Plugin path |
| Placed footprint vs master diff | kDoctor `footprint_lineage_service.py` | Pathfinding; thin tests |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| PCB read for BOM/fab metadata | **Used** (jBOM) | No |
| DRC run | **Used** (kproj publish) | No |
| Full board edit model | **Unimplemented** | No |
| Design-block board linkage | kDoctor spike (**used** in pathfinding, not a product API) | No |

### Defects and shortcuts

- PCB reader is partial; not a board editor (ADR 0002 already states this).
- Plugin `pcbnew` path is environment-specific; not a portable package default.
- Footprint lineage coordinate-frame caveats are documented in kDoctor docstrings—carry as explicit limits, not silent assumptions.

### Lift note

PCB **editing** is intended scope but low donor maturity. A first PCB slice would likely be **read + DRC/export facade**, not geometry editing. Depends on project context and (for exports) CLI policy (#12).

---

## 4. Symbol libraries

**Remit:** inspect/edit reusable symbol definitions and library collections.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| Flattened sexpdata reader | Subdivision `symbol_library_reader.py` | `tests/test_kicad_plant_graph.py` (`SymbolLibraryReaderTests`) |
| Regex unit/extends/locked view | Subdivision `sch_text.library_symbols` | Overview + lint consumers; `tests/test_kicad_library_overview.py` |
| Field lint / contact sheet | `tools/contract/lint_symbol_fields.py`, `symbol_contact_sheet.py` | overview tests; contact sheet is tooling |
| Inheritance/pin-kind diff vs cache | kDoctor `symbol_lineage_service.py` | Scripts (`poc/test_symlib_fix.py`) |
| Name/properties/pin-count context | EagleLib2KiCad `kicad_library_context_service.py` | curation harness tests |
| Bulk property and structural recipes | Railroad `symbols/edits/*.py`; retired Subdivision `apply_symbol_recipe.py` (git `3325807`) | Dated scripts / archive |

### Package (ADR 0004) — already lifted and improved

| Capability | Usage | Notes |
| --- | --- | --- |
| Explicit-path inspect + resolve | **Used** by package tests/recipe; **not** yet by donors | Supersedes silent flatten/extends-ignore for this surface |
| Existing declared property edit + atomic save | Package-only until donor probe/cutover | |
| Rename/copy/split/add pin/graphics model | **Unimplemented** in package; recipes show **used** demand in Railroad/Subdivision history | |

### Defects and shortcuts (donor — do not re-inherit)

Survey §3.1 and ADR 0004 evidence remain the defect list for **remaining** donor code:

1. Standard properties dropped by `sch_text.library_symbols`.
2. Quote-truncating property regex.
3. Pins flattened across units; unit 0 undocumented.
4. No pin `hide` / body style in donor readers (package exposes more pin/body fields).
5. Dual disagreeing readers in Subdivision.
6. Forward `extends` to a later parent broke overview pin lists (ADR 0004 evidence).

Package acceptance deliberately fixed inspection/inheritance/property-edit gates. Structural library editing remains open.

### Lift note

**Next symbol slices** should extend the existing `SymbolLibrary` service (property insert/delete, pin ops, rename, copy) rather than port `sch_text` as a second public model. Bring recipe tests as behavioral gates; keep Railroad policy out of the package.

---

## 5. Footprint libraries

**Remit:** inspect/edit reusable footprint definitions and collections.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| Placed vs `.kicad_mod` master diff | kDoctor `footprint_lineage_service.py` | Pathfinding |
| `.pretty` enumerate + pad count | EagleLib2KiCad `kicad_library_context_service.py` | unit/harness tests |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Footprint lineage diff | **Used** in kDoctor spikes | No |
| Pad-count / list context | **Used** in EagleLib2KiCad closure reports | No |
| Full `.kicad_mod` read/edit model | **Unimplemented** | No |
| Footprint library writes | **Unimplemented** | No |

### Defects and shortcuts

- Diff-oriented, not a definition editor.
- 3D models out of scope until requested (ADR 0002).

### Lift note

Low maturity. A first footprint slice is **read model + path identity**, parallel to early symbol inspection, after tables/resolution can locate `.pretty` trees.

---

## 6. Library tables and resolution

**Remit:** registrations; resolve references with global/project context. Not definition content.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| Global/project sym/fp tables, `${VAR}` from `kicad_common.json` + pro overrides, add/remove/rename | EagleLib2KiCad `kicad_environment_service.py` | `tests/unit/test_kicad_environment_service.py` |
| Nested `Table` entries; hard-coded `${KICAD10_*}` | kDoctor `symbol_lineage_service._parse_sym_lib_table` | Scripts |
| Classify internal/external lib refs (regex) | kproj `kicad_libraries.py` | `tests/unit/common/test_kicad_libraries.py` |
| design_block_lib_table / block drift | kDoctor `design_block_service.py` | `poc/tests/test_design_block_service.py` |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Resolve configured libraries with real vars | **Used** (EagleLib2KiCad conversion/curation) | No |
| Nested tables | **Used** in kDoctor lineage | No |
| Lib-table write | **Used** (EagleLib2KiCad) | No |
| `design_block_lib_table` as first-class | Spike **used** in kDoctor | No |
| Single precedence model (global/project/env) | **Unimplemented** as one package API | No |

### Defects and shortcuts

- Three parsers (Eagle full, kDoctor nested, kproj classify-only).
- kDoctor variable expansion uses hard-coded macOS defaults—not general resolution.
- kproj classification is not resolution.

### Lift note

Strong donor candidate for an early **non-symbol** slice: read+resolve (+ optional write) under ADR 0003 byte rules for table files. Depends on environment/config discovery, not on full project schematic model. Lookup precedence still needs an owner lock (open map/grilling territory; do not invent here).

---

## 7. Connectivity

**Remit:** obtain/inspect/trace/compare electrical connections in project context; netlists as exchange datasets.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| kicadsexpr netlist parse | Subdivision `netlist_reader.NetlistReader` | `tests/test_kicad_plant_graph.py` (`NetlistReaderTests`) |
| `sch export netlist` wrapper | Subdivision `KicadCliNetlistExporter` | `KicadCliExporterSmokeTests` |
| Net-for-net compare / unify check | archive `docs/archive/unify/build_spcoast.py`; `tools/contract/netlist_diff.py` | Archive/scripts |
| Consumers | plant/controller parsers, link tools, render | Integration via those tools |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Parse exported netlist | **Used** (Subdivision compilers) | No |
| Export netlist via CLI | **Used** | No |
| Live connectivity from loaded schematic without export | **Unimplemented** | No |
| Connectivity-preserving edit gate (ADR 0003) | Policy only; needs service | No |

### Defects and shortcuts

- Only netlist path today; freshness/provenance of `.net` files is a consumer problem (Subdivision #23 frozen desk net noted in survey).
- Multiple CLI locators (`KICAD_CLI` vs others)—package must not fork another without #12.

### Lift note

High value, strong tests relative to size. Natural slice: **netlist read model + optional export**, private CLI. Full “trace without export” waits on richer schematic model. Connectivity compare is a gate helper for later schematic edits.

---

## Cross-cutting internals (not public TOC)

These support services; ADR 0002 keeps them private.

| Concern | Strongest donor | Package stance |
| --- | --- | --- |
| S-expression read/edit representation | CircuitDK `lossless_sexpr` (ADR 0003) | **In package** private; do not add jBOM sexpdata / Eagle sexp / kDoctor regex as peers |
| Byte-preserving spans | Subdivision `sch_text` (legacy) | Superseded for symbols by CircuitDK spans; schematic port still open |
| kicad-cli locator + exports | kproj `kicad_install` + exporters | Unimplemented here; grilling [#12](https://github.com/plocher/kicad-primitives/issues/12) |
| Runtime lock/plugin | jBOM `kicad_runtime` | Unimplemented here |
| ERC/DRC interpretation | kDoctor on kproj runner | Belongs with project/document checks when lifted |

**Defect:** five+ CLI locators and two env names (`KPROJ_KICAD_CLI` vs `KICAD_CLI`). **Shortcut:** treating `cli` as a public module (rejected by ADR 0002).

---

## Matrix: intended area × maturity

| Area | Donor maturity | Package | Blocking dependencies for a useful slice |
| --- | --- | --- | --- |
| Symbol libraries | High (and partially superseded) | **Partial (ADR 0004)** | None for further symbol ops |
| Connectivity (netlist) | Medium-high | None | Private CLI helper; project path optional for export |
| Library tables/resolution | Medium-high | None | Config home / var policy (precedence lock) |
| Projects | Medium | None | Fix sheet-walk facts (#13); define pro coverage |
| Schematics (read) | Medium (fragmented) | None | Project hierarchy; write model already chosen |
| Schematics (edit) | Medium but wrong write path | None | Localized sch writes; connectivity gates for electrical edits |
| PCBs (read/DRC) | Medium | None | Project; CLI |
| PCBs (edit) | Low | None | Large model gap |
| Footprint libraries | Low | None | Tables/resolution to find libraries |

---

## Recommended bounded implementation slices

Ordered for **decision support**, not a committed roadmap. Each slice should stay vertical: one client outcome, donor tests moved or rewritten as gates, ADR 0003 writes where editing appears. No consumer cutover (ADR 0005).

### S1 — Extend symbol-library editing (same service)

- **Outcome:** property insert/delete and/or pin number/name/type edits and/or rename within one `.kicad_sym`, still explicit-path.
- **Depends on:** ADR 0004 surface (done).
- **Donor anchors:** retired recipe ops; Railroad edit scripts; overview/lint expectations.
- **Why next:** live Railroad/Subdivision demand; reuses parser/persist; no project model required.
- **Avoid:** boiling the ocean (all recipe ops in one PR).

### S2 — Connectivity: netlist inspect (+ optional export)

- **Outcome:** parse kicadsexpr netlist; optional `sch export netlist` behind private CLI.
- **Depends on:** provisional CLI locator policy (#12) if export is included; read-only parse can land first with fixtures only.
- **Donor anchors:** `NetlistReaderTests`, exporter smoke, `netlist_diff.py` ideas.
- **Why:** only connectivity implementation in the estate; feeds later schematic edit gates.

### S3 — Library tables read/resolve (then optional write)

- **Outcome:** load global/project sym/fp tables; resolve `${VAR}`; list nicknames → paths.
- **Depends on:** owner-facing precedence/env rules (small grilling or spike); nested tables from kDoctor.
- **Donor anchors:** EagleLib2KiCad environment tests; kDoctor nested examples.
- **Why:** unlocks “open library by nickname” and footprint discovery without sys.path corpora.

### S4 — Project context: discovery + hierarchy (correct sheet paths)

- **Outcome:** open project by path; list schematic files with correct relative resolution; text_variables.
- **Depends on:** #13 sheet-walk fixes filed/fixed in donors or reimplemented cleanly here.
- **Donor anchors:** jBOM project tests/flows; kproj project reader.
- **Why:** prerequisite for honest schematic multi-sheet work.

### S5 — Schematic placed-symbol read (merged view)

- **Outcome:** one instance record: fields, uuid, transform, unit if present; title block.
- **Depends on:** S4 for multi-sheet; ADR 0003 representation for future edits.
- **Donor anchors:** jBOM schematic reader tests + Subdivision placement consumers.
- **Why:** collapses three partial views; still read-only.

### S6 — Schematic localized field edit

- **Outcome:** set existing placed-symbol property without whole-file reformat; lock-file guard.
- **Depends on:** S5; runtime lock port; optional connectivity gate later.
- **Donor anchors:** jBOM annotate scenarios (behavior only—not dumps writer); kDoctor renumber netlist-identical idea.
- **Why:** replaces the most harmful write path donors still use.

### S7 — PCB read + DRC/export facade

- **Outcome:** footprint/pad/title read; DRC JSON findings; selected exports.
- **Depends on:** S4; #12 CLI.
- **Donor anchors:** jBOM pcb_reader tests; kproj DRC/export contracts.
- **Why:** useful without claiming board editing.

### S8 — Footprint library read model

- **Outcome:** open `.kicad_mod` / list `.pretty` with stable identity and pad summary.
- **Depends on:** S3 for resolution; PCB lineage only as evidence.
- **Why:** completeness for library TOC; lower urgency than S1–S5 for current clients.

### Explicitly later / larger

- Full schematic geometry (wires/labels/sheets).
- PCB geometry editing.
- Live connectivity without netlist export.
- Structural symbol library ops beyond a thin S1 series.
- design_block tables as productized API.
- Public CLI module (rejected); KiCad 11 IPC facade (design note only).

---

## Facts needed for an owner-selected 1.0 bar

ADR 0002/0005: owner locks 1.0 completeness. This inventory does not. Useful inputs:

1. **Parity set:** which **used** donor capabilities must work through this package before any post-1.0 cutover (BOM path? netlist compilers? lib-table manager? annotate?).
2. **Must-fix defects:** sheet-walk, dual symbol readers, whole-file schematic rewrite—which are 1.0 blockers vs accepted limits?
3. **Edit surface minimum:** is symbol property edit + one schematic field edit enough, or must pin/symbol structural edits ship?
4. **Resolution policy:** global vs project table precedence and env var names (#12 adjacent).
5. **CLI necessity:** which exports/ERC/DRC are in 1.0 vs “invoke kicad-cli yourself”?
6. **Verification gates:** byte round-trip only vs netlist-identical vs KiCad resave stability (per operation type, ADR 0003).
7. **Consumer offer order:** still map [#6](https://github.com/plocher/kicad-primitives/issues/6); 1.0 bar should list which donor is the first **offer**, not force migration (ADR 0005).
8. **Out of scope confirmations:** 3D, fab orchestration, railroad compilers, variants (jBOM #382 / kproj #66)—remain excluded unless owner adds them.

---

## Suggested decision uses

| Decision | Use this inventory to… |
| --- | --- |
| Next implementation ticket | Pick one of S1–S8; open a scoped issue with donor paths + tests |
| 1.0 grilling | Answer the eight fact questions; mark each matrix cell in/out |
| #12 CLI grilling | See cross-cutting locator multiplicity and S2/S7 dependence |
| #13 sheet-walk task | Treat as S4 prerequisite evidence, not a silent reimplementation debt |
| #6 migration order | Remember cutovers wait for 1.0+; probes only before then |

## Non-goals of this asset

- No code copy into `src/`.
- No 1.0 scope lock.
- No consumer `pyproject` changes.
- No rewrite of the 2026-10-12 survey.

## Provenance

- Survey 2026-10-12 paths rechecked 2026-10-24 on local Dropbox/workspace checkouts.
- Package surface from `src/kicad_primitives/` and ADR 0004 implementation note.
- Open map tickets at research time: #1, #6, #8, #9, #12, #13 (plus closed distribution #7).
