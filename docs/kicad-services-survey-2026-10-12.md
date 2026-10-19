# KiCad services survey (2026-10-12)

- Status: survey, read-only. No repository was changed except for this file.
- Question (owner): what KiCad read/edit/write tooling exists across jBOM, kproj, kDoctor, EagleLib2KiCad, FieldUnit-Subdivision and Railroad; what overlaps; what a general KiCad project-and-library API still lacks; evolve in situ or start a stand-alone package.
- Method: read each repo's layout, README, CONTEXT/AGENTS, docs, pyproject and tests; listed open GitHub issues with `gh`. Every claim cites a path. Where a claim could not be verified it says so.
- Not covered: the 90-odd per-board project repos under `plocher/*` (they hold designs, not tooling). `~/Dropbox/KiCad/AI-playground/*.py` and `~/Dropbox/KiCad/SPCoast_KiCad_Library` were skimmed only; see §1.8.

## 1. Inventory

Aliases: `~/Dropbox/KiCad/jbom` and `jBOM` are the same directory (inode 286302996); `kdoctor` and `kDoctor` likewise (inode 469280645). `kproj-phase2` is not a git repo; it holds only `docs/CONTEXT.md` and `docs/adr/`, the planning predecessor of `kproj/CONTEXT.md`.

### 1.1 Summary table

| Repo | Remote | Size (src) | Parsing approach | KiCad targeted | Reads | Edits / writes | kicad-cli | Renders | Tests touching KiCad I/O |
|---|---|---|---|---|---|---|---|---|---|
| jBOM 7.9.1 | `plocher/jBOM` | 40.9k lines, 127 test files + 57 `.feature` | `sexpdata` tree (`src/jbom/common/sexp_parser.py`); regex for sheet hierarchy and `.kicad_pro` is JSON | files "KiCad 6+" (`services/project_discovery.py`); plugin on KiCad 9/10 (`plugin/__init__.py`) | project discovery/resolution, lock file, `.kicad_pro` `text_variables`, schematic symbols as BOM components, title blocks, PCB footprints/pads/origins | schematic properties via tree mutation and `sexpdata.dumps` (whole-file reformat); `.kicad_pcb` zone fill via `pcbnew` in plugin mode | `pcb export gerber/drill/ipc356`; private locator | none | `tests/services/readers/test_schematic_reader.py` (12), `tests/unit/test_pcb_reader.py` (11), `tests/unit/test_annotate_repairs.py` (18), `tests/unit/test_project_variables_reader.py` |
| kproj 0.13.4 | `plocher/kproj` | 10.8k lines, 59 test files + 14 `.feature` | wraps jBOM (`jbom>=7.3.0` in `pyproject.toml`); own regex for lib tables, `lib_id`, footprint refs, sheet walk | KiCad 9 and 10 (`SUPPORTED_KICAD_MAJORS` in `common/kicad_install.py`) | title blocks (via jBOM), symbol/footprint library references, `sym-lib-table`/`fp-lib-table` classification | none | public locator (`find_kicad_cli`, `find_kicad_python`), `sch erc`, `pcb drc` (JSON), `sch export svg/pdf`, `pcb export render/step`, iBOM script | PNG/SVG/PDF/STEP through kicad-cli | `tests/unit/common/test_kicad_libraries.py`, `test_kicad_install.py`, `tests/contract/test_kicad_cli_erc.py`, `test_kicad_cli_drc.py`, `test_schematic_exporter.py`, `test_pcb_exporter.py` |
| kDoctor | `plocher/kDoctor` | no package; `poc/` 3.6k lines | regex + balanced-paren block scanning; deliberately not `sexpdata` (`poc/services/design_block_service.py` docstring); `poc/sch_symbol_transfer.py` optionally imports jBOM from the sibling checkout | KiCad 9/10 (`poc/erc_drc_summary.py`); `${KICAD10_*}` only (`symbol_lineage_service.py`) | `lib_symbols` cache vs parent library (with `extends`), `sym-lib-table` incl. nested `Table` entries, placed footprints vs `.kicad_mod` masters, `design_block_lib_table` and block drift, embedded `.kicad_wks`, title-block conventions, symbol/footprint positions | text-level: renumber power refs, restore a symbol from its parent (`sexpr_replace`), transfer symbol instance blocks between schematics, unlink a design block | `sch erc`, `pcb drc --schematic-parity` JSON summariser | none | one unit-test file `poc/tests/test_design_block_service.py`; `poc/test_symlib_fix.py` is a script |
| EagleLib2KiCad | `plocher/EagleLib2KiCad` | 2.1k lines, 14 test/feature files | own minimal s-expression parser `src/eaglelib2kicad/common/sexp.py`; Eagle XML via `ElementTree` | KiCad config-home version detected from the directory name (`kicad_environment_service.py:505`) | global and project `sym-lib-table`/`fp-lib-table` with nicknames; `${VAR}` resolution from `kicad_common.json` and project overrides; symbol name/properties/pin count from `.kicad_sym`; `.pretty` footprint items and pad counts; closure report | add/remove/rename lib-table entries (table regenerated line by line, `_write_table_records`) | none | none | `tests/unit/test_kicad_environment_service.py`, `test_library_curation_harness.py`, `features/` |
| FieldUnit-Subdivision | `plocher/FieldUnit-Subdivision` | `tools/kicad_services/` 834 lines; `tools/contract/` 472 lines | `sexpdata` via jBOM's `load_kicad_file` (jBOM reached by `sys.path` to `~/Dropbox/KiCad/jBOM/src`, `tools/kicad_services/__init__.py`); text spans + regex in `sch_text.py` | KiCad 10 only (`AGENTS.md`; `sch_text.py` assumes one node per line, tab-indented) | netlist (`kicadsexpr`): components, fields, sheet paths, nets, nodes; `.kicad_sym` top-level symbols, properties, pins across units; placed-symbol transforms; title block (via jBOM); `sch_text.library_symbols`: properties, pins, `extends`, units, `ki_locked`, Value autoplace | text spans (`end_of`, `blocks`, `replace_spans`); the retired recipe did rename symbol/pins/properties, change pin type, add a pin, edit body texts, split units, copy between libraries (git `3325807:tools/contract/apply_symbol_recipe.py`); the retired unifier generated a whole project by text (`docs/archive/unify/build_spcoast.py`) | `sch export netlist` (`KicadCliNetlistExporter`, own locator); `sym export svg` (`tools/contract/symbol_contact_sheet.py`) | SVG contact sheet; plant picture via Graphviz (`tools/plant_graph/picture.py`) | `tests/test_kicad_plant_graph.py`: `SymbolLibraryReaderTests` (1), `NetlistReaderTests` (1), `KicadCliExporterSmokeTests` (1); `sch_text.py` has no tests; `tests/test_contract_lint.py` (14) tests `lint_libraries` on dicts, not the parser |
| Railroad | `plocher/Railroad` | `Scratch/tools/` 1,454 lines (gitignored: `.gitignore:36`) | text templates and regex; `uuid5` for determinism | KiCad 10 | consumes Subdivision readers (`binding_pass*.py`, `sargent_bindings.py`) | generates `.kicad_sym` symbols and `.kicad_sch` sheets from templates (`make_scratch_project.py`, `make_scratch_panel.py`, `rebuild_scratch.py`, `make_spike_lib.py`); add/remove symbols and fields (`amend_scratch_lib.py`) | `make netlist` in `Archive/SPCoast/kicad.mk` | none | none |
| InterlockingPlant | none (local git) | symbols only | n/a | KiCad 10 | n/a | n/a | n/a | n/a | n/a |
| FieldUnit (Arduino) | `plocher/FieldUnit` | `tools/test_ctc_desk.py` only | n/a | n/a | no KiCad tooling; ADRs 0003 to 0005 and the design docs cite symbol contracts in prose | none | none | none | none |

