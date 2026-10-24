# Lift inventory (2026-10-24)

Status: research asset for [#9](https://github.com/plocher/kicad-primitives/issues/9). Catalogue only. No code lift.

Baseline: founding survey [`docs/kicad-services-survey-2026-10-12.md`](../kicad-services-survey-2026-10-12.md) (historical evidence; not rewritten).

Governing decisions: ADR 0001–0005. Public TOC: ADR 0002. Write model: ADR 0003. First shipped slice: ADR 0004 (`kicad_primitives.symbols`). Dependency bar: ADR 0005 (no released donor pin before `1.0.0`).

Method: re-check survey harvest paths against live donor checkouts on 2026-10-24; map each ADR 0002 area to donor behavior, tests, defects, package presence, and usage. Defects are a separate dimension—not silent policy.

## How to read this document

| Label | Meaning |
| --- | --- |
| Used | Implemented and consumed by a **current** client workflow (named caller) |
| Historical demand | Implemented behavior or past recipes that once drove work; not proof of current callers |
| Shipped (package) | Present in `kicad-primitives` with package tests/recipe; **not** the same as Used by a donor |
| Usage unverified | Implemented somewhere; this pass did not establish current callers |
| Unused | Implemented and confirmed **not** consumed by current clients |
| Unimplemented | Intended by ADR 0002 scope (or a natural sub-capability) and absent in that row’s “In package” / donor sense as stated |
| Defect / shortcut | Known wrong behavior or debt; must not be copied as package policy |
| In package | Present in `kicad-primitives` today under accepted ADRs |

**Unused investigation (this pass):** no capability was confirmed unused. Where callers were not traced, the label is **Usage unverified** or **Historical demand**, not Unused. Do not treat spikes as automatically unused.

**Path convention:** harvest tables use **donor-rooted** paths (`jBOM/...`, `kproj/...`, `kDoctor/...`, `EagleLib2KiCad/...`, `FieldUnit-Subdivision/...`, `Railroad/...`). Package paths use this repo root.

This inventory supports later slice choices and an owner-selected 1.0 bar. It does **not** select 1.0 scope, migrate consumers, or authorize lifts.

## Snapshot: package today

Public surface is only `kicad_primitives.symbols.SymbolLibrary` (plus exported error/snapshot types).

| Capability | Status in package |
| --- | --- |
| Explicit-path `.kicad_sym` open | **Shipped (package)** — tests + usage recipe; no donor cutover |
| Declared inspection (properties, pins, bodies/units, private modifier) | **Shipped (package)** (ADR 0004) |
| Effective inheritance with provenance | **Shipped (package)** |
| Localized existing-property edit + `to_bytes` / `save` | **Shipped (package)** |
| Symbol rename, pin edit, property insert/delete, unit split, cross-library copy | **Unimplemented** here (deferred by ADR 0004); see donor historical recipes |
| Projects, schematics, PCBs, footprints, tables, project-owned connectivity services | **Unimplemented** public services here |
| Public parser / text / CLI modules | Out of public TOC (private internals only) |

Tests here: `tests/functional/test_symbol_{inspection,editing,persistence}.py`, `tests/unit/test_symbol_internals.py`, opt-in `tests/verify_symbol_libraries.py`, record `docs/review/first-symbol-slice-results.json`.

Donor symbol readers remain in Subdivision/kDoctor; no consumer cutover (ADR 0005).

## Checkout drift vs survey (2026-10-24)

All primary survey harvest paths still exist except:

| Path | Note |
| --- | --- |
| `FieldUnit-Subdivision/tools/contract/lint_libraries.py` | **Missing** (survey still cites it; `lint_symbol_fields.py` and `symbol_contact_sheet.py` remain) |
| `FieldUnit-Subdivision/tests/test_contract_lint.py` | **Missing** |

Railroad bulk recipes still at `Railroad/symbols/edits/2026-10-12-four-libraries.py` and `Railroad/symbols/edits/2026-10-13-head-set.py`.

---

## 1. Projects

**Remit (ADR 0002):** design context; settings; access to schematics/PCBs; project-wide operations.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| Discover/resolve `.kicad_pro`, autosave, input shapes | `jBOM/src/jbom/services/project_discovery.py`, `jBOM/src/jbom/services/project_file_resolver.py`, `jBOM/src/jbom/application/pcb_project_loader.py` | `jBOM/tests/test_project_discovery.py`; `jBOM/tests/test_project_file_resolver.py` |
| Hierarchical schematic file list | `jBOM/src/jbom/services/project_context.py` (`get_hierarchical_schematic_files`, lock awareness) | `jBOM/tests/test_project_context.py` (hierarchy case ~line 49+) |
| `.kicad_pro` `text_variables` | `jBOM/src/jbom/services/project_variables_reader.py` | `jBOM/tests/unit/test_project_variables_reader.py` |
| Thin project metadata facade | `kproj/src/kproj/services/kicad_project_reader.py` | Exercised via kproj publish/read paths (usage of this facade: **Usage unverified** as a standalone product surface) |
| Lock / plugin write guard | `jBOM/src/jbom/common/kicad_runtime.py` | Used beside annotate/write; see `jBOM/tests/unit/test_annotate_repairs.py` |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Project discovery / single-pro directory rules | **Used** — jBOM loaders/CLI; kproj wraps resolution | No |
| Hierarchy file list | **Used** — jBOM project/BOM hierarchy | No |
| text_variables read | **Used** — jBOM | No |
| Full `.kicad_pro` model (sheets, libraries, ERC settings) | **Unimplemented** as one model | No |
| KiCad variants (project/export variant selection) | **Unimplemented** / **undecided** for package coverage (jBOM #382, kproj #66 are spikes; **not** an ADR exclusion) | No |
| Sheet instance paths / multi-instance sheets / `sheet_instances` | **Unimplemented** | No |
| Unified project lock API for all writers | **Used** inside jBOM write paths; other donors mostly prose | No |

### Defects and shortcuts (not policy)

- jBOM resolves `Sheetfile` children from the **project directory**, not the parent sheet directory (survey §2). Wrong for nested sheet folders.
- Nobody reads sheet instance paths or UUIDs as a first-class model (survey §2–3).
- Map task [#13](https://github.com/plocher/kicad-primitives/issues/13) still open: file/fix sheet-walk defects in jBOM and kproj.

### Lift note

Bring project discovery + variables + hierarchy **with** their tests; do not copy the wrong resolution base. Sheet-tree correctness is a prerequisite for honest multi-sheet schematic work. Variants stay undecided coverage, not “out of scope by ADR.”

---

## 2. Schematics

**Remit:** inspect/edit schematic content in project context (placed symbols, embedded defs, hierarchy, electrical checks).

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| BOM-oriented placed symbols + title block | `jBOM/src/jbom/services/schematic_reader.py` | `jBOM/tests/services/readers/test_schematic_reader.py` |
| Property annotation writer (tree + `sexpdata.dumps`) | `jBOM/src/jbom/services/annotation_service.py` | `jBOM/tests/unit/test_annotate_repairs.py` |
| Placement transform reader | `FieldUnit-Subdivision/tools/kicad_services/schematic_reader.py` (`SchematicPlacementReader`) | Callers include Subdivision plant parsers; limited direct unit tests |
| Text span helpers on sch/sym | `FieldUnit-Subdivision/tools/kicad_services/sch_text.py` | No dedicated tests (survey §1.6, §3.1) |
| Symbol instance transfer / renumber power | `kDoctor/poc/sch_symbol_transfer.py`, `kDoctor/poc/renumber_power_refs.py` | Scripts; verification notes, not a suite |
| Restore embedded `lib_symbols` entry from parent library | `kDoctor/poc/services/symbol_lineage_service.py` (`update_from_parent`, ~502); client `kDoctor/poc/check_local_symbol_overrides.py` (restore path ~99) | Pathfinding scripts; thin automated coverage |
| Title-block convention audit | `kproj/src/kproj/services/metadata_analyzer.py`; `kDoctor/poc/check_metadata_conventions.py` | kproj service tests / kDoctor scripts |
| ERC run + JSON findings | `kproj/src/kproj/services/design_analyzer.py` | `kproj/tests/contract/test_kicad_cli_erc.py` |
| ERC interpretation / nearest ref | `kDoctor/poc/erc_drc_summary.py` | Pathfinding scripts/reports |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Read placed symbol fields for BOM | **Used** — jBOM BOM/application | No |
| Read placement transform | **Used** — Subdivision plant tools | No |
| Annotate/repair fields via whole-file rewrite | **Used** — jBOM annotate CLI | No (wrong write philosophy for this package) |
| Selected embedded-symbol restore from parent (`update_from_parent`) | **Used** — kDoctor override-check client | No |
| General embedded `lib_symbols` edit/cache sync | **Unimplemented** as a complete model (donor has **selected** restore only) | No |
| Wires, labels, junctions, no-connects, sheets nodes | **Unimplemented** as a model | No |
| Placed unit, pins, `instances` paths | **Unimplemented** | No |
| Project-scoped ERC as schematic/project operation | Runner **Used** (kproj publish); interpretation **Used** in kDoctor pathfinding; not packaged | No |

### Defects and shortcuts

- Three partial views of one placed-symbol node (jBOM / Subdivision / kDoctor); none is complete (survey §2).
- jBOM write path reformats the entire schematic (`sexpdata.dumps`)—unsuitable as package write policy (ADR 0003).
- kproj sheet token `(sheetfile` does not match KiCad 10 `(property "Sheetfile" ...)` (survey §1.3, §2).
- `sch_text` quote-truncation and tab-depth coupling (survey §3.1)—partially superseded for **libraries** by this package; still relevant if ported for schematics.
- kDoctor restore is text/`sexpr_replace` oriented and pathfinding-grade; not a full cache-sync product API.

### Lift note

Prefer a **read** merge of BOM fields + transform + identity first. Edits must use ADR 0003 localized writes, not jBOM dumps. Record kDoctor restore as **donor-used selected behavior** when planning schematic/library-cache work; “In package: No” is not “unimplemented in the estate.” Schematic electrical checks belong with project/schematic services, not a public `checks` module (ADR 0002).

---

## 3. PCBs

**Remit:** inspect/edit board content in project context; DRC ownership on the board/project.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| Footprints, pads, layers, origins, title | `jBOM/src/jbom/services/pcb_reader.py` | `jBOM/tests/unit/test_pcb_reader.py` |
| DRC JSON runner | `kproj/src/kproj/services/design_analyzer.py` | `kproj/tests/contract/test_kicad_cli_drc.py` |
| DRC interpretation | `kDoctor/poc/erc_drc_summary.py` | Scripts |
| PCB exports (gerber/render/step) | `jBOM/src/jbom/services/gerber_service.py`; `kproj/src/kproj/services/pcb_exporter.py` | `kproj/tests/contract/test_pcb_exporter.py` |
| Zone fill via `pcbnew` | `jBOM/src/jbom/plugin/zone_filler.py` | Plugin path |
| Placed footprint vs master diff | `kDoctor/poc/services/footprint_lineage_service.py` | Pathfinding; thin tests |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| PCB read for BOM/fab metadata | **Used** — jBOM | No |
| DRC run | **Used** — kproj publish | No |
| Full board edit model | **Unimplemented** | No |
| Design-block board linkage | **Usage unverified** as product API; present in kDoctor pathfinding | No |

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
| Flattened sexpdata reader | `FieldUnit-Subdivision/tools/kicad_services/symbol_library_reader.py` | `FieldUnit-Subdivision/tests/test_kicad_plant_graph.py` (`SymbolLibraryReaderTests`) |
| Regex unit/extends/locked view | `FieldUnit-Subdivision/tools/kicad_services/sch_text.py` (`library_symbols`) | `FieldUnit-Subdivision/tests/test_kicad_library_overview.py`; lint/contact-sheet tools |
| Field lint / contact sheet | `FieldUnit-Subdivision/tools/contract/lint_symbol_fields.py`, `FieldUnit-Subdivision/tools/contract/symbol_contact_sheet.py` | overview tests; contact sheet is tooling |
| Inheritance/pin-kind diff vs cache | `kDoctor/poc/services/symbol_lineage_service.py` | `kDoctor/poc/test_symlib_fix.py` (script) |
| Name/properties/pin-count context | `EagleLib2KiCad/src/eaglelib2kicad/services/kicad_library_context_service.py` | `EagleLib2KiCad/tests/unit/test_library_curation_harness.py` (and related) |
| Bulk property and structural recipes | `Railroad/symbols/edits/*.py`; retired Subdivision `apply_symbol_recipe.py` (git `3325807`) | Dated scripts / git history — **Historical demand** |

### Package (ADR 0004) — already lifted and improved

| Capability | Usage | Notes |
| --- | --- | --- |
| Explicit-path inspect + resolve | **Shipped (package)**; donor cutover **not** done | Supersedes silent flatten/extends-ignore for this surface |
| Existing declared property edit + atomic save | **Shipped (package)**; no released donor pin (ADR 0005) | |
| Rename/copy/split/add pin/graphics model | **Unimplemented** in package; Railroad/Subdivision recipes = **Historical demand** (and possible ongoing local use—**Usage unverified** beyond those scripts) | |

Donor readers above remain **Used** by Subdivision plant/overview/lint paths until cutover.

### Defects and shortcuts (donor — do not re-inherit)

Survey §3.1 and ADR 0004 evidence remain the defect list for **remaining** donor code:

1. Standard properties dropped by `sch_text.library_symbols`.
2. Quote-truncating property regex.
3. Pins flattened across units; unit 0 undocumented.
4. No pin `hide` / body style in donor readers (package exposes more pin/body fields).
5. Dual disagreeing readers in Subdivision.
6. Forward `extends` to a later parent broke overview pin lists (ADR 0004 evidence).

Package acceptance deliberately fixed inspection/inheritance/property-edit gates. Structural library editing remains open here.

### Lift note

**Next symbol slices** should extend the existing `SymbolLibrary` service (property insert/delete, pin ops, rename, copy) rather than port `sch_text` as a second public model. Bring recipe behaviors as gates; keep Railroad policy out of the package.

---

## 5. Footprint libraries

**Remit:** inspect/edit reusable footprint definitions and collections.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| Placed vs `.kicad_mod` master diff | `kDoctor/poc/services/footprint_lineage_service.py` | Pathfinding |
| `.pretty` enumerate + pad count | `EagleLib2KiCad/src/eaglelib2kicad/services/kicad_library_context_service.py` | `EagleLib2KiCad/tests/unit/test_library_curation_harness.py` |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Footprint lineage diff | **Used** in kDoctor pathfinding clients | No |
| Pad-count / list context | **Used** in EagleLib2KiCad closure/curation | No |
| Full `.kicad_mod` read/edit model | **Unimplemented** | No |
| Footprint library writes | **Unimplemented** | No |

### Defects and shortcuts

- Diff-oriented, not a definition editor.
- 3D models remain out of scope until requested (ADR 0002 exclusion).

### Lift note

Low maturity. A first footprint slice is **read model + path identity**, after tables/resolution can locate `.pretty` trees.

---

## 6. Library tables and resolution

**Remit:** registrations; resolve references with global/project context. Not definition content.

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| Global/project sym/fp tables, `${VAR}` from `kicad_common.json` + pro overrides, add/remove/rename | `EagleLib2KiCad/src/eaglelib2kicad/services/kicad_environment_service.py` | `EagleLib2KiCad/tests/unit/test_kicad_environment_service.py` |
| Nested `Table` entries; hard-coded `${KICAD10_*}` | `kDoctor/poc/services/symbol_lineage_service.py` (`_parse_sym_lib_table`) | Scripts |
| Classify internal/external lib refs (regex) | `kproj/src/kproj/common/kicad_libraries.py` | `kproj/tests/unit/common/test_kicad_libraries.py` |
| design_block_lib_table / block drift | `kDoctor/poc/services/design_block_service.py` | `kDoctor/poc/tests/test_design_block_service.py` |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Resolve configured libraries with real vars | **Used** — EagleLib2KiCad conversion/curation | No |
| Nested tables | **Used** — kDoctor lineage | No |
| Lib-table write | **Used** — EagleLib2KiCad | No |
| `design_block_lib_table` as first-class | **Used** in kDoctor pathfinding; productization **Usage unverified** | No |
| Single precedence model (global/project/env) | **Unimplemented** as one package API | No |

### Defects and shortcuts

- Three parsers (Eagle full, kDoctor nested, kproj classify-only).
- kDoctor variable expansion uses hard-coded macOS defaults—not general resolution.
- kproj classification is not resolution.

### Lift note

Strong donor candidate for an early **non-symbol** slice: read+resolve (+ optional write) under ADR 0003 byte rules for table files. Depends on environment/config discovery, not on full project schematic model. Lookup precedence still needs an owner lock (do not invent here).

---

## 7. Connectivity

**Remit (ADR 0002):** obtain, inspect, trace, and compare electrical connections **within project context**, with explicit data exchange where needed.

Netlist files are **exchange datasets**. They can lack current provenance and freshness. Handling a `.net` file is related evidence and a useful building block; it is **not** by itself the public project-owned Connectivity service, and must not silently rewrite ownership (ADR 0002).

### Donor harvest

| Behavior | Source | Test anchors |
| --- | --- | --- |
| kicadsexpr netlist parse | `FieldUnit-Subdivision/tools/kicad_services/netlist_reader.py` (`NetlistReader`) | `FieldUnit-Subdivision/tests/test_kicad_plant_graph.py` (`NetlistReaderTests`) |
| `sch export netlist` wrapper | `FieldUnit-Subdivision/tools/kicad_services/netlist_reader.py` (`KicadCliNetlistExporter`) | `KicadCliExporterSmokeTests` in the same file |
| Net-for-net compare / unify check | `FieldUnit-Subdivision/docs/archive/unify/build_spcoast.py`; `FieldUnit-Subdivision/tools/contract/netlist_diff.py` | Archive/scripts |
| Consumers of parse/export | Subdivision plant/controller parsers, link tools, render | Integration via those tools |

### Capability profile

| Capability | Usage | In package |
| --- | --- | --- |
| Parse exported netlist (exchange data) | **Used** — Subdivision compilers/tools | No |
| Export netlist via CLI | **Used** — Subdivision exporter helper | No |
| Project-owned connectivity model (trace/compare from design context) | **Unimplemented** as package/public service | No |
| Live connectivity from loaded schematic without export | **Unimplemented** | No |
| ADR 0003 connectivity verification for edits | **Policy** (required when applicable); no shared helper service yet | No |

### Defects and shortcuts

- Only netlist exchange path today; freshness/provenance of `.net` files is a consumer problem (survey notes Subdivision frozen desk net issues).
- Multiple CLI locators (`KICAD_CLI` vs others)—package must not fork another without #12.
- Treating “netlist reader” as full ADR 0002 Connectivity would blur ownership.

### Lift note

An **exchange-reader** slice (parse fixtures / existing `.net` files) is permissible and valuable. Optional export needs private CLI policy (#12). That slice does **not** replace project-owned Connectivity and does not make “project path optional” the ownership rule—export may take a project/schematic path as **input to CLI**, while the public Connectivity area still belongs to project context when offered.

---

## Cross-cutting internals (not public TOC)

These support services; ADR 0002 keeps them private.

| Concern | Strongest donor | Package stance |
| --- | --- | --- |
| S-expression read/edit representation | CircuitDK `lossless_sexpr` (ADR 0003) | **In package** private; do not add jBOM sexpdata / Eagle sexp / kDoctor regex as peers |
| Byte-preserving spans | `FieldUnit-Subdivision/tools/kicad_services/sch_text.py` (legacy) | Superseded for symbols by CircuitDK spans; schematic port still open |
| kicad-cli locator + exports | `kproj/src/kproj/common/kicad_install.py` + exporters | Unimplemented here; grilling [#12](https://github.com/plocher/kicad-primitives/issues/12) |
| Runtime lock/plugin | `jBOM/src/jbom/common/kicad_runtime.py` | Unimplemented here |
| ERC/DRC interpretation | kDoctor on kproj runner | Belongs with project/document checks when lifted |

**Defect:** five+ CLI locators and two env names (`KPROJ_KICAD_CLI` vs `KICAD_CLI`). **Shortcut:** treating `cli` as a public module (rejected by ADR 0002).

---

## Matrix: intended area × maturity

| Area | Donor maturity | Package | Blocking dependencies for a useful slice |
| --- | --- | --- | --- |
| Symbol libraries | High (and partially superseded here) | **Partial (ADR 0004)** | None for further symbol ops |
| Netlist exchange data (not full Connectivity ownership) | Medium-high | None | Fixtures for parse-only; #12 if export included |
| Connectivity (project-owned) | Low as unified service | None | Project context; schematic richness; ADR 0003 gates on edits |
| Library tables/resolution | Medium-high | None | Config home / var policy (precedence lock) |
| Projects | Medium | None | Fix sheet-walk facts (#13); decide pro/variants coverage |
| Schematics (read) | Medium (fragmented) | None | Project hierarchy; write model already chosen |
| Schematics (edit) | Medium but wrong write path | None | Localized sch writes; **required** ADR 0003 verification for the edit class |
| PCBs (read/DRC) | Medium | None | Project; CLI |
| PCBs (edit) | Low | None | Large model gap |
| Footprint libraries | Low | None | Tables/resolution to find libraries |

---

## Recommended bounded implementation slices

Ordered for **decision support**, not a committed roadmap. Each slice should stay vertical: one client outcome, donor tests moved or rewritten as gates, ADR 0003 writes where editing appears. No consumer cutover (ADR 0005).

**Write verification (ADR 0003):** connectivity-preserving operations must verify unchanged connectivity; electrical edits must verify their intended electrical change. Implementation mechanism may vary (netlist compare, future in-model compare, etc.). The **contract is not optional** and is not deferred by slice wording.

### S1 — Extend symbol-library editing (same service)

- **Outcome:** property insert/delete and/or pin number/name/type edits and/or rename within one `.kicad_sym`, still explicit-path.
- **Depends on:** ADR 0004 surface (done).
- **Donor anchors:** retired recipe ops; `Railroad/symbols/edits/*`; overview/lint expectations.
- **Why next:** historical and tooling demand; reuses parser/persist; no project model required.
- **Avoid:** boiling the ocean (all recipe ops in one PR).
- **Verification:** library byte/preservation gates as today; electrical/connectivity gates apply when an edit is classified that way.

### S2 — Netlist exchange reader (+ optional export)

- **Outcome:** parse kicadsexpr netlist as **exchange data**; optional `sch export netlist` behind private CLI.
- **Ownership:** this is **not** claiming the full public Connectivity area. Project-owned obtain/trace/compare remains a later service.
- **Depends on:** fixtures for parse-only; provisional CLI locator policy (#12) if export is included.
- **Donor anchors:** `FieldUnit-Subdivision/tests/test_kicad_plant_graph.py` (`NetlistReaderTests`, exporter smoke); `FieldUnit-Subdivision/tools/contract/netlist_diff.py`.
- **Why:** only netlist implementation in the estate; useful input to later schematic edit **verification** and to a future Connectivity service.

### S3 — Library tables read/resolve (then optional write)

- **Outcome:** load global/project sym/fp tables; resolve `${VAR}`; list nicknames → paths.
- **Depends on:** owner-facing precedence/env rules (small grilling or spike); nested tables from kDoctor.
- **Donor anchors:** `EagleLib2KiCad/tests/unit/test_kicad_environment_service.py`; kDoctor nested examples.
- **Why:** unlocks “open library by nickname” and footprint discovery without sys.path corpora.

### S4 — Project context: discovery + hierarchy (correct sheet paths)

- **Outcome:** open project by path; list schematic files with correct relative resolution; text_variables.
- **Depends on:** #13 sheet-walk fixes filed/fixed in donors or reimplemented cleanly here.
- **Donor anchors:** `jBOM/tests/test_project_context.py`, `jBOM/tests/test_project_discovery.py`, `jBOM/tests/test_project_file_resolver.py`; kproj project reader.
- **Why:** prerequisite for honest schematic multi-sheet work.

### S5 — Schematic placed-symbol read (merged view)

- **Outcome:** one instance record: fields, uuid, transform, unit if present; title block.
- **Depends on:** S4 for multi-sheet; ADR 0003 representation for future edits.
- **Donor anchors:** `jBOM/tests/services/readers/test_schematic_reader.py`; Subdivision placement consumers.
- **Why:** collapses three partial views; still read-only.

### S6 — Schematic localized field edit

- **Outcome:** set existing placed-symbol property without whole-file reformat; lock-file guard.
- **Depends on:** S5; runtime lock port.
- **Verification (required, ADR 0003):** classify the operation. Connectivity-preserving field edits must prove connectivity unchanged (mechanism open: netlist compare helper, later in-model compare, etc.). Edits that intentionally change connectivity/electrical meaning must prove the intended change. Do not ship S6 as “bytes only, connectivity later.”
- **Donor anchors:** jBOM annotate scenarios (behavior only—not dumps writer); kDoctor renumber “netlist byte-identical” idea as one possible mechanism.
- **Related donor (not the same slice):** embedded restore via `kDoctor/poc/services/symbol_lineage_service.py` `update_from_parent` / `kDoctor/poc/check_local_symbol_overrides.py`.
- **Why:** replaces the most harmful write path donors still use.

### S7 — PCB read + DRC/export facade

- **Outcome:** footprint/pad/title read; DRC JSON findings; selected exports.
- **Depends on:** S4; #12 CLI.
- **Donor anchors:** `jBOM/tests/unit/test_pcb_reader.py`; kproj DRC/export contracts.
- **Why:** useful without claiming board editing.

### S8 — Footprint library read model

- **Outcome:** open `.kicad_mod` / list `.pretty` with stable identity and pad summary.
- **Depends on:** S3 for resolution; PCB lineage only as evidence.
- **Why:** completeness for library TOC; lower urgency than S1–S5 for current clients.

### Explicitly later / larger

- Full schematic geometry (wires/labels/sheets).
- PCB geometry editing.
- Project-owned Connectivity beyond exchange netlists; live connectivity without export.
- Structural symbol library ops beyond a thin S1 series.
- design_block tables as productized API.
- Public CLI module (rejected); KiCad 11 IPC facade (design note only).
- Variants: still **undecided** package coverage (not listed as excluded).

---

## Facts needed for an owner-selected 1.0 bar

ADR 0002/0005: owner locks 1.0 completeness. This inventory does not. Useful inputs:

1. **Parity set:** which **Used** donor capabilities must work through this package before any post-1.0 cutover (BOM path? netlist compilers? lib-table manager? annotate?).
2. **Must-fix defects:** sheet-walk, dual symbol readers, whole-file schematic rewrite—which are 1.0 blockers vs accepted limits?
3. **Edit surface minimum:** is symbol property edit + one schematic field edit enough, or must pin/symbol structural edits ship?
4. **Resolution policy:** global vs project table precedence and env var names (#12 adjacent).
5. **CLI necessity:** which exports/ERC/DRC are in 1.0 vs “invoke kicad-cli yourself”?
6. **Verification gates (ADR 0003):** for each edit class, which mechanisms satisfy the required contract (byte preservation; unchanged connectivity; intended electrical change; optional KiCad resave stability as evidence only)? Mechanisms are choosable; the contract is not.
7. **Consumer offer order:** still map [#6](https://github.com/plocher/kicad-primitives/issues/6); 1.0 bar should list which donor is the first **offer**, not force migration (ADR 0005).
8. **Coverage decisions (not automatic exclusions):** 3D remains ADR-excluded until requested; fab orchestration and railroad compilers stay consumer product logic; **variants** need an explicit in/out decision (currently unimplemented/undecided).

---

## Suggested decision uses

| Decision | Use this inventory to… |
| --- | --- |
| Next implementation ticket | Pick one of S1–S8; open a scoped issue with donor-rooted paths + tests |
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
- Repair pass on PR #23: usage labels, ADR 0003 verification wording, variants coverage, kDoctor embedded restore, jBOM project test anchors, donor-rooted paths, unused-investigation honesty, netlist vs Connectivity ownership.
- Open map tickets at original research time: #1, #6, #8, #9, #12, #13 (plus closed distribution #7).
