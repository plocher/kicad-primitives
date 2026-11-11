# External survey: KiCad-AI-Assistant (2026-11-11)

Status: research input for Structured-B synthesis. Not an ADR.

Subject: [paul356/KiCad-AI-Assistant](https://github.com/paul356/KiCad-AI-Assistant) (local clone `~/Dropbox/workspace/KiCad-AI-Assistant`, `main` at `8f94f8b`, tag `0.2.10`), compared with this package's ADRs.

Brief: `docs/review/external-survey-brief-2026-11-11.md`. Exemplar: `docs/review/hitl-comparison-2026-11-10.md`.

All external paths below are relative to the clone root. "README claim" marks a statement that I did not find in code.

## What it is

Two products in one repo:

| Part | Path | Job |
| --- | --- | --- |
| MCP server `kcaa` | `kcaa/` | FastMCP server with about 110 tools for schematic, PCB, libraries, routing, versions, skills. PyPI name `kcaa`. |
| KiCad action plugin | `kicad_plugin/` | wx chat panel inside the PCB editor. Runs its own LLM client loop, starts `kcaa` as a subprocess, and adds a "framework" layer (snapshot, reload, context budget). |

- **Language:** Python. `requires-python >=3.10` (`pyproject.toml`). Plugin runs in KiCad's bundled Python; server runs in a separate `uv` venv (`docs/plugin/architecture.md` §8).
- **License:** MIT (`LICENSE`, copyright "Lama Al Rajih" 2025). The repo is a fork of the Lama Al Rajih `kicad-mcp` lineage: first commits 2025-03-20 by "Lama"; 393 of 449 commits by `paul356`.
- **KiCad target:** 10.0. README says "Tested on KiCad 10.0 / Linux & Windows". macOS paths exist in code and docs but are not stated as tested.
- **Activity:** 449 commits from 2025-03-20 to 2026-11-09; 112 commits since 2026-08-01. Tags `0.2.5` to `0.2.10`. `develop` → `main` release branch policy. CI workflows in `.github/workflows/`.
- **Maturity signals:** "Development Status :: 4 - Beta". Large unit and integration test tree (`tests/unit`, `tests/integration`, about 60 test files). Detailed backlog with issue links (`docs/develop_backlog.md`). Many fixes reference real user bugs. Some design docs are stale against code (see Confidence and gaps).

## How it touches KiCad

### Backend map

| Backend | Used for | Evidence |
| --- | --- | --- |
| `kicad-skip` (`skip`) parse and whole-tree write | All schematic edits: symbols, wires, labels, no-connects, sheets, groups | `kcaa/utils/schematic_sexp_utils.py:11-28` (`sch.write(tmp)` then `os.replace`); `kcaa/utils/skip_compat.py`; `docs/skip_library_notes.md` |
| `sexpdata` load and full re-serialize | All PCB edits (placement, properties, outline, zones, tracks, vias, groups), `.kicad_dru` rules | `kcaa/utils/pcb_sexp_utils.py:37-87` (`sexpdata.dumps` plus regex newlines); `kcaa/utils/pcb_design_rules.py:101-120` |
| Text splice on raw source | Symbol-library append and remove; library-table append | `kcaa/utils/symbol_library_utils.py:327-374`, `462-542`; `kcaa/utils/sym_lib_table_utils.py:71-135` |
| KiCad IPC (`kicad-python` / `kipy`) | PCB save, PCB revert (reload), zone refill, "Update PCB from Schematic" action, open DRC dialog, ping | `kcaa/tools/kipy_tools.py`, `kcaa/utils/kipy_reload.py`, `kcaa/tools/pcb_zone_tools.py` (`refill_zones`), `kcaa/tools/pcb_edit_tools.py` (`update_pcb_from_schematic`), `kcaa/utils/ipc_drc.py` |
| `pcbnew` SWIG (plugin process only) | Read active board path for context, `pcbnew.Refresh()`, board path for auto-save | `kicad_plugin/context_bridge.py:47-90`; `kicad_plugin/ui/panel.py` (`_auto_save_pcb_on_open`, `_auto_refresh`) |
| `kicad-cli` | ERC (JSON), BOM export, thumbnails | `kcaa/tools/erc_tools.py:69-130`; `kcaa/tools/bom_tools.py:677-723`; `kcaa/tools/export_tools.py:127-181` |

The server never imports `pcbnew` (grep of `kcaa/` finds none). The plugin does.

### Which edits go where

- **Every design edit is a direct file edit.** No tool edits a board or schematic through IPC item APIs. Grep finds no `create_items`, `update_items`, or `begin_commit` in `kcaa/`.
- **IPC is used only to sync the GUI with disk** and to fire GUI actions:
  - Before the first mutation of a turn, the plugin calls `save_document` so the PCB editor flushes unsaved GUI edits to disk (`kicad_plugin/llm_client.py` `_execute_tool_with_policy`, about lines 2995-3060).
  - After the turn, it calls `reload_kicad`, which runs `Board.revert()` over IPC (`kcaa/utils/kipy_reload.py:49-86`).
  - `refill_zones` runs revert → refill → save over IPC (`kcaa/tools/pcb_zone_tools.py`, end of file). So "copper zones via KiCad IPC" means: zone geometry is written by file edit; only the fill is computed by KiCad.
  - `run_drc_check` runs the action `pcbnew.DRCTool.runDRC`, which opens the DRC dialog. It returns `{"success": True}` with no violations (`kcaa/utils/ipc_drc.py:12-49`).
  - `update_pcb_from_schematic` runs a GUI action that opens a modal dialog. A socket timeout counts as success (`pcb_edit_tools.py`, `update_pcb_from_schematic` docstring and handler).

### Schematic edits under KiCad 10 IPC limits

- KiCad 10 IPC has no schematic save or revert that this code can use. `save_document` refuses `.kicad_sch` with a message (`kcaa/tools/kipy_tools.py:202-210`). `try_reload_schematic_in_kicad` uses `Schematic.revert()` and says "KiCad 11+" (`kcaa/utils/kipy_reload.py:89-139`).
- So schematic edits are blind file writes with `kicad-skip`. The plugin then tells the user: "Schematic updated on disk — use File → Revert in the Schematic Editor" (`kicad_plugin/ui/panel.py`, `_auto_refresh`).
- Consequence (inference): unsaved schematic edits in eeschema are not flushed before the snapshot. The pre-mutation `save_document` call fails for `.kicad_sch`, the failure is logged as a warning, and the turn continues (`llm_client.py` `_execute_tool_with_policy`). If the user then saves in eeschema, the agent's file edit is lost. If the user reverts, the user's own unsaved edits are lost. Nothing detects this.

### Parse model, preservation, and limits

- **Three parsers / writers:** `kicad-skip` (schematic), `sexpdata` (PCB, tables, libraries, `.kicad_dru`), and hand-written span scanners (library remove). `sexpdata` is not a direct dependency; it arrives through `kicad-skip` (`pyproject.toml` lists only `kicad-skip`).
- **Byte preservation:** none for schematic and PCB. Both rewrite the whole file. The PCB writer comments that it uses "same technique used by skip's writeTree" (`pcb_sexp_utils.py:77-87`). The only PCB round-trip test checks footprint count, not bytes (`tests/unit/tools/test_pcb_utils.py:76-84`). Library remove is byte-identical outside the removed node (`symbol_library_utils.py:525-536`). Library append inserts a `sexpdata.dumps` single-line node, not KiCad formatting (`symbol_library_utils.py:359-369`).
- **Atomic write:** yes. Temp file plus `os.replace` in every writer read.
- **Backup:** `<file>.bak` copied before every write, one level, overwritten by the next call (`docs/plugin/mutation_safety.md` §2; `schematic_sexp_utils.py:23-27`).
- **Conflict detection:** none. "Last write wins" (`docs/plugin/mutation_safety.md` §8). No fingerprint, no peer-lock read (grep for `lck`, `lock_file` finds nothing in `kcaa/`).
- **Project-root guard:** `docs/plugin/architecture.md` §7 says mutations are checked to stay inside the project. In code, `PathValidator` is used only by `secure_subprocess.py` for `kicad-cli` calls. No edit tool imports it. Treat the architecture claim as not true for edits.
- **Hierarchy:** tools take one `schematic_path` and edit that one file. Sheet CRUD exists and can create a child file (`kcaa/tools/sheet_tools.py:254`). The netlist tool treats sub-sheets as opaque components with sheet pins (`kcaa/utils/netlist_parser.py:387-388`; `docs/plugin/tool_contract.md` §3.1). There is no hierarchy-wide document object. The context bridge derives only the root same-stem `.kicad_sch` from the board path (`kicad_plugin/context_bridge.py:70-88`).
- **Library tables and `${VAR}`:** reads project and global `sym-lib-table`/`fp-lib-table`, follows nested `Table` entries with a cycle guard (`symbol_library_utils.py:140-167`). `${VAR}` values come from process environment variables that start with `KICAD` plus `KIPRJMOD` (`symbol_library_utils.py:68-88`). `kicad_common.json` is not read (grep finds no reference). User-defined path variables therefore resolve only when KiCad exports them to the plugin environment (README claim that KiCad provides them; not verified).
- **Netlist / connectivity:** own geometric netlist per sheet file: pins, wires, junctions, labels, power symbols, then union-find (`netlist_parser.py:658-850`). Not `kicad-cli` netlist. Sub-sheet nets are not traced across the hierarchy. ERC does use `kicad-cli` and follows the full hierarchy (`erc_tools.py:76-79`).
- **Agent metadata in design files:** placement groups are stored as a `placement_group` property on placed symbols and footprints (README "Schematic Groups"; `tests/unit/tools/test_pcb_utils.py:194-199` mentions the hidden-marker channel). The agent writes its own state into the user's design.

## API / tool surface

Two profiles, chosen by `KICAD_MCP_PROFILE` (`kcaa/server.py:1-15`, `117-249`):

- `plugin`: editing, query, IPC, ERC/DRC, skills, versions. No MCP resources or prompts.
- `full` (default, standalone): all of the above plus resources, prompts, BOM, export, pattern analysis, project listing.

Main tool groups (full list in `README.md` "Available Tools"):

| Group | Examples | Granularity |
| --- | --- | --- |
| Project | `list_projects`, `get_project_structure`, `open_project` | one-job |
| Symbol index | `sync_symbol_index`, `search_library_symbols`, `get_library_symbol_pins` | one-job; SQLite index in KiCad config dir |
| Symbol libraries | `create_symbol_library`, `create_symbol`, `add_symbols_to_library`, `remove_symbols_from_library`, `delete_symbol_library` | composite: file + table + index in one call |
| Schematic edit | `add_symbol_to_schematic`, `set_symbol_property` (batch `items`), `move_component`, `connect_pins_with_wire`, labels, no-connects | open → edit → save per call; some batch with partial apply |
| Schematic groups | `assign_symbols_to_group`, `place_symbol_group`, `rotate_symbol_group` | composite layout ops |
| Sheets | `add_sheet_symbol`, `update_sheet_symbol`, `add_sheet_pin` | one-job, may create a child file |
| Netlist / analysis | `extract_schematic_netlist`, `find_component_connections`, `run_erc` | read; ERC via `kicad-cli` |
| PCB query / edit / placement / groups / zones / routing | `list_footprints`, `set_footprint_position`, `align_footprints`, `add_zone`, `pcb_route_pad_to_pad`, `pcb_add_vias` | file edit per call; router has `dry_run` |
| DRC and rules | `run_drc_check` (opens dialog), `set_net_class_rules`, `add_custom_rule` | rules edit `.kicad_pro` / `.kicad_dru` |
| Versioning | `save_project_version`, `list_project_versions`, `restore_project_version` | tar.gz checkpoint |
| IPC | `check_kicad_ipc_connection`, `save_document`, `reload_kicad`, `refill_zones`, `update_pcb_from_schematic` | GUI sync and actions |
| Skills | `list_skills`, `get_skill`, `add_skill`, `append_to_skill`, `delete_skill` | Markdown files under `KCAA_SKILLS_DIR` |

Naming rule worth noting: a `library_` prefix means a library definition; no prefix means a placed object (`README.md` "Available Tools"; `docs/plugin/tool_contract.md` "Naming conventions").

## Agent and tooling glue

### Prompt and skill side versus code side

| Prompt / skill side | Code side |
| --- | --- |
| System prompt: "modest, cautious", "share your plan", "never call `save_project_version`, `reload_kicad` … unless asked", "the framework handles snapshots/reloads" (`kicad_plugin/llm_client.py:1395-1403`) | `ToolPolicy` registry: per tool `kind`, `path_arg`, `auto_snapshot`, `mark_dirty`, `track_snapshot`, `clear_dirty_paths_arg`, `post_process` (`kicad_plugin/tool_registry.py:9-27`, `TOOL_POLICIES`) |
| Coordinate and grid rules, "never invent coordinates" (`llm_client.py`, `_PROMPT_SCHEMATIC`, `_PROMPT_PCB`) | Tool calls with no policy entry are rejected (`_TOOL_LOADING_PROMPT`, `llm_client.py:548-563`; `tests/unit/plugin/test_tool_registry_alignment.py`) |
| 12 skill files with frontmatter `tools:` lists (`kicad_plugin/skills/*.md`, 772 lines) | Skill-to-tool map built from frontmatter (`llm_client.py` `_get_skill_tool_map`) |

### Gates and refusal

- No human approval gate in code. `docs/plugin/architecture.md` §2 mentions "approve/reject controls"; grep of `kicad_plugin/` finds none. README claim / design-doc claim, not in code.
- Refusals that exist are file-integrity style: no overwrite on create (`create_empty_library_file`, `create_symbol`), delete only empty libraries, refuse system libraries, report partial state on library delete (`docs/plugin/tool_contract.md` §3.3).
- No ERC/DRC gate on any write. DRC returns no evidence.

### Evidence shape

- JSON dicts. Usual keys `success`, `error`, `message`, plus `backup_path`, `file_modified`, per-item `results`, `applied_count`, `failure_count` (`docs/plugin/tool_contract.md` §6; `pcb_edit_tools.py` `set_footprint_property`).
- Inconsistent failure shape: some tools return `{"error": …}` with no `success` key (`tool_contract.md`, `create_symbol` section says so).
- False positives exist. `reload_kicad` reports a `.kicad_pcb` as reloaded because `try_reload_pcb_in_kicad` swallows every exception (`kipy_reload.py:85-86` with `kipy_tools.py:300-306`). `run_drc_check` and `update_pcb_from_schematic` report dispatch, not outcome.

### Session state

- In-app: conversation, tool log, and enabled tool set persist per project as JSON (`kicad_plugin/session_store.py`, schema v3).
- Per turn: `_ToolExecutionState` holds `snapshotted_paths` and `dirty_paths` (`llm_client.py` about line 1683).
- Server (plugin profile): stateless. Streamable HTTP runs with `stateless_http=True` and `json_response=True` (`kcaa/server.py:322-329`). Every tool call opens, edits, and saves files. No server-held document state.

### Versioning, snapshots, rollback

Three layers, all separate from KiCad's own `.history` (`docs/develop_backlog.md:259-296` says ".history stays independent"):

1. `<file>.bak` before every write. One level.
2. Project checkpoint: `save_project_version` writes `<dir>/.versions/project/<stem>.project.<timestamp>.tar.gz` with a `.manifest.json` of SHA-256 hashes. Dedup: if hashes equal the latest archive, no new archive. Keep last 10 by default (`kcaa/utils/version_manager.py:122-165`).
3. Restore: archives the current state first (undoable), then extracts over the project files (`version_manager.py:197-250`).

Plugin automation ("framework"):

- For a tool with `auto_snapshot=True`, on the first mutation per project per turn: IPC `save_document` → `save_project_version` → the tool (`llm_client.py` `_execute_tool_with_policy`). A failed snapshot aborts the tool call.
- At turn end: `reload_kicad` on all `dirty_paths` (`llm_client.py` `_auto_reload_modified_files`, about lines 3423-3440).

Limits found in code:

- **File set is root-only.** `project_file_set` takes only the same-stem `.kicad_pro`, root `.kicad_sch`, and `.kicad_pcb` (`version_manager.py:33-49`). Sub-sheets, `.kicad_dru`, project library tables, and project-local libraries are not archived. `add_custom_rule` has `auto_snapshot=True` (`tool_registry.py`) but writes `.kicad_dru`, which the snapshot does not hold. Restore of a hierarchical project restores only the root sheet.
- **Restore is not atomic and not exact.** It writes each member with `open(target, "wb")` in place (`version_manager.py:237-241`). Files created after the checkpoint (for example a new child sheet) stay.
- **Standalone mode has none of the framework.** No auto-snapshot, no auto-reload. The tools still write `.bak`. The agent must call `save_project_version` itself.
- **Auto-save on panel open.** The plugin saves the open board through IPC when the panel opens, to clear a dirty flag that KiCad sets (`panel.py` `_auto_save_pcb_on_open`). That also writes any real unsaved user edits, without asking.

### Context compaction

All in `kicad_plugin/llm_client.py`:

- **On-demand tool schemas.** The full catalog is about 46K tokens. The client exposes three meta-tools (`enable_tool`, `disable_tool`, `get_tool_schema`) and sends only loaded schemas (`llm_client.py:533-563`).
- **Budget check, not every turn.** Under `llm_compact_threshold` (default 0.70 of `llm_context_tokens`, default 128000) history stays append-only, to keep the provider prefix cache valid (`_maybe_compact`, `llm_client.py:2630-2695`). Token count is `len(json)/4`.
- **Eviction first.** Over budget, enabled tool schemas are evicted before any history change (`llm_client.py:2697-2720`, issue #133).
- **Then compaction.** Drop tool turns whose tool names all reappear later (`_dedup_tool_calls`, `llm_client.py:2004-2033`). Then summarize the oldest prefix with the same LLM, in chunks no larger than half the window, map-reduce, with an 800-character floor, keeping the pending user question verbatim (`_compact_history`, `llm_client.py:2035-2313`). Target 0.49 of the window.
- **Rollback-aware pruning, always on.** After `restore_project_version`, tool turns between the save point and the restore are deleted from history, because they describe stale files (`_prune_rollback_history`, `llm_client.py:2317-2360`, called first in `_maybe_compact`).
- **History repair.** Orphaned tool calls are stripped after compaction (`_validate_history`, `llm_client.py:2537-2628`).

### In-app versus standalone

| Concern | In-app (`plugin` profile) | Standalone (`full` profile) |
| --- | --- | --- |
| Transport | Streamable HTTP on loopback, stateless, plain JSON | stdio default, or HTTP/SSE (`server.py:307-320`) |
| LLM loop | Plugin's own client (OpenAI, Anthropic, Ollama, Bedrock) | Host's (Claude Desktop, Cursor) |
| Context paths | Injected from `pcbnew` (`context_bridge.py`) | Agent passes paths; `KICAD_SEARCH_PATHS` for discovery |
| Snapshot, reload, dirty tracking | Plugin framework | None; agent must call tools |
| Tool loading / compaction | Plugin meta-tools and compaction | Host's problem |
| Extra surface | — | MCP resources, prompts, BOM, export, patterns |

## Comparison matrix

| Axis | KiCad-AI-Assistant | This package (locked ADRs) |
| --- | --- | --- |
| Product shape | KiCad action plugin with own LLM loop + MCP server | Installable library of KiCad capabilities |
| Design home | Live KiCad session plus files on disk | KiCad files plus project and library context |
| Write model | Save on every tool call; whole-file rewrite for schematic and PCB; text splice for libraries | Buffered edits; source-preserving localized write (ADR 0003) |
| Lifecycle | Per-call open → edit → `.bak` → atomic save; GUI revert at turn end | Open, read, modify, validate, write, close; revert; discard (ADR 0008, 0011) |
| Executive vs primitives | Server tools mostly one-job; executive is the plugin "framework" (save GUI → snapshot → edit → reload) | Primitives only; client or recipe owns sequence (ADR 0009) |
| Hierarchy | One sheet file per call; no hierarchy document; snapshot misses sub-sheets | `Schematic` is the set of sheet trees (ADR 0011) |
| Library tables / `${VAR}` | Nested tables; `${VAR}` from process env only | First-class area; `${VAR}` from KiCad config (ADR 0002; EagleLib2KiCad donor) |
| Connectivity | Own per-sheet geometric union-find; ERC via `kicad-cli` | Client before/after `project.netlist()` compare (ADR 0009) |
| Reuse across apps | One plugin and one server; no library API | One package, many consumers after 1.0 |
| Agent host concerns | Inside the plugin: LLM providers, compaction, sessions, skills, updater | Out of package; host or MCP server owns them (ADR 0012, proposed) |
| License | MIT | MIT |

## Pressure on our decisions

### Claims that hold

| Claim | Why KiCad-AI-Assistant does not overturn it |
| --- | --- |
| ADR 0003 one source-preserving parser | It runs three writers (skip, sexpdata, span splice). Only the span splice keeps bytes. Schematic and PCB writes reformat the whole file, and no test checks bytes. It also had to patch `builtins.open` for skip on Windows (`kcaa/utils/skip_compat.py`). This is the multi-parser drift ADR 0003 exists to stop. |
| ADR 0009 primitives, not an executive | Its own server stays near one-job tools. The policy (flush GUI, snapshot, reload) lives in the plugin client's `ToolPolicy` registry, which is the layering we chose. Standalone mode loses that policy entirely, which shows policy is client-owned and must be rebuilt per host. |
| ADR 0008 / 0009 no silent overwrite | It has no conflict check ("last write wins", `mutation_safety.md` §8) and it silently reverts the GUI board after writes. Our fingerprint and `overwrite=True` rule addresses the exact failure its users can hit. |
| ADR 0011 D6 revert invalidates handles | It needed `_prune_rollback_history` because a restore makes earlier tool results stale. Same idea as our "handles become invalid after revert", at the conversation layer. |
| ADR 0011 D7 backup has no built-in policy | Its keep-10 and per-turn cadence are host choices made in the plugin. That fits our split: `project.backup()` with explicit arguments, cadence in the client. |
| ADR 0007 one private `kicad-cli` discovery | It has three discovery paths: a hard-coded macOS path in `bom_tools.py:677`, another in `export_tools.py:127-150`, and a manager in `kcaa/utils/kicad_cli.py`. Confirms the need for one private rule. |
| Peer lock is a query | It reads no lock at all. Nothing in its experience argues for a lock inside `save()`. |

### Claims worth attacking

| Pressure | Possible crack | What would change if the crack is real |
| --- | --- | --- |
| ADR 0012 rule 3: "Mutations stay buffered … save … remain explicit tools. No save-on-mutate." | Its server runs stateless per call (`server.py:322-329`) and saves per tool. That is what makes a GUI reload after each turn simple. Buffered MCP mutations need server-held open artifacts, session identity, handle lifetime, and an agent that remembers to save. | ADR 0012 wording must name the session model: a stateful server that holds open artifacts per session, or an explicitly named per-call "open, edit, save" composite tool. Escalates ADR 0012 open question 6. Follow-up: ADR 0012 wording, then grill. |
| Non-goal: a live in-UI executive; "only the client knows" if KiCad holds unsaved edits (ADR 0009 primitive test) | Under KiCad 10 nobody knows for schematics. IPC can flush and revert a board, but not a schematic. A file writer beside a running eeschema can clobber, or be clobbered by, the user's unsaved edits. The plugin's answer (flush PCB, write, revert GUI, tell user to File → Revert) still loses data in one direction. | Package stays query-only on locks. ADR 0012 must state a coexistence rule for servers: check `is_locked`, refuse or warn when the document is open in KiCad, never trigger a GUI revert silently. Usage pages may need a "KiCad is open" warning. Follow-up: grill. |
| ADR 0011 D7 backup "archives the project files" | Its checkpoint uses a root-only file set and misses sub-sheets, `.kicad_dru`, and project tables, and even its own tool writes `.kicad_dru` under a snapshot that does not hold it. D7 does not list the file set; D8 does (for save-as). | Confirm `project.backup()` uses the same set as D8 save-as (all project-local files). Follow-up: ticket. |
| ADR 0012 rule 6: structured evidence for gate-like tools | Its DRC tool and "Update PCB" tool report success when a GUI dialog opens. `reload_kicad` reports success after a swallowed failure. Any engine work routed through GUI actions returns no verdict. | Add wording: dispatch-only tools must say "dispatched", never a verdict; gate tools must run headless (`kicad-cli`) or return parsed results. Follow-up: ADR 0012 wording. |
| Git `.history` interop deferred (#58–#60) | It chose not to touch KiCad's `.history` and built a third history (`.bak`, `.versions/`, KiCad `.history`). Agents get a cheap checkpoint without Git. Users get three mechanisms that do not know each other. | Input for #59 grilling: weigh the "agent checkpoint" case. A ZIP from `project.backup()` may cover it without `.history` interop, or the triple-history confusion may argue for interop. Follow-up: grill (#59). |
| KiCad IPC is out of default scope (AGENTS, ADR 0006) | The only reliable GUI sync for boards in this project is IPC. A future MCP that lives beside a running KiCad will want `kipy` for flush and revert. | Keep IPC out of `kicad_primitives`. ADR 0012 §4 should list IPC beside `pcbnew` as server-only, purpose-limited. Follow-up: ADR 0012 wording. |

## Steal list (apply outside or beside the package)

1. **Tool policy as data** (`kicad_plugin/tool_registry.py`): each tool declares kind, path argument, snapshot, dirty marks. A registry-coverage test refuses unknown tools. Layer: MCP server or host client.
2. **Snapshot once per project per turn, with hash dedup** (`version_manager.py:122-165`; `llm_client.py` `_execute_tool_with_policy`). Layer: server or recipe over `project.backup()`, with the D8 file set.
3. **Rollback-aware context pruning** (`_prune_rollback_history`). Layer: host client.
4. **Eviction-first context budget and on-demand tool schemas** (`_maybe_compact`, meta-tools). Layer: host client; relevant once a tool catalog passes about 100 tools.
5. **`library_` prefix naming rule** for definition versus placement. Layer: ADR 0012 tool naming.
6. **Batch responses with per-item results and counts** (`set_symbol_property`, `set_footprint_property`). Layer: MCP envelope over per-object primitives.
7. **Partial-state failure reports** that say exactly what was removed and what was left (`delete_symbol_library`). Layer: MCP envelope; our primitives already avoid partial state.
8. **`find_symbols_not_in_libraries`** read-only pre-flight. Layer: consumer or recipe (kDoctor-shaped).
9. **KiCad IPC socket discovery** (`KICAD_API_SOCKET`, newest `api*.sock`, Flatpak path; `kipy_tools.py:25-57`). Layer: private server helper, only if IPC is ever used.
10. **Skill files with frontmatter tool lists** (`kicad_plugin/skills/*.md`). Layer: host skill.

## Reject list (do not pull into this package)

1. `kicad-skip` or `sexpdata` whole-file re-serialize as a write core.
2. Save on every operation with a single-level `.bak` as the persistence model.
3. Silent GUI revert after file writes, and auto-save of the user's board on panel open.
4. Dispatch-only GUI actions reported as success.
5. A root-only project file set for backup or restore; non-atomic in-place restore.
6. Per-sheet geometric netlist as connectivity truth.
7. `${VAR}` resolution from process environment only.
8. Agent placement state (`placement_group`) written into design files by the library.
9. LLM provider adapters, compaction, session store, or updater in any library layer.

## Overlap with our donors

| Donor | Overlapping job in KiCad-AI-Assistant | Evidence |
| --- | --- | --- |
| jBOM | BOM analysis and CSV export via `kicad-cli`; symbol and footprint indexing | `kcaa/tools/bom_tools.py`; `kcaa/utils/symbol_index_manager.py`, `footprint_index_manager.py` |
| kproj | `kicad-cli` locator and export facade (thumbnails, BOM) | `kcaa/utils/kicad_cli.py`; `kcaa/tools/export_tools.py` |
| kDoctor | ERC JSON interpretation; footprint read model; nested library tables; missing-library discovery | `kcaa/tools/erc_tools.py`; `kcaa/tools/pcb_library_tools.py`; `symbol_library_utils.py:140-167`; `find_*_not_in_libraries` |
| EagleLib2KiCad | Library creation and table registration with `${VAR}` URIs | `create_symbol_library`, `create_footprint_library`; `kcaa/utils/sym_lib_table_utils.py`, `fp_lib_table_utils.py` |
| FieldUnit-Subdivision | Schematic netlist reader; span-based library text edits; symbol model with units | `kcaa/utils/netlist_parser.py`; `symbol_library_utils.py:385-542`; `kcaa/utils/symbol_geometry.py` |

## Sources read

| Path | Use |
| --- | --- |
| `README.md`, `pyproject.toml`, `LICENSE`, git log/shortlog/tags | Product shape, deps, license, activity |
| `docs/plugin/architecture.md`, `mutation_safety.md`, `tool_contract.md` | Design intent, backup and error contract |
| `docs/plugin/pcb_feasibility.md`, `docs/skip_library_notes.md` (first 80 lines), `docs/develop_backlog.md:183-382` | skip limits, PCB plan, versioning decision |
| `kcaa/server.py` | Profiles, transport, stateless mode |
| `kcaa/utils/version_manager.py`, `kcaa/tools/version_tools.py` | Snapshot and restore |
| `kcaa/tools/kipy_tools.py`, `kcaa/utils/kipy_reload.py`, `kcaa/utils/ipc_drc.py` | IPC use and KiCad 10 limits |
| `kcaa/utils/schematic_sexp_utils.py`, `pcb_sexp_utils.py`, `skip_compat.py` | Write model |
| `kcaa/utils/symbol_library_utils.py` (39-182, 252-542), `sym_lib_table_utils.py:71-135` | Tables, `${VAR}`, library text edits |
| `kcaa/tools/pcb_zone_tools.py` (380-491), `pcb_edit_tools.py` (400-517), `erc_tools.py` (60-130), `pcb_design_rules.py` (95-125) | Zone, update-from-schematic, ERC, rules writes |
| `kicad_plugin/tool_registry.py` (1-60, 190-215, 380-482), `context_bridge.py`, `session_store.py` (header) | Policy registry, context, sessions |
| `kicad_plugin/llm_client.py` (505-570, 1395-1470, 1680-1700, 2000-2360, 2576-2775, 2995-3100, 3400-3445) | Prompt, meta-tools, compaction, snapshot and reload orchestration |
| `kicad_plugin/ui/panel.py` (860-910, 1980-2060) | Auto-save on open, refresh messages |
| `tests/unit/tools/test_pcb_utils.py` (1-200) | What round-trip tests check |

Skimmed only (grep or headers): `kcaa/utils/netlist_parser.py` (function index and docstrings), `kcaa/tools/sheet_tools.py` (tool list, child file write), `kcaa/utils/config.py` (`get_env_vars`), `kcaa/utils/path_validator.py` and its callers, `kicad_plugin/skills/schematic_wiring.md` and skill sizes.

Not read: `kcaa/router/` (about 12K lines), `symbol_edit_tools.py` and `wire_edit_tools.py` bodies, `render_board_tools.py`, `kicad_plugin/updater.py`, `docs/skill-system-design.md`, `docs/sheet-crud-plan.md`, Chinese README.

## Confidence and gaps

- **No code was run.** All behavior claims come from reading code. I did not verify that KiCad 10 loads files written by skip or sexpdata.
- **skip write fidelity is inferred.** The skip package is not in the clone. The claim "whole-tree rewrite" rests on `schematic_sexp_utils.py` calling `sch.write` and on the comment in `pcb_sexp_utils.py:80-82`. Medium confidence.
- **KiCad 10 IPC schematic limits** come from this repo's docstrings and error strings (`kipy_tools.py:202-210`, `kipy_reload.py:92-94`). I did not check the KiCad or `kicad-python` sources.
- **Approve/reject UI**: described in `docs/plugin/architecture.md` §2; not found by grep in `kicad_plugin/`. It may exist under another name in `panel.py` (4323 lines, read in part).
- **`selected_refs` and `active_sheet` context fields** are in `tool_contract.md` §5; `collect_context` as read sets only board-derived fields. They may be set elsewhere.
- **macOS behavior** of IPC socket discovery and plugin paths is not verified; README states Linux and Windows testing only.
- **Compaction quality** (what the summaries keep) was not evaluated; only the mechanism was read.
- **Our side**: I did not check how `project.backup()` builds its file set in `src/`; the ticket suggestion rests on ADR 0011 D7 text only.