### 1.2 jBOM (`~/Dropbox/KiCad/jBOM`)

The reference "services" layout: `common/` (stateless) → `services/` (stateful, constructor-configured) → `application/` → `cli/`, dependency inward only (`docs/design/service-command-architecture.md`, `docs/architecture/adr/0013-domain-centric-design.md`).

KiCad-facing modules:

- `src/jbom/common/sexp_parser.py`: `load_kicad_file` (whole file through `sexpdata.loads`), `walk_nodes`, `find_child`, `find_all_children`. No version check; no write counterpart.
- `src/jbom/services/schematic_reader.py`: `SchematicReader.load_components` (one `Component` per placed `(symbol ...)`: `lib_id`, Reference, Value, Footprint, uuid, `in_bom`, `dnp`, `exclude_from_sim`, other properties, source file) and `read_metadata` (title, rev, date, company, comments 1 to 9). It does not read pins, wires, labels, sheets or `lib_symbols`.
- `src/jbom/services/project_context.py`: `ProjectContext` (lock file, `get_hierarchical_schematic_files`). The hierarchy walk is a regex over `(property "Sheetfile" ...)` and resolves each child against the project directory, not the parent sheet (`_extract_sheet_files`, `_process_hierarchical_schematic`).
- `src/jbom/services/project_discovery.py`, `project_file_resolver.py`, `application/pcb_project_loader.py` (`resolve_pcb_input`): one `.kicad_pro` per directory, autosave handling, the four input shapes kproj inherits.
- `src/jbom/services/project_variables_reader.py`: `.kicad_pro` JSON `text_variables` only.
- `src/jbom/services/pcb_reader.py`: `DefaultKiCadReaderService` (footprints, pads, layers, origins, title block; `mode` auto/pcbnew/sexp).
- `src/jbom/services/annotation_service.py`: the only schematic writer. Mutates the `sexpdata` tree and writes `sexpdata.dumps(...)` (lines 198, 364): the whole file is reserialised, so a one-field change reformats every line. Guarded by `common/kicad_runtime.py` (`check_write_permitted`, `is_running_inside_kicad`).
- `src/jbom/services/gerber_service.py`: `_find_kicad_cli` (private; PATH, macOS bundle, Windows, Linux, snap).
- `src/jbom/plugin/zone_filler.py`: `pcbnew` API, plugin mode only.
- No `.kicad_sym` reader, no `.pretty`/`.kicad_mod` reader, no netlist reader, no lib-table reader, no renderer.

Docs that bear on a shared API: ADR 0004 and 0016 (EagleLib2KiCad: "service-surface-first", incubate library-manager services there, converge into jBOM later); `docs/reference/kicad-best-practices.md` (what jBOM reads from symbols and footprints).

### 1.3 kproj (`~/Dropbox/KiCad/kproj`)

