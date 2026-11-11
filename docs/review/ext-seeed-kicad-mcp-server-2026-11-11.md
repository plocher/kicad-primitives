# External survey: Seeed-Studio kicad-mcp-server (2026-11-11)

Status: research input for Structured-B synthesis. Not an ADR.

Subject: [Seeed-Studio/kicad-mcp-server](https://github.com/Seeed-Studio/kicad-mcp-server) (local clone `~/Dropbox/workspace/kicad-mcp-server`, HEAD `0b445be`, 2026-10-22). All paths below are relative to `src/kicad_mcp_server/` unless they start with a repo-root name (`README.md`, `CLAUDE.md`, `tests/`, `pyproject.toml`).

Purpose: this server is the closest public dress rehearsal for proposed [ADR 0012](../adr/0012-future-mcp-tool-surface.md). The note tests each ADR 0012 tool rule against what the server actually does.

Brief: [external-survey-brief-2026-11-11.md](external-survey-brief-2026-11-11.md). Exemplar: [hitl-comparison-2026-11-10.md](hitl-comparison-2026-11-10.md).

## What it is

An **MCP server** (FastMCP, stdio) in Python. It is not a reusable KiCad library. All KiCad logic lives inside tool modules and private parsers.

| Field | Value | Evidence |
| --- | --- | --- |
| Shape | One FastMCP server, 47 registered tools, 1 resource (`kicad://config`) | `server.py`; `grep @mcp.tool tools/*.py` |
| Language | Python ≥ 3.10 | `pyproject.toml` |
| Runtime deps | `fastmcp>=3.2,<4`, `mcp[cli]`, `pydantic`, `jinja2`, `python-dotenv`, `kicad-skip` | `pyproject.toml` |
| License | Declared MIT in `pyproject.toml` (`license = { text = "MIT" }`, OSI classifier) and `README.md:316-318`. **No `LICENSE` file in the repo.** `docs/README.md:225` links `../LICENSE`, which does not exist. This explains the missing SPDX id on GitHub. | repo root listing |
| KiCad target | Mixed. README title says 9.0+; README requirements say 8.0+ (9 or 10 recommended); `CLAUDE.md` says KiCad 9 / `20240130`; code writes `20250114` schematics and then runs `kicad-cli sch upgrade` (`tools/project.py:40-57,197`). Recent commits parse KiCad 10 ERC/DRC JSON. | as cited |
| Activity | 96 commits, 2026-01-25 to 2026-10-22; 9 authors, 84 commits by one author | `git log`, `git shortlog` |
| Maturity | `version = "0.1.0"`, "Development Status :: 3 - Alpha". 112 test functions. CI: ruff + pytest on Ubuntu and Windows, Python 3.10/3.13. No macOS job. KiCad-dependent tests self-skip in CI because KiCad is not installed there. | `pyproject.toml`, `.github/workflows/ci.yml`, `tests/` |
| Self-description | README positions editing as experimental and recommends the KiCad GUI for design work (`README.md:252-261`). | README |

Unused or stale pieces (code fact):

- `kicad-skip` is a declared dependency, but no module imports it. `parsers/schematic_parser.py` says "wrapper using kicad-skip" in its docstring and is a regex parser.
- `templates/**/*.j2` (pytest, Unity, Arduino, ESP-IDF, ST HAL, device-tree) are not loaded by any tool. `tools/device_tree.py:65,516` uses inline Jinja strings. "Hardware test code generation" (`README.md:12,199`) is a **README claim, not verified in code**: no registered tool renders those templates.
- `CLAUDE.md` describes "6 tools" and lists test generation, library management and LCSC as out of scope. The code has 47 tools, a parts registry, and device-tree generation. `CLAUDE.md` is stale.

## How it touches KiCad

| Concern | What the server does | Evidence |
| --- | --- | --- |
| Schematic parse model | Own **regex + line-based paren counting**. No sexpr library. Paren counting ignores string literals. Encoding fallback chain utf-8 → latin-1 → cp1252 → iso-8859-1 → utf-8 ignore. | `parsers/schematic_parser.py:100-127,172-204,305-406` |
| Schematic "nets" | `list_schematic_nets` returns **labels, global labels, hierarchical labels and power-symbol names**. It does not compute connectivity. `SchematicNet.pins` is always empty (the code says so in `tools/hierarchical_analysis.py:76-78,154-155`). | `parsers/schematic_parser.py:407-467` |
| Net tracing | **`kicad-cli sch export netlist --format kicadxml`** into a temp file, parsed with `xml.etree`. No own connectivity engine for the agent-facing trace. A geometric wire tracer exists in the parser (`trace_wire_network`, `build_wire_network`) but the trace tools use the netlist. | `tools/netlist.py:39-131`, `parsers/netlist_parser.py` |
| `pcbnew` | (1) PCB analysis: `pcbnew.LoadBoard` **in the server process** when importable; silent fallback to a text parser on any exception. (2) Project creation: `NewBoard` + `SaveBoard` in a **subprocess** under KiCad's Python (`stdin=DEVNULL`). | `parsers/pcb_parser_kicad.py:93-105`, `tools/pcb.py:8-15`, `tools/project.py:22-38,174-188`, `utils/kicad_python.py` |
| `kicad-cli` | ERC, DRC (`--severity-all`, `--schematic-parity` when a sibling `.kicad_sch` exists), netlist, Gerber, drill, STEP, 3D render, schematic SVG, `sch upgrade`. Runs off the event loop with `asyncio.to_thread`. ERC/DRC force `LANG=C.UTF-8` so report text parses. | `utils/kicad_cli.py`, `tools/validation.py:306-362,489-530`, `tools/pcb_layout.py`, `tools/visualization.py` |
| CLI discovery | `KICAD_CLI` → `PATH` → detected install dir; cached in a module global. | `utils/kicad_cli.py:30-72` |
| KiCad IPC | None found. | grep |
| Direct file generation | Yes. Schematic inserts (`add_component_from_library`, `add_wire`, `add_label`, `add_global_label`, `add_hierarchical_label`); whole-board text template (`setup_pcb_layout`); template project copy and personalization. | `tools/schematic_editor.py`, `tools/pcb_layout.py:73-165`, `tools/project.py:93-171` |
| Write method | Read whole file, string-splice, `Path.write_text`. **No temp file and rename, no backup, no fingerprint check, no lock check, no quote escaping in label/value text.** `add_component_from_library`, `add_wire`, `add_label` use platform default encoding for read and write; label tools use UTF-8. | `tools/schematic_editor.py:419,481,510,581,614,630,653,669` |
| Byte preservation | Untouched content survives except trailing whitespace (`content.rstrip()` before append). Inserted text is not KiCad-formatted. New symbol instances go at end of file, after `sheet_instances` / `embedded_fonts`. Embedded `lib_symbols` text is re-indented and stripped of four attributes by regex. | `tools/schematic_editor.py:90-145,336-340,572-579` |
| Hierarchy | Read: `get_components(recursive=True)` follows `Sheetfile` depth-first, cycle-safe. Netlist and ERC tools redirect a sub-sheet path to the root schematic (`<project>.kicad_sch`). No sheet-instance model: references come from the `Reference` property, not `(instances …)`. | `parsers/schematic_parser.py:493-538`, `tools/netlist.py:23-36`, `tools/validation.py:144-157` |
| Library tables and `${VAR}` | **None.** `add_component_from_library` looks only in KiCad's stock symbol directory. No `sym-lib-table`, no `fp-lib-table`, no `${VAR}` resolution. Parts-registry downloads are dropped into a directory and not registered in any table. | `tools/schematic_editor.py:52-61`, `utils/kicad_version.py:63` |
| Netlist content kept | Component ref/value/footprint/libsource; net name/code; node ref/pin. **Pin electrical type (`pintype`) is dropped.** Pin types for conflict checks come from a separate regex parse of `lib_symbols`. | `parsers/netlist_parser.py:51-109`, `tools/pin_analysis.py:461-489` |

### Is "100% accurate pin-level tracing" true?

README claim: `README.md:9,153`. Partly true in code, with three cracks.

1. **Holds at the source.** Connectivity comes from KiCad's own netlist exporter (`tools/netlist.py:77-89`). The parser maps it faithfully (`parsers/netlist_parser.py:84-102`).
2. **Stale-netlist reuse.** `_ensure_netlist` (`tools/pin_analysis.py:19-60`) returns the first existing file among `<sheet>.xml` next to the schematic, `<tmp>/<stem>.xml`, or the hashed cache path. It does **no freshness check**. `trace_hierarchical_connection`, `analyze_hierarchical_nets`, all pin-analysis tools and all device-tree tools use it. After an `add_wire` or GUI edit, they can answer from an old netlist. ERC/DRC have an mtime staleness check (`tools/validation.py:57-62`); the netlist path does not. A same-named unrelated `.xml` beside the sheet is also accepted.
3. **Failure detection by emoji.** `_ensure_netlist` treats a result as failure only if it contains `❌` (`tools/pin_analysis.py:57`). The kicad-cli failure branch of `generate_netlist` returns `⚠️ Automatic netlist generation failed` (`tools/netlist.py:101-115`), with no `❌`. The caller then probes again and can pick up a stale file.
4. **Probable defect (inference, not executed).** `NetlistParser.trace_connection(ref)` without a pin returns `nets: {name: [ {pin, connected_to}, … ]}` (a list per net, `parsers/netlist_parser.py:215-234`). `trace_netlist_connection` indexes it as a dict, `net_info['pin']` (`tools/netlist.py:192-201`). That raises `TypeError`, caught as "❌ Error tracing netlist". No test calls `trace_netlist_connection`. The per-pin branch works.

Also: `get_netlist_nets` truncates each net to 10 pins in its output (`tools/netlist.py:254-257`). That is display, not accuracy, but an agent sees a partial net.

## API / tool surface

47 tools. Every tool takes file paths, returns a string (or an `Image`), and holds no handle between calls.

| Group | Tools | Granularity |
| --- | --- | --- |
| Schematic read (regex) | `list_schematic_components`, `get_symbol_details`, `search_symbols`, `list_schematic_nets` (labels only), `get_schematic_info`, `search_components_by_type` | One-job reads |
| Netlist | `generate_netlist` (kicad-cli → temp XML path), `trace_netlist_connection`, `get_netlist_nets`, `get_netlist_components` | One-job; agent must pass the netlist path from the first call |
| Hierarchy | `trace_hierarchical_connection`, `analyze_hierarchical_nets` | **Composite**: schematic parse + hidden netlist reuse/generate + trace |
| PCB read | `list_pcb_footprints`, `get_pcb_statistics`, `analyze_pcb_nets`, `find_tracks_by_net`, `analyze_pcb_signal_integrity`, `analyze_pcb_power_integrity` | One-job reads; backend switches silently between `pcbnew` and text |
| Checks | `run_erc`, `run_drc`, `get_erc_violations`, `get_drc_violations`, `export_erc_report`, `export_drc_report` | `run_*` one-job (with sub-sheet → root redirect). `get_*` run the check when the report is stale. `export_*` always rerun the check, then copy |
| Pin analysis | `analyze_pin_functions`, `detect_pin_conflicts`, `extract_pinmux_config` | Composite: netlist + lib_symbols regex + net-name heuristics |
| Device tree | `generate_device_tree`, `extract_gpio_config`, `extract_i2c_devices`, `extract_spi_devices`, `extract_power_domains`, `validate_pin_configuration` | Composite and heuristic (net-name substrings, inline templates); optional file write |
| Edit | `add_component_from_library`, `add_wire`, `add_label`, `add_global_label`, `add_hierarchical_label` | One-job by name; each **writes the file immediately**. `add_component_from_library` also embeds the library symbol |
| Project / board | `create_kicad_project`, `setup_pcb_layout`, `export_gerber` | Composite. Project = pcbnew subprocess + schematic text + `kicad-cli sch upgrade`. Gerber = gerbers + best-effort drill |
| Visual / export | `render_pcb` (returns `Image`), `export_pcb_3d`, `export_schematic_svg` | One-job exporters |
| Parts registry | `search_parts_registry`, `get_registry_part`, `download_registry_part` | One-job; JSON output |

Overwrite behaviour of write tools (code fact):

| Tool | On existing target |
| --- | --- |
| `create_kicad_project` | Refuses if `<name>.kicad_pro/sch/pcb` exist (`tools/project.py:248-257`). Template copy then overwrites other files silently (`shutil.copytree(dirs_exist_ok=True)`, `shutil.copy`, `tools/project.py:107-118`). |
| `setup_pcb_layout` | **Overwrites `<schematic>.kicad_pcb` with an empty outline board. No existence check.** (`tools/pcb_layout.py:52-56,165`) |
| `export_erc_report` / `export_drc_report` | `shutil.copy` over `output_path` (`tools/validation.py:867,931`). |
| `generate_device_tree` | `open(output, "w")` (`tools/device_tree.py:520-525`). |
| `render_pcb` / `export_pcb_3d` | Default output beside the PCB; STEP passes `--force` (`tools/visualization.py:65,133`). |
| `download_registry_part` | `open(path, "wb")` with the remote basename (`utils/parts_registry.py:188-197`). A remote file named like an existing local library overwrites it. |
| Schematic `add_*` | Rewrites the whole sheet file in place, non-atomic. |

## Agent and tooling glue

| Concern | What the server does | Evidence |
| --- | --- | --- |
| Prompt vs code | One short `instructions` string in `FastMCP(...)`; tool docstrings carry usage hints and "next step" suggestions. No skill pack. `CLAUDE.md` is a developer doc, not an agent skill. | `server.py:8-21` |
| Evidence shape | **Markdown prose with emoji verdicts** (`✅`, `❌`, `⚠️`, sometimes `X`/`OK`). Counts are Markdown list lines. Parts-registry tools return JSON. `render_pcb` returns an image. No machine-readable verdict field on ERC/DRC. | `tools/validation.py:132-141,406-441`, `tools/device_tree.py:378,527` |
| Gates and refusal | Good examples: ERC/DRC delete the old report before running, so a report on disk is from this run (`tools/validation.py:342-344,516`); "kicad-cli exited cleanly but wrote no report" is not reported as pass (`tools/validation.py:387-396`); `add_component_from_library` refuses when the symbol definition is missing (`tools/schematic_editor.py:564-570`); `export_gerber` reports "no files produced" by mtime diff (`tools/pcb_layout.py:248-292`). No fab gate: `export_gerber` runs without ERC/DRC. | as cited |
| Session state | None for documents. Process-wide caches only: kicad-cli path, KiCad Python path, install dir, parts index (`_INDEX_CACHE`), and temp-dir report/netlist files keyed by an 8-hex digest of the resolved source path. Temp files persist across sessions and processes. | `utils/kicad_cli.py:27`, `utils/parts_registry.py:122`, `tools/netlist.py:12-20`, `tools/validation.py:23-34` |
| Versioning / rollback | None. No backup, no undo, no save/discard. README: "KiCad must be closed and reopened to see file changes" (`README.md:259`). | |
| Peer locks / GUI concurrency | No lock query, no refusal. | grep for `lck`/`lock`: no hits |
| Isolation | None. kicad-cli and `pcbnew` use the user's KiCad profile. `pcbnew.LoadBoard` runs in the server process. Child Python gets `stdin=DEVNULL` so it does not eat the stdio transport (`utils/kicad_python.py:85-91`); kicad-cli calls do not set that. | |
| Token / context | Output caps: ERC table first 20 rows; net pin lists first 10; hierarchy groups 20/30. Errors often include full Python tracebacks. | `tools/validation.py:414-418`, `tools/netlist.py:254`, `tools/hierarchical_analysis.py:202-204` |
| Parts registry safety | HTTPS only; host must be the registry host, a subdomain, or `PARTS_REGISTRY_ASSET_HOSTS`; cross-host redirects blocked; part id restricted to `[A-Za-z0-9_-]`; filename extension allow-list per format; 50 MB cap; `save_dir` must exist and resolve under cwd, home, or `PARTS_REGISTRY_SAVE_ROOTS`. Gaps: home is a wide root; existing files are overwritten; no atomic write; content is not parsed or validated as KiCad; the comment claims truncated streams are caught, but code only rejects `Content-Length > cap` and never compares `len(data)` with `Content-Length`. Not tested in `tests/`. | `utils/parts_registry.py:45-197`, `tools/parts_registry.py:77-142` |

## Comparison matrix

| Axis | Seeed kicad-mcp-server | This package (locked ADRs) |
| --- | --- | --- |
| Product shape | Single MCP server; KiCad logic inside tools | Installable library; MCP is a later sibling (ADR 0012 C, proposed) |
| Design home | KiCad files, read by path per call | KiCad files plus project and library context |
| Write model | Read-splice-`write_text`, append-only inserts, regex | Source-preserving localized edit on one parser (ADR 0003) |
| Lifecycle | None; each tool call is the unit; write on call | Open, read, modify, validate, write, close; save/discard/revert (ADR 0008, 0011) |
| Executive vs primitives | Mixed. Many one-job reads; composites hide netlist generation, check reruns, and pcbnew/CLI sequences | Primitives only; client or recipes own sequence (ADR 0009) |
| Hierarchy | Recursive component read; root redirect for CLI; no sheet-instance model | `Project` → `Schematic` → `SheetFile`, sheet instances (#79) |
| Library tables / `${VAR}` | None; stock symbol dir only | First-class area (ADR 0002) |
| Connectivity | kicad-cli XML netlist; pin types dropped; no compare tool; stale reuse in composites | `project.netlist()` before/after; typed pin-to-net equality (ADR 0011) |
| Reuse across apps | None; parsers are private to the server | One package, many consumers after 1.0 |
| Agent host concerns | Inside the server: caches, Markdown envelopes, no sessions, no isolation | Out of package; server owns them (ADR 0012 rules 7–8) |
| License | Declared MIT; no license text file in repo | MIT |

## Pressure on our decisions

### Claims that hold

| Claim | Why Seeed does not overturn it |
| --- | --- |
| ADR 0003 one source-preserving parser | Seeed uses three ad hoc parse styles (line paren counting, char paren counting that ignores strings, regex field grabs) and can only **append**. It cannot update an existing property. Its own README calls editing experimental. That is the ceiling of a stringly approach. |
| ADR 0008 / 0011 buffered lifecycle with explicit save | `setup_pcb_layout` silently replaces an existing board. Schematic edits write in place with no backup, no atomic rename, and no discard. These are the exact failures our lifecycle rules forbid. |
| ADR 0009 no hidden steps | `_ensure_netlist` is a hidden step. It reuses stale netlists and detects failure by searching for `❌`. A hidden step turned a correct primitive (kicad-cli netlist) into a wrong answer. |
| ADR 0011 typed netlist equality | Seeed's netlist drops pin electrical type, then reconstructs it with a second regex parse to detect conflicts. Keeping pin type in the netlist model avoids that double source. |
| ADR 0007 private CLI discovery | Seeed needs the same rule (env override, PATH, install dir, cached). It stays a private helper there too. Order differs (PATH before platform defaults) but the shape matches. |
| ADR 0012 rule 4 "no silent overwrite" | Six Seeed write paths overwrite silently (table above). Only `create_kicad_project` refuses, and only for the three main project files. The rule is needed. |
| ADR 0012 rule 6 "structured evidence" | Seeed's own code cannot read its own verdicts reliably (`❌` vs `⚠️`). Prose-and-emoji evidence is fragile even inside one codebase. Strong support. |
| ADR 0002 library tables as a first-class area | Seeed has no table support, so `add_component_from_library` only works for stock symbols, and downloaded parts are unusable until a human edits a table. The gap shows the need. |

### Claims worth attacking

| Pressure | Possible crack | What would change if the crack is real |
| --- | --- | --- |
| ADR 0012 rule 3 "mutations stay buffered; save is an explicit tool" | Seeed is stateless: path in, string out, file written. That is the common MCP shape. Buffering needs server-held handles across calls, a crash story for pending edits, and a GUI-concurrency story. ADR 0012 puts sessions server-side (rule 7) but defines no handle, timeout, or on-exit behaviour. | ADR 0012 wording: name a document handle, state the default `on_close` for server exit and idle timeout (map to ADR 0011 `on_close`), and say what a stateless client gets. Follow-up: **ADR 0012 wording**, then **grill**. |
| ADR 0012 rule 5 "engine tools are explicit" | Seeed began explicit ("First export a netlist", `README.md:145`) and moved to implicit `_ensure_netlist` for derived tools. Agents and users seem to want derived reads without a manual netlist step. | If implicit is demanded, the rule needs a freshness contract: a derived tool may reuse a netlist only when its source fingerprints match (ADR 0011 fingerprint check is a ready basis), and the response must name the netlist it used. Follow-up: **ADR 0012 wording**. |
| ADR 0006 / 0012 "pcbnew stays private and purpose-limited" | Seeed's best PCB numbers (track length incl. arcs, design-rule values, diff-pair data) come from `pcbnew`; the text fallback loses them. KiCad-native new-file creation also goes through `pcbnew` + `kicad-cli sch upgrade`. | PCB report parity may need a private `pcbnew` backend for some derived values, or we accept a smaller PCB report surface. ADR 0012 open question 5 becomes concrete. Follow-up: **grill**. |
| ADR 0012 rule 2 "composites list each step" | Seeed's composites (`get_drc_violations`, `export_erc_report`, `generate_device_tree`) return one prose result and do not list steps. Yet agents used them, judging from issues fixed in the log. Step lists cost tokens. | Keep the rule, but specify a compact step record (name, verdict, artifact path) rather than full sub-results. Follow-up: **ADR 0012 wording**. |
| ADR 0012 rule 8 "isolate KiCad profile for every engine call" | Seeed runs kicad-cli and in-process `pcbnew` on the user profile with no reported profile damage in the log. Isolation may be needed only for `pcbnew` and GUI-like engines, not for read-only CLI exports. | Narrow rule 8 to engines that write profile state, or keep it broad and accept cost. Needs evidence, not taste. Follow-up: **grill**. |
| Sub-sheet path handling | Seeed redirects any sub-sheet path to the root for netlist and ERC, by naming convention. Agents pass whatever sheet they hold. | Our `Project` entry already accepts any file in the project directory. Confirm that MCP tools take any sheet path and resolve the project, not demand the root. Follow-up: **ADR 0012 wording** (one line). |
| Peer lock is a query only | Seeed writes while KiCad may be open and tells the user to reopen. No damage report, but GUI save would clobber agent edits. | Package rule stays query-only. ADR 0012 server policy should state whether write tools refuse when locked. Follow-up: **ADR 0012 wording** (already an open question 6). |

## Steal list

Each item names its layer. None goes into `kicad_primitives` public API unless stated.

1. **Delete-before-run for engine reports** (`tools/validation.py:342-344`). Private engine helper in the package (ADR 0007 machinery) and MCP server. A report on disk then proves this run.
2. **Freshness check before reusing derived artifacts** (ERC/DRC `_report_is_stale`). MCP server, keyed on ADR 0011 fingerprints rather than mtime only. Seeed's mtime check misses sub-sheets in subdirectories (`_schematic_files` globs one directory).
3. **Force English locale for parseable CLI reports, with language-neutral fallback** (`utils/kicad_cli.py:75-84`; tests with Czech ERC fixture `tests/fixtures/reports/erc_kicad10_cs.json`). Private engine helper; relevant to kDoctor-style ERC interpretation.
4. **KiCad 10.0.6 ERC JSON position-scale quirk** (positions 100× too small; corrected by comparing with schematic object positions; `docs/VALIDATION.md`, `parsers/check_report_parser.py`). Knowledge for whichever layer parses ERC JSON. Verify against our KiCad before relying on it.
5. **`stdin=DEVNULL` for child processes under a stdio MCP server** and `asyncio.to_thread` for CLI calls. MCP server runner.
6. **Parts-download guard set** (HTTPS, host allow-list, no cross-host redirect, id charset, extension allow-list, size cap, save-root confinement). MCP server or a BOM/parts consumer. Add: refuse overwrite, atomic write, length check, and table registration as a separate explicit tool.
7. **Image-returning render tool** for multimodal review. MCP server, thin over a package export.
8. **Let KiCad write brand-new files** (`pcbnew.NewBoard` + `kicad-cli sch upgrade`). Reference for a future "create" operation; engine use must stay that operation's stated purpose.
9. **Pin-anchor geometry** (library Y-up to sheet Y-down, rotation, unit filter; `tools/schematic_editor.py:253-333`). Reference only, for future placed-symbol or label insertion in `schematics`. Re-derive on our parser.
10. **End-to-end edit test verified by kicad-cli netlist** (`tests/test_tools/test_hierarchical_labels.py:121+`). Matches our functional-gate style; confirms the gate is cheap.

## Reject list

1. Regex and paren-count parsing as the read or edit core (violates ADR 0003 "one parser").
2. Write-on-call edits with non-atomic `write_text`, no backup, no conflict check.
3. Markdown-with-emoji as the gate verdict, and code that greps its own emoji.
4. Silent backend fallback that changes result semantics (`tools/pcb.py:8-15` catches any exception from `pcbnew` and switches to text parsing; some tools do not say which mode ran).
5. Hidden netlist reuse without freshness.
6. Net-name substring heuristics (I2C/SPI/GPIO, I2C address from net name) inside any shared library layer. If wanted, they belong in a consumer or server tool, labeled heuristic.
7. Declared dependencies and templates that no code uses.
8. "Labels" presented as "nets" (`list_schematic_nets`). Name things by what they are.

## Overlap with our donors

| Seeed piece | Donor that already does this job | Note |
| --- | --- | --- |
| `utils/kicad_cli.py` discovery and exporters (Gerber, drill, STEP, SVG, render) | kproj | kproj facade is the planned basis (ADR 0007). |
| ERC/DRC JSON parsing, severity, exclusions | kDoctor | Seeed's KiCad 10 fixtures and the position-scale quirk are useful test inputs. |
| Netlist XML reader | FieldUnit-Subdivision (netlist reader, connectivity gate) | Subdivision keeps more (and gates edits); Seeed drops pin types. |
| Schematic insert of symbols/labels/wires | FieldUnit-Subdivision (byte-preserving span edits) | Subdivision edits in place; Seeed only appends. |
| Project discovery, root-sheet by name | jBOM (project context), our `projects` | Seeed uses "one `.kicad_pro`, root = same stem"; ours is the same rule plus `top_level_sheets`. |
| Library lookup | EagleLib2KiCad (tables, `${VAR}`) | Seeed has none. |

## Sources read

| Path (external repo) | Depth |
| --- | --- |
| `README.md`, `CLAUDE.md`, `pyproject.toml`, `requirements.txt`, `.github/workflows/ci.yml` | Read |
| `server.py`, `config.py`, `tools/__init__.py` | Read |
| `tools/netlist.py`, `parsers/netlist_parser.py` | Read in full |
| `tools/schematic_editor.py` | Read in full |
| `tools/project.py`, `tools/pcb_layout.py`, `tools/parts_registry.py`, `utils/parts_registry.py` | Read in full |
| `utils/kicad_cli.py`, `utils/kicad_python.py`, `utils/file_handlers.py` | Read in full |
| `tools/validation.py` | Lines 1-200, 300-540, 761-953 |
| `tools/hierarchical_analysis.py` | Read in full |
| `parsers/schematic_parser.py` | Lines 1-30, 100-206, 305-340, 407-540; grep of the rest |
| `parsers/pcb_parser_kicad.py`, `tools/pcb.py` | Lines 1-200 each |
| `tools/pin_analysis.py` | Lines 1-200; grep for pin-type handling |
| `tools/visualization.py` | Lines 1-200 |
| `tools/device_tree.py` | Lines 288-617; grep for templates |
| `tests/test_tools/test_hierarchical_labels.py` | Lines 120-175; grep across `tests/` |
| `docs/VALIDATION.md` | First 60 lines (summarized) |
| Skimmed or not read: `parsers/pcb_parser.py` (text fallback), `parsers/check_report_parser.py`, `models/types.py`, `utils/kicad_version.py`, `tools/schematic.py`, `tools/schematic_search.py`, remaining `tools/pcb.py`, `tools/device_tree.py` and `tools/pin_analysis.py` bodies, `docs/DEVICE_TREE.md`, `docs/PIN_ANALYSIS.md`, `docs/TESTING.md`, `docs/INSTALLATION.md`, most of `tests/` | Not read in depth |
| This repo: `docs/review/external-survey-brief-2026-11-11.md`, `docs/review/hitl-comparison-2026-11-10.md`, `docs/adr/0012-future-mcp-tool-surface.md`, `AGENTS.md` (as provided) | Read |

## Confidence and gaps

- **Nothing was executed.** Per the brief, I did not install or run the server or its tests. All findings come from reading code and `git log`.
- **`trace_netlist_connection` all-pins defect** is an inference from type shapes (`parsers/netlist_parser.py:215-234` vs `tools/netlist.py:192-201`). High confidence; not run.
- **Stale-netlist reuse** is a code fact (`tools/pin_analysis.py:39-60`). Whether it bites in practice depends on agent call order; not observed.
- **KiCad acceptance of appended symbol instances** (placed after `sheet_instances`, no `(instances …)` block) was not tested here. Seeed's own end-to-end test exports a netlist from such a file, which suggests kicad-cli loads it; annotation behaviour in the GUI is unverified.
- **Text PCB fallback accuracy** (`parsers/pcb_parser.py`) not reviewed.
- **ERC position-scale quirk** is a Seeed doc and code claim; not checked against our KiCad 10 install.
- **License**: metadata says MIT; no license text file exists. I make no legal judgment. Reuse of code (not ideas) should wait for an owner decision or an upstream `LICENSE` file.
- **Upstream state beyond the local clone** (issues, PR discussion, stars) was not checked; the clone HEAD is 2026-10-22.
- Device-tree and pin-analysis heuristics were sampled, not audited.