- Depends on jBOM as a library (`pyproject.toml`; ADR 0001 inherits jBOM's patterns, ADR 0003 "read, don't invoke", ADR 0006 library-shape discipline without extracting a library).
- `src/kproj/services/kicad_project_reader.py`: thin wrapper over `resolve_pcb_input`, `SchematicReader.read_metadata`, `DefaultKiCadReaderService.read_metadata`.
- `src/kproj/common/kicad_libraries.py`: `enumerate_libraries(project_dir)`; regexes `_LIB_TABLE_ENTRY`, `_LIB_ID_REF`, `_FOOTPRINT_REF`, `_SHEETFILE_REF`; classifies each library internal/external and kicad/added. Its sheet walk matches `(sheetfile "...")`, which occurs 0 times in `~/Dropbox/KiCad/Railroad/SPCoast/SPCoast.kicad_sch` and `South-cTc.kicad_sch` (KiCad 10 writes `(property "Sheetfile" ...)`), so on those files only the root sheet is scanned. Not verified against older files.
- `src/kproj/common/kicad_install.py`: `find_kicad_cli` (env `KPROJ_KICAD_CLI`, platform defaults, PATH), `find_kicad_python`, iBOM plugin dir, version gate 9/10. Tested in `tests/unit/common/test_kicad_install.py` and `tests/contract/test_kicad_install_locator.py`.
- `src/kproj/services/design_analyzer.py`: `kicad-cli sch erc` / `pcb drc` JSON → `Finding`; mechanical failure vs findings split (ADR 0004).
- `src/kproj/services/schematic_exporter.py`, `pcb_exporter.py`, `thumbnail_generator.py`, `ibom_generator.py`: exports with atomic temp-file moves; `common/subprocess_runner.py` is the one subprocess entry point.
- `src/kproj/services/metadata_analyzer.py`: title-block convention audit (`${COMMENT9}` status taxonomy).
- No KiCad file is written.

### 1.4 kDoctor (`~/Dropbox/KiCad/kDoctor`)

- Status per `README.md` and `docs/ARCHITECTURE.md`: Phase 0 pathfinding done (5 steps, reports under `reports/step0N/`), Phase 1 spike in progress; no package, no `pyproject.toml`. `README.md` links `docs/DOCTRINE.md`, which does not exist.
- `docs/ARCHITECTURE.md` already states the plan this survey is about: "Phase 2: Shared primitives library. Extract jBOM's `services/` and `common/` layers into a neutral `kicad-primitives` library ... Do not extract or optimize the library ahead of need. Wait for evidence from a third consumer." Its "Primitives kdoctor will need" list: ERC/DRC runner and JSON parser, netlist exporter and parser, `.kicad_pro` reader, structure audits, a public `find_kicad_cli()`. It also sets a facade rule: file parsing and `kicad-cli` now, the KiCad 11 IPC API later behind the same contracts.
- `poc/services/symbol_lineage_service.py` (550 lines): `lib_symbols` cache vs parent library, `extends` resolution, pin-kind diff, `_parse_sym_lib_table` following nested `Table` entries, `_expand_kicad_variables` with hard-coded macOS defaults for `${KICAD10_*}`, lock-file check, `sexpr_replace` write backend.
- `poc/services/footprint_lineage_service.py`: placed footprint vs `.pretty/*.kicad_mod` master, with the coordinate-frame caveats documented in its docstring.
- `poc/services/design_block_service.py`, `embedded_wks_service.py` (base64 + Zstandard via the `zstd` CLI), `location_service.py` (nearest reference; provisional zone grid; its `_scan_balanced_block` does not skip quoted strings).
- Scripts: `poc/renumber_power_refs.py` (single-pass mapped token replace, verified by "netlist byte-identical"), `poc/sch_symbol_transfer.py` (list/extract/apply symbol instance blocks, regenerates uuids, rewrites `(instances (project ...))`), `poc/unlink_design_block.py`, `poc/check_*.py`, `poc/erc_drc_summary.py`.

### 1.5 EagleLib2KiCad (`~/Dropbox/KiCad/EagleLib2KiCad`)

Not in the owner's list, but it is the one repo that reads and writes KiCad library tables with real path-variable resolution, and jBOM ADR 0004/0016 name it as the incubator for "KiCad library environment management services":

- `src/eaglelib2kicad/common/sexp.py`: own tokenizer and parser (lists, quoted strings with escapes, bare tokens).
- `src/eaglelib2kicad/services/kicad_environment_service.py` (581 lines): `discover_configured_libraries` (global and project tables, nicknames, `${VAR}` from `kicad_common.json` `environment.vars` and project `.kicad_pro` overrides, config-home version detection), `add_library`, `remove_library`, `rename_library`.
- `src/eaglelib2kicad/services/kicad_library_context_service.py`: symbol contexts (name, properties, pin-node count) and footprint items (`.pretty`, pad count), closure report (resolved/unresolved/ambiguous).
- `README.md`: intent is "a general KiCad library manager ... the organization and relationships of the corpus itself".

### 1.6 FieldUnit-Subdivision (`~/Dropbox/workspace/FieldUnit-Subdivision`)

- `tools/kicad_services/__init__.py` bootstraps `~/Dropbox/KiCad/jBOM/src` onto `sys.path`; `jbom` is not pip-installed (`python3 -c "import jbom"` fails; `sexpdata 1.0.2` is installed).
- `tools/kicad_services/netlist_reader.py`: `NetlistReader` (the only netlist reader in any repo) and `KicadCliNetlistExporter` (own locator: `KICAD_CLI`, two macOS bundle paths, `/usr/local/bin`, `/usr/bin`).
- `tools/kicad_services/symbol_library_reader.py`: `SymbolLibraryReader` returns `LibrarySymbol(name, reference_prefix, pins, properties)`; pins are aggregated across units, unit identity is dropped, `extends` is ignored, graphics are ignored.
- `tools/kicad_services/schematic_reader.py`: `SchematicPlacementReader` (`at`, rotation, mirror per reference; title block via jBOM).
- `tools/kicad_services/sch_text.py` (80 lines): `end_of` (skips quoted strings), `blocks(text, head, depth)`, `replace_spans`, `library_symbols` (regex over a symbol block: non-standard properties, pins with type, `extends`, units → pin names, `ki_locked`, Value `do_not_autoplace`). Format-dependent on KiCad 10's one-node-per-line, tab-indented output. No tests of its own.
- `tools/contract/lint_symbol_fields.py`, `lint_libraries.py`, `symbol_contact_sheet.py` consume `sch_text.library_symbols`.
- Retired but recorded: `apply_symbol_recipe.py` (git `3325807`): `set_prop`, `del_prop`, `rename_prop`, `rename_symbol`, `rename_pins`, `add_pin`, `edit_texts`, `split_units`, copy between libraries, `HAND_FINISHED` carry-over, symbols written in KiCad's sorted order (`docs/review/symbol-library-triage-2026-10-10.md` §1, §6). `docs/archive/unify/build_spcoast.py`: `rewrite_symbols`, `renumber`, `set_title_block`, `sheet_block`, `sheet_instances`, `embedded_worksheet`, `check` (ERC and net-for-net netlist comparison).
- `docs/archive/TBD-shared-kicad-python-api.md`: open POC debt: "Contribute equivalent services upstream to jBOM (or extract a small shared KiCad Python package with jBOM peers)."
- Consumers: `tools/plant_graph/compiler.py` (types only), `tools/controller_graph/compiler.py`, `tools/link_subdivision.py`, `tools/parse_kicad_plant.py`, `tools/parse_kicad_controller.py`, `tools/render_plant_picture.py`; `AGENTS.md`: "Reuse these; do not write new s-expression parsers."

### 1.7 Railroad (`~/Dropbox/KiCad/Railroad`)

- `AGENTS.md`: schematics are data sources; lock-file rule; "Read connectivity from the netlist or ERC, never from coordinates"; `Archive/SPCoast/kicad.mk` "expected to move into FieldUnit-Subdivision `tools/`". `kicad.mk` still defaults `SYMBOLS` to `InterlockingPlant/symbols` and `LIB` to `Railroad.kicad_sym`, both superseded by the 2026-10-11 cutover to `Railroad/symbols/`.
- `Scratch/tools/*.py`: text-template generators for symbols (`prop`, `pin_sx`, `symbol`), sheets (`place`, `abut`, `wire`, `label`, `junction`, hierarchical sheet insertion), `extract` of a symbol block from a library, `uuid5` ids. Gitignored (`.gitignore:36`), so they live only in Dropbox.
- `symbols/`: four hand-maintained libraries since commit `3cba1a4` (`Railroad-Trackplan`, `Railroad-Office`, `Railroad-Field`, `Railroad-HardwareIO.kicad_sym`), which replaced the three cutover libraries (`RailroadPlant`, `RailroadDevice`, `RailroadDesk`) during this survey; the tree was clean at the end of it. FieldUnit-Subdivision branch `feat/four-libraries` (`1297d0a`) follows the rename in `tools/contract/lint_symbol_fields.py` and `symbol_contact_sheet.py`; `tools/contract/lint_libraries.py:32` still names the InterlockingPlant libraries.
- Global `~/Library/Preferences/kicad/10.0/sym-lib-table` registers `RailroadPlant`, `RailroadDevice`, `RailroadDesk` and the three InterlockingPlant ones (disabled and hidden); the four new names were not yet registered when read.

### 1.8 Other evidence

- `~/Dropbox/KiCad/AI-playground/`: `fix_unit_names.py`, `fix_symbol_names.py`, `comprehensive_fix.py`, `update_kicad_library.py`, `validate_library.py`: one-off regex edits and generation of `SPCoast.kicad_sym` from an inventory CSV. Evidence that library editing by script recurs; not reusable.
- `~/Dropbox/workspace/kicad`: a KiCad source checkout (has `api/`), cited by kDoctor `docs/ARCHITECTURE.md` as reference for the IPC API.

### 1.9 Who imports whom today

| Consumer | Provider | Mechanism |
|---|---|---|
| kproj | jBOM | `pyproject.toml` dependency `jbom>=7.3.0` |
| FieldUnit-Subdivision | jBOM | `sys.path` to the Dropbox checkout (`tools/kicad_services/__init__.py`) |
| kDoctor `poc/sch_symbol_transfer.py` | jBOM | `sys.path` to the sibling checkout, optional (`HAS_JBOM`) |
| Railroad `Scratch/tools` | FieldUnit-Subdivision | `sys.path` to `~/Dropbox/workspace/FieldUnit-Subdivision/tools` |
| EagleLib2KiCad | none | own parser; convergence into jBOM planned (jBOM ADR 0004) |
| jBOM | none | |

## 2. Overlaps and conflicts

| Capability | Implementations | Stronger today, and why |
|---|---|---|
| S-expression parsing | jBOM `common/sexp_parser.py` (sexpdata); EagleLib2KiCad `common/sexp.py` (own); kDoctor regex + balanced parens (several files); FieldUnit-Subdivision `sch_text.py` (spans); kproj regexes (`common/kicad_libraries.py`) | For reading a tree: jBOM, tested and shared by two consumers. For editing: `sch_text.py`, because it keeps untouched bytes and skips quoted strings; kDoctor's `_scan_balanced_block` does not skip strings. Neither editor is tested. |
| Title block | jBOM `SchematicReader.read_metadata`, `pcb_reader._extract_title_block_metadata`; kDoctor `poc/check_metadata_conventions.py` (regex); kproj wraps jBOM | jBOM; kproj's `MetadataAnalyzer` and kDoctor's checker apply the same `${COMMENT9}` taxonomy in two places (`kproj/src/kproj/services/metadata_analyzer.py`, `kDoctor/poc/check_metadata_conventions.py`). |
| Sheet hierarchy walk | jBOM `ProjectContext._extract_sheet_files` (regex on `property "Sheetfile"`, resolved from the project dir); kproj `_walk_schematic_tree` (regex on `(sheetfile`, resolved from the parent sheet) | Neither. jBOM matches KiCad 10 files but resolves paths from the wrong base for nested directories; kproj resolves correctly but its token does not occur in KiCad 10 files (§1.3). Nobody reads sheet instance paths or UUIDs. |
| kicad-cli locator | kproj `find_kicad_cli` (public, tested, env `KPROJ_KICAD_CLI`); jBOM `gerber_service._find_kicad_cli` (private); Subdivision `KicadCliNetlistExporter._discover_kicad_cli` and `symbol_contact_sheet.KICAD_CLI` (env `KICAD_CLI`); kDoctor `--kicad-cli`; Railroad `kicad.mk` and `build_spcoast.py` (`KICAD_CLI`) | kproj's, but the env var name differs from everything else (`KPROJ_KICAD_CLI` vs `KICAD_CLI`). |
| ERC/DRC | kproj `DesignAnalyzer` (runner + JSON → findings, tested); kDoctor `erc_drc_summary.py` (grouping, exclusions, nearest reference) | Complementary: kproj owns the runner and parse, kDoctor owns the interpretation. |
| `sym-lib-table` / `fp-lib-table` | EagleLib2KiCad (parse, resolve `${VAR}` from `kicad_common.json`, write); kDoctor (nested `Table`, hard-coded `${KICAD10_*}` defaults); kproj (regex, classify only) | EagleLib2KiCad for resolution and write; kDoctor is the only one following nested tables. |
| `.kicad_sym` reading | Subdivision `SymbolLibraryReader` (sexpdata, pins across units) and `sch_text.library_symbols` (units, `extends`, locked); kDoctor `symbol_lineage_service` (`extends` resolution, pin kinds); EagleLib2KiCad library context (name, properties, pin count) | Subdivision's pair, for fields and units. None models unit graphics, pin positions per unit, or resolves `extends` into a full symbol (kDoctor resolves it only for text diff). Subdivision has two readers of the same file that disagree on unit handling. |
| Placed symbol instance | jBOM `SchematicReader._parse_symbol` (BOM view); Subdivision `SchematicPlacementReader` (transform view); kDoctor `location_service`, `sch_symbol_transfer` (regex views) | Three partial views of one node; none reads pins, unit, `instances` paths. |
| Lock-file guard | jBOM `check_write_permitted`; kDoctor `_assert_project_not_locked`; Railroad `AGENTS.md` prose | jBOM (plugin-mode aware, dry-run aware). |
| Writing | jBOM: tree + `sexpdata.dumps` (reformat); kDoctor and Subdivision: text replacement; Railroad Scratch and AI-playground: template generation; EagleLib2KiCad: regenerate lib table lines | Three write philosophies. The reformat path is unsuitable for anything the owner reviews as a diff (`sch_text.py` docstring states the reason). |
| Netlist | Subdivision `NetlistReader` only | Fills kDoctor's listed gap. |
| `.kicad_pro` | jBOM `text_variables`; EagleLib2KiCad path-variable overrides | Neither reads sheets, libraries, ERC settings or variants. |

## 3. Gaps

What a reusable KiCad project-and-library API would need that no repo has:

| Area | Gap | Nearest existing piece |
|---|---|---|
| Project model | `.kicad_pro` beyond `text_variables`; root sheet, sheet tree with instance paths and UUIDs, multi-instanced sheets, `sheet_instances`; project-local lib tables and `design_block_lib_table` as one model | jBOM `ProjectContext`; EagleLib2KiCad environment; kDoctor design-block service |
| Schematic model | wires, labels (local, global, hierarchical), junctions, no-connects, sheets, `lib_symbols`; placed symbol with unit, pins, `instances` | jBOM and Subdivision read only symbols; Railroad Scratch generates wires and labels by template |
| Byte-preserving edit | a node-level API (find node by path or uuid, set/add/remove child, replace block) over text spans, with KiCad-formatted insertion; today `sch_text.py` exposes spans and the recipe's helpers are gone | `sch_text.py`; recipe at git `3325807`; kDoctor `sexpr_replace` |
| Symbol library model | symbol with units, per-unit graphics and pins with positions, properties with effects, `extends` resolved, `ki_locked`, power flag; operations: rename, copy across libraries, split or merge units, add pin; write in KiCad's sorted order | recipe (retired), `sch_text.library_symbols`, kDoctor lineage |
| Footprint libraries | `.pretty`/`.kicad_mod` read as a model; write | kDoctor footprint lineage (diff only); EagleLib2KiCad pad count |
| kicad-cli facade | one locator and env var; version probe; `sch export netlist/svg/pdf/bom`, `sch erc`, `pcb drc/export`, `sym export svg`, `sym upgrade`; JSON parsing; Fontconfig stderr noise | kproj (most), Subdivision (netlist, sym svg), kDoctor (summaries) |
| Lib tables | one parser/writer for `sym-lib-table`, `fp-lib-table`, `design_block_lib_table`, global and project, nested tables, `${VAR}` from `kicad_common.json` | EagleLib2KiCad + kDoctor nested handling |
| Versioned formats | nothing checks `(version N)`; `sch_text.py` assumes KiCad 10 layout; `sexpdata` is version-blind; KiCad 10 variants unsupported (jBOM #382, kproj #66) | none |
| Round-trip tests | no automated parse → write → bytes-equal suite anywhere; verification is manual or by netlist comparison (`build_spcoast.py --check`, kDoctor renumber notes) and by `kicad-cli` render (`symbol_contact_sheet.py`) | the two verification ideas exist; neither is a test |
| Packaging | `jbom` not installable here; two repos reach into Dropbox paths; Railroad's spike tools are gitignored | kproj's pin on PyPI `jbom` |
| Runtime facade | the KiCad 11 IPC API behind the same contracts (kDoctor `docs/ARCHITECTURE.md`) | design note only |

### 3.1 Verified observations on FieldUnit-Subdivision `tools/kicad_services/` (from building the library overview tool, 2026-10-12)

The coordinator reported seven findings from a library-overview tool written today on a worktree branch (`worktree-agent-a12e56333f942670a`, `tools/kicad_library_overview.py`). That branch and file are not visible in this checkout, so the new code is reported, not verified; each underlying defect was checked against the working tree (`1297d0a`) and the live libraries.

1. `sch_text.library_symbols()` drops KiCad's standard properties (`_STANDARD_PROPERTIES`, `tools/kicad_services/sch_text.py:50`), so a consumer that needs every field walks the symbol blocks twice. Reported: a `library_standard_properties()` was added beside it on the worktree branch. One call returning every property with the standard set flagged would be simpler.
2. The property regex `"([^"]*)"` (`sch_text.py:61`) truncates a value at an escaped quote. Verified: `~/Dropbox/KiCad/Railroad/symbols/Railroad-Trackplan.kicad_sym` lines 462 and 662 carry `\"D\"` inside a Description. The same pattern is used for the symbol-name match (line 60) and the `extends` match (line 64). Reported fix on the branch: a quote-aware pattern plus an `unquote()`; `library_symbols()` should adopt it for all three.
3. Pins and units are joined by name only: `pins` is a flat `[(name, number, etype)]` without a unit and `units` is `{unit: [names]}` (`sch_text.py:62-70`); a pin name repeated across units is ambiguous. Unit 0 meaning "common to all units" is undocumented. `SymbolLibraryReader` has the same flattening (§1.6). This is the §3 "symbol library model" gap seen from a consumer.
4. No pin visibility (`hide`) or graphic style is exposed by either reader. The four libraries contain 807 `(hide yes)` nodes in all (`grep -c` per file: 306, 188, 160, 153), so a consumer cannot tell a hidden pin from a shown one.
5. kicad-cli discovery is reimplemented per CLI: `tools/parse_kicad_plant.py:74` (`--kicad-cli`), `tools/parse_kicad_controller.py:32`, `tools/contract/symbol_contact_sheet.py:27` (`KICAD_CLI` constant), `KicadCliNetlistExporter._discover_kicad_cli` in `netlist_reader.py`, and reportedly the new overview tool. One `find_kicad_cli()` in `kicad_services` is the place (and item 7 of §5 Option A moves it to kproj's).
6. `tools/kicad_services/__init__.py` inserts `~/Dropbox/KiCad/jBOM/src` into `sys.path` on import. Verified dependence: `netlist_reader.py`, `symbol_library_reader.py` and `schematic_reader.py` import `jbom` (lazily, inside methods); `sch_text.py` and `types.py` do not. The side effect therefore runs for the pure-text helpers too, and for every consumer of `types`.
7. `blocks()` keys on an exact tab depth (`sch_text.py:35`, `"\t" * depth`). Right for KiCad's output; hand-written fixtures must use literal tabs, and a file re-indented by any other tool is invisible to it. This is the "versioned formats" gap in concrete form.

## 4. Open GitHub issues

`gh` is authenticated as `plocher`. Repos with no remote: InterlockingPlant. Not a repo: `kproj-phase2`. Zero open issues: kDoctor, Railroad, EagleLib2KiCad.

jBOM (32 open; those touching KiCad services):
- #382 SPIKE: KiCad v10 variants (`kicad-cli sch export bom --variant`).
- #214 v8: EagleLib2KiCad adapter requirements under ADR constraints (service-surface-first; convergence).
- #204 generalized KiCad-aware heuristic signal framework (symbol/footprint taxonomy as search signals).
- #401 rollout sequencing of ratified CLI changes across kproj/kDoctor (the three CLIs are treated as one family).
- #342 wayfinder: shared datasheet document library for jBOM + kproj.
- #313, #302, #269: docs and BDD housekeeping; not KiCad-API work.

kproj (10 open):
- #66 SPIKE: KiCad v10 variants (depends on jBOM #382).
- #62 SPIKE: evaluate KiCad Prism.
- #64 SPIKE: Arduino sketches; #20 cross-domain project links (KiCad project ↔ sketch ↔ daughterboard) — a project-model concern.
- #45 config redesign; #40 `--init`; #32, #14, #12: not KiCad-API work.

FieldUnit-Subdivision (20 open; those touching the readers):
- #13 unify the SPCoast projects (done 2026-10-07; still open).
- #15 plant compiler: classify by Role/Kind (reader consumers).
- #17 desk compiler: code lines from the root sheet, field stations from encoding instances (needs sheet-instance reading, §3).
- #23 frozen desk fixture `South-cTc.net` is behind the drawing.
- #26 epic: rebuild model, link and generate layer to the ADRs.
- #30 cleanup pass: apply the symbol contract to the legacy drawings (bulk schematic edit, §3 byte-preserving edit).
- #31 documentation set from the data model (consumes readers; rendering).
- #8, #5, #1, #16, #18 to #22, #24, #25, #29: compiler and linker semantics, not KiCad I/O.

FieldUnit (10 open): none concern KiCad tooling (#18 to #29 are interlocking logic and docs).

## 5. Options

Both options assume the same end state: one set of contracts, in jBOM's `common/` + `services/` shape, consumed by all six repos. They differ in where the code lives during the next months and in what the owner pays now.

### Option A: evolve in situ, then extract on evidence

Table of contents for the API, each entry marked with its home and a TODO where the gap is. Home is the repo with the strongest implementation today.

1. `sexp` (read tree): jBOM `common/sexp_parser.py`. TODO: `(version N)` probe; typed accessors (`yes`/`no`, numbers, strings) so callers stop comparing `Symbol("yes")`.
2. `text` (byte-preserving edit): FieldUnit-Subdivision `tools/kicad_services/sch_text.py`. TODO: unit tests with golden bytes; node-level helpers recovered from the retired recipe (`set_prop`, `del_prop`, `rename_prop`, `rename_symbol`, `rename_pins`, `add_pin`, `edit_texts`, `split_units`, `prop_spans`, `pin_spans`); a formatter for inserted nodes; a `kicad-cli sym upgrade` / `sch export netlist` round-trip gate as a reusable test helper.
3. `symbols` (library model): FieldUnit-Subdivision; merge `SymbolLibraryReader` and `sch_text.library_symbols` into one reader that keeps units, pins per unit with positions, `extends`, `ki_locked`. TODO: graphics, write in sorted order, copy across libraries.
4. `netlist`: FieldUnit-Subdivision `NetlistReader`, `KicadCliNetlistExporter`. TODO: none for the model; the locator moves to item 7.
5. `schematic` (placed objects): jBOM `SchematicReader` + Subdivision `SchematicPlacementReader` merged into one symbol-instance record (fields, uuid, transform, unit, `instances`). TODO: wires, labels, junctions, sheets, `lib_symbols`.
6. `project`: jBOM `ProjectContext`, `project_discovery`, `project_variables_reader`. TODO: sheet tree with instance paths (fix the `Sheetfile` resolution base), `.kicad_pro` libraries and settings; the kproj sheet regex retired in favour of this.
7. `cli` (kicad-cli facade): kproj `common/kicad_install.py` + `services/design_analyzer.py` + exporters. TODO: adopt `KICAD_CLI` as the env var (or alias it), add `sch export netlist`, `sym export svg`, `sym upgrade`; fold Subdivision's two locators and jBOM's private one; a stderr filter for Fontconfig noise.
8. `tables` (lib tables): EagleLib2KiCad `kicad_environment_service.py`. TODO: nested `Table` entries (from kDoctor), `design_block_lib_table`, project-scope precedence; replace kproj's and kDoctor's regex parsers.
9. `footprints`: kDoctor `footprint_lineage_service.py`. TODO: a read model; write deferred.
10. `runtime` (lock files, plugin mode): jBOM `common/kicad_runtime.py`. TODO: adopted by Subdivision and kDoctor; Railroad's prose rule becomes a call.
11. `checks` (ERC/DRC interpretation): kDoctor `erc_drc_summary.py` on top of item 7.

Order of work:
1. Make `jbom` importable without `sys.path` hacks: `pip install -e ~/Dropbox/KiCad/jBOM` on this machine; remove the bootstrap from `tools/kicad_services/__init__.py` and `kDoctor/poc/sch_symbol_transfer.py`. One afternoon.
2. Items 2 and 3 in FieldUnit-Subdivision, because the symbol-library work is live this week (branch `feat/four-libraries`, uncommitted library edits in Railroad) and #30 needs a bulk schematic edit. Add tests and a round-trip gate first; then the node helpers.
3. Items 7 and 10: point Subdivision and kDoctor at kproj's locator and jBOM's lock guard; settle the env var name. Small PRs in three repos.
4. Items 4, 5, 6 upstreamed into jBOM `services/` (jBOM ADR 0004 already names jBOM as the contract home), with kproj dropping its sheet regex. Keep Subdivision's `kicad_services/` as a thin re-export until its callers move.
5. Item 8 stays in EagleLib2KiCad until kDoctor imports it; then converge per jBOM ADR 0004.
6. Extract to a package only when kDoctor's Phase 1 imports from two of these homes at once (its own stated trigger).

Near-term cost to the owner: low and incremental. Three or four small PRs across Subdivision, kproj, jBOM; no new repo, no release engineering; the symbol-library work continues uninterrupted. Risk: three homes for a while (jBOM, Subdivision, EagleLib2KiCad); the Dropbox checkout remains the de facto distribution until jBOM is released with the new services.

### Option B: stand-alone package now

Name: `kicad-primitives` (the name kDoctor's architecture already uses), import name `kicad_primitives`, repo `plocher/kicad-primitives`, MIT, Python 3.10+, `sexpdata` as the only runtime dependency.

Layout:

```
src/kicad_primitives/
  sexp/        parser, typed accessors, version probe          (from jBOM)
  text/        spans, node edit, formatter, round-trip gate    (from Subdivision sch_text + recipe)
  project/     discovery, .kicad_pro, sheet tree, lock files   (from jBOM, kproj)
  schematic/   symbol instances, wires, labels, sheets         (from jBOM, Subdivision, kDoctor)
  symbols/     library model, units, pins, extends, write      (from Subdivision, kDoctor)
  footprints/  .pretty read model                              (from kDoctor)
  tables/      sym/fp/design-block lib tables, ${VAR}          (from EagleLib2KiCad, kDoctor)
  netlist/     kicadsexpr reader                               (from Subdivision)
  cli/         locator, erc, drc, exports, netlist, sym        (from kproj, Subdivision)
tests/         golden files per KiCad version; round-trip suite
```

Migration order: (1) create the repo with `sexp`, `netlist`, `cli` and `runtime`, the pieces with tests today; (2) FieldUnit-Subdivision switches first (it has the fewest callers and the most churn); (3) kproj switches its locator and sheet walk; (4) jBOM switches `sexp_parser`, `project_context`, `kicad_runtime` and declares the dependency, releasing jBOM 8; (5) kDoctor builds its Phase 1 on the package; (6) EagleLib2KiCad contributes `tables`; (7) Railroad's spike tools and `kicad.mk` call the package's CLI.

Near-term cost to the owner: a new repo with CI, versioning and PyPI (or a path dependency in four `pyproject.toml` files), a jBOM major release, and four consumer migrations before any new capability lands. The owner is mid-way through a symbol-library redesign and a desk-codegen design; both would pause. Benefit: one home, one test suite, from day one; the "third consumer" question is answered by fiat.

### Recommendation

Option A, with the extraction trigger made explicit (kDoctor Phase 1 importing from two homes). Reasons:

- Every repo's own docs already point the same way: jBOM is the contract home (jBOM ADR 0004/0016, kproj ADR 0001/0003), extraction waits for evidence (kDoctor `docs/ARCHITECTURE.md` Phase 2), and Subdivision's own note says "contribute upstream to jBOM" (`docs/archive/TBD-shared-kicad-python-api.md`). Option A is the plan the repos agreed on; Option B overrides it.
- The strongest pieces are unevenly distributed (read: jBOM; edit: Subdivision; tables: EagleLib2KiCad; cli: kproj). A package built now would start as a copy of four styles; evolving each in place first lets the tests and the merged readers settle before the move.
- The live work (symbol libraries, #30 bulk edit, desk codegen) needs item 2 and 3 immediately and nothing else.
- The functional-gates principle (owner, 2026-10): tests and a round-trip gate before a golden package.

## 6. Pending decisions

1. Adopt Option A (evolve in situ, extract on the kDoctor two-homes trigger). 
   - DECISION: AGREE
  
2. Install `jbom` editable on this machine and delete the `sys.path` bootstraps in Subdivision and kDoctor. Default: yes, first step.
   - DECISION: Why does jbom need to be editable for this project to proceed?  jBOM and kproj are already installed via PYPI...
  
3. Home for the byte-preserving editor and the symbol-library model until extraction
   - DECISION: Rather than churning between multiple repos, put the extracted files directly into the `~/Dropbox/KiCad/kicad_services/` repo where they can be manipulated directly.
  
4. Recover the retired recipe's node helpers into `sch_text.py` with tests, rather than leaving them in git history, and fold in §3.1 items 1 to 4 (one property call, quote-aware regex, pins keyed by unit, `hide` exposed).
   - DECISION: AGREE

5. Merge `SymbolLibraryReader` (sexpdata) and `sch_text.library_symbols` (regex) into one reader that keeps units. 
   - DECISION: AGREE

6. kicad-cli locator: adopt kproj's `find_kicad_cli` everywhere (five copies in Subdivision alone, §3.1 item 5); env var name. Default: kproj's function, reading `KICAD_CLI` first and `KPROJ_KICAD_CLI` as a kproj alias.
   - DECISION: AGREE

7. Lib-table parsing: adopt EagleLib2KiCad's environment service as the one implementation and add kDoctor's nested-table handling to it.    
   - DECISION: AGREE

8. File the two sheet-walk defects (jBOM resolves `Sheetfile` from the project dir; kproj's `(sheetfile` token matches nothing in KiCad 10 files) as issues. Default: yes, one issue each.
   - DECISION: file an issue in each repo, make a feature branch in that repo, fix the bug, create and submit a PR that closes the issue.
  
9.  Package name for the eventual extraction. Default: `kicad-primitives`.
   - DECISION: AGREE

10. Fix `Railroad/Archive/SPCoast/kicad.mk` defaults (`SYMBOLS`, `LIB`) to the cutover libraries, or retire the file into Subdivision `tools/` as `AGENTS.md` expects. Default: retire into Subdivision when the desk `make` target is designed.
   - DECISION: the archive is a frozen copy, so retire into Subdivision is the right path

11. Commit Railroad's `Scratch/tools` spikes somewhere (they are gitignored) or record that they are disposable. Default: move the two binding passes beside what they generate in Subdivision `docs/archive/`; leave the generators.
   - DECISION: AGREE

12. Close FieldUnit-Subdivision #13 (unification done 2026-10-07). Default: close with a pointer to `docs/archive/unify/`.
   - DECISION: DISAGREE - out of scope for this effort

13. Fix kDoctor `README.md`'s link to the missing `docs/DOCTRINE.md`. Default: yes, in kDoctor.
   - DECISION: AGREE - this can be a direct edit and push from main, as kdoctor is still in early development

14. Move the jBOM `sys.path` bootstrap out of `tools/kicad_services/__init__.py` into the three modules that import `jbom` (§3.1 item 6), until decision 2 removes it. Default: yes.
   - DECISION: AGREE - but see comments on #2 above

15. Update `tools/contract/lint_libraries.py:32` to the four library names or retire it (its (Role, Kind) table predates the field-based lint). Default: retire; `lint_symbol_fields.py` is the gate.
   - DECISION: DISAGREE - out of scope for this effort
