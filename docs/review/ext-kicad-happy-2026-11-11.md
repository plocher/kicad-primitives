# kicad-happy review (2026-11-11)

Status: research input for Structured-B synthesis. Not an ADR.

Subject: [kicad-happy](https://github.com/aklofas/kicad-happy) (local clone `~/Dropbox/workspace/kicad-happy`, HEAD `7d9d4d9f`, tag `v3.0.1`), compared with this package's ADRs and proposed ADR 0012.

Brief: `docs/review/external-survey-brief-2026-11-11.md`. Exemplar: `docs/review/hitl-comparison-2026-11-10.md`.

All external paths below are relative to the kicad-happy clone root.

## What it is

kicad-happy is a **skill pack** with a large deterministic Python analysis engine behind it. It is not an MCP server and not a KiCad plugin.

| Field | Value | Evidence |
| --- | --- | --- |
| Product shape | 11 agent skills (`kicad`, `spice`, `emc`, `datasheets`, `bom`, `digikey`, `mouser`, `lcsc`, `element14`, `jlcpcb`, `pcbway`), CLI scripts, and a composite GitHub Action | `skills/*/SKILL.md`, `action.yml`, `README.md:228-242` |
| Hosts | Claude Code plugin, Codex, Antigravity/Gemini, opencode, Cursor rules | `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `.opencode/opencode.json`, `.cursor/rules`, `GEMINI.md` |
| Language | Python 3.10+, stdlib only for the core; optional `requests`, `playwright`, `pdftotext`, ngspice/LTspice/Xyce | `ARCHITECTURE.md:18-20`, `README.md:195`, `README.md:427` |
| Size | About 122k lines under `skills/` (tests excluded); 241 test modules in `tools/tests` | `wc -l` over `skills/` |
| License | MIT (Andrew Klofas, 2025) | `LICENSE` |
| KiCad target | Reads KiCad 5 to 10. KiCad 10 features handled: `top_level_sheets`, design variants, `(hide yes)` | `README.md:429-438`, `skills/kicad/scripts/kicad_core/project.py:217-278` |
| Activity | 1670 commits from 2026-03-08 to 2026-11-06; v3.0.1 current | `git log` |
| Maturity signals | Frozen 3.x contracts (input formats, rule IDs, CLI flags, exit codes); output changes need a declared budget; CI-enforced import layering; external corpus harness of about 5,800 projects (README claim, not verified in code) | `ARCHITECTURE.md:5-23`, `how-it-works.md:211-245` |

## How it touches KiCad

**Own parser, read model only.** `skills/kicad/scripts/kicad_core/sexp.py` is a hand-written tokenizer and recursive parser. It returns nested Python lists of strings. It decodes KiCad brace escapes and C escapes, and keeps the raw text of escaped tokens for net names (`sexp.py:15-49`, `sexp.py:112-140`). It drops comments, whitespace, and token positions. It cannot write. No `sexpdata`, `kiutils`, or KiCad library is imported (grep over `skills/`).

**No KiCad runtime.** No code calls `kicad-cli`, imports `pcbnew`, or uses KiCad IPC (grep for `kicad-cli`, `pcbnew`, `kipy`, `subprocess` over `skills/`, `tools/`, `action/`). `kicad-cli` appears only in comments, in docs, and as a **recorded oracle** in tests: expected values are pasted from `kicad-cli 10.0.6` netlists (`tools/tests/test_net_driver_priority.py:1-27`, `tools/tests/test_top_level_sheets_kicad10.py:7`). README claim: "No KiCad installation needed" (`README.md:195`); the code matches this.

**Connectivity is re-implemented.** The schematic net map is a union-find over pin, wire, and label coordinates in KiCad internal units. Points join only at exact coordinates; near misses go to `diagnostics` (`how-it-works.md:29`, `skills/kicad/scripts/kicad_core/coords.py` per `ARCHITECTURE.md:152`). Bus vectors, groups, and aliases are ports of KiCad C++ (`skills/kicad/scripts/schematic/connectivity.py:1-80`). PCB copper connectivity is a union-find over pads, tracks, vias, and zone fills (`skills/kicad/scripts/pcb/connectivity.py`, `ARCHITECTURE.md:187`).

**ERC is re-implemented, not interpreted.** `skills/kicad/scripts/schematic/erc_pins.py:1-40` ports KiCad 10's default pin-conflict map and driver sets from `eeschema/erc/*.cpp`. DRC is approximated by DFM measurements plus `.kicad_dru` and `rule_severities` reads (`skills/kicad/scripts/pcb/dfm.py`, `kicad_core/project.py:643-648`, `737-817`). Nothing reads a KiCad ERC or DRC report.

**Hierarchy is strong.** Multi-instance sheets with per-instance reference remap, multi-root `top_level_sheets`, `${VAR}` in sheet file names, KiCad 10 variants, legacy `symbol_instances` (`skills/kicad/scripts/schematic/hierarchy.py:1-40`, `kicad_core/project.py:240-311`, `kicad_core/instances.py` per `ARCHITECTURE.md:155`).

**Library tables are thin.** `load_lib_tables` reads only the project-local `sym-lib-table` and `fp-lib-table` and returns raw URIs. No global tables, no nested tables, no `${VAR}` or `kicad_common.json` resolution (`kicad_core/project.py:820-852`). The legacy reader expands `${KIPRJMOD}` only (`schematic/legacy_reader.py:409-436`). No code opens standalone `.kicad_sym` or `.kicad_mod` files; analysis uses the symbols embedded in `lib_symbols` and the footprints embedded in the board (grep for `kicad_sym`, `.pretty`).

**Two write paths, both schematic properties.**

| Script | Job | Mechanism |
| --- | --- | --- |
| `skills/bom/scripts/edit_properties.py` | Set or add properties on placed symbols, keyed by reference | Regex plus paren matching finds placed-symbol spans (`skills/bom/scripts/kicad_sexp.py:25-81`); value replaced in place; new property inserted after the last property with detected indent and version-aware `hide` form (`edit_properties.py:83-174`) |
| `skills/bom/scripts/sync_datasheet_urls.py` | Write `Datasheet` URLs from `datasheets/manifest.json` | Same helpers (`ARCHITECTURE.md:131`) |

Write safeguards: atomic temp-and-replace (`kicad_core/fileio.py:12-81`); `--dry-run` with a JSON change log (`edit_properties.py:274-283`, `414-419`); opt-in timestamped `.bak` (`edit_properties.py:425-430`); a lock-file **warning** that does not block the write (`edit_properties.py:360-370`); equal value is an exact no-op (`edit_properties.py:240-247`).

Limits of the write path (fact, then inference):

- Fact: the file is read with universal newlines and written with `newline="\n"` (`edit_properties.py:386`, `fileio.py:12`). Inference: a CRLF file is rewritten with LF on every line, so untouched bytes change.
- Fact: symbols are matched by the text of `(property "Reference" ...)` in the symbol block, and every block with that reference is updated (`edit_properties.py:61-76`, `218-224`). Inference: in a KiCad 10 multi-instance sheet, per-instance references live in `(instances ...)`, so a reference such as `R12` on a second instance may not be found, or one edit may hit all instances.
- Fact: I found no byte-identity round-trip test for the write path (grep for `byte|identical|unchanged` in `tools/tests/test_bom_*.py`, `test_writer_file_version.py`, `test_sync_datasheet_urls.py`). Tests cover spans, escapes, version-aware hide, and write roots (`tools/tests/test_bom_spans.py`, `test_bom_write_roots.py`).

No PCB, symbol-library, footprint-library, or table writes exist.

## API / tool surface

The agent surface is **skill text plus CLI scripts that emit JSON**. There is no tool schema registry; each CLI has `--schema` that prints a JSON Schema (`skills/kicad/SKILL.md:107-116`, `skills/kicad/scripts/schema_codec.py` per `ARCHITECTURE.md:88`).

| Command | Job | Granularity |
| --- | --- | --- |
| `analyze_schematic.py` | Parse hierarchy, build nets, run 60+ detectors, emit envelope (60–220 KB) | Composite analysis pipeline; opt-in `--lifecycle` adds network calls |
| `analyze_pcb.py [--full] [--schematic]` | Board extraction, copper connectivity, DFM, placement, thermal pads | Composite |
| `analyze_gerbers.py` | Gerber/Excellon reader and completeness checks | Composite |
| `cross_analysis.py` | Schematic-to-PCB checks (XV, CC, EG, DA) over two JSON files | One job over JSON |
| `analyze_thermal.py`, `skills/emc/scripts/analyze_emc.py` | Thermal estimate; 44 EMC rule checks over analyzer JSON | One job over JSON |
| `skills/spice/scripts/simulate_subcircuits.py` | Testbenches for detected subcircuits; runs a simulator | One job over JSON plus external engine |
| `what_if.py` | Patch values **in the analyzer JSON**, recompute derived fields | One job; never touches KiCad files |
| `diff_analysis.py`, `summarize_findings.py` | Compare runs; roll up findings | One job over JSON |
| `fab_release_gate.py` | Pass/warn/fail gate over analyzer JSON; exits 1 on FAIL | Named gate over JSON (`fab_release_gate.py:1-60`, `README.md:442`) |
| `review/scripts/deep_review_gate.py` | Validate LLM `deep_review.json`, quarantine uncited findings | Named gate over JSON |
| `bom_manager.py analyze/export` | BOM gaps, part-number convention, tracking CSV merge | Composite BOM tool |
| `edit_properties.py`, `sync_datasheet_urls.py` | Schematic property write-back | One job, one file |
| `translate_bom_pnp.py` | BOM/CPL to JLCPCB upload format | One job |
| `fetch_datasheet_<p>.py`, `sync_datasheets_<p>.py` | Distributor search and datasheet download (×4) | One job per provider |

GitHub Action mode (`action.yml`, `action/entrypoint.sh`): auto-detect project, sync datasheets when keys exist (non-blocking), run schematic and PCB analyzers, optional SPICE, format a markdown PR comment, set `has-critical` and `findings-count` outputs. No agent runs. An optional second step chains `claude-code-action`, `codex-action`, or opencode to write prose over the same JSON (`github-action.md:52-148`).

Mode comparison:

| Mode | Who sequences | Adds over scripts |
| --- | --- | --- |
| Standalone scripts | User | Nothing; JSON or `--text` |
| GitHub Action | `action/entrypoint.sh` | Fixed sequence, PR comment, status outputs |
| Agent (skill) | Agent under `SKILL.md` contract | Datasheet sync, raw-file spot checks, Deep Review pass, report, write-back on request |

## Agent and tooling glue

**Code owns facts; prompts own procedure.** `how-it-works.md:5-15` states the split: scripts are deterministic extraction; the agent reasons over the JSON.

| Prompt / skill side | Code / gate side |
| --- | --- |
| Design Review Contract: run every applicable analyzer, disclose skipped ones, triage false positives (`skills/kicad/SKILL.md:42-83`) | Analyzer envelopes with `rule_id`, `detector`, `severity`, `confidence`, `evidence_source`, `trust_summary`, `diagnostics` (`SKILL.md:276-301`, `ARCHITECTURE.md:43`) |
| "Always run `spice` / `emc`" as required steps (`SKILL.md:36`, `413-420`) | `LC-007` info finding when lifecycle audit was skipped, so the gap is in data (`SKILL.md:647`) |
| `DS-001` refusal: no "verified" wording without datasheets (`SKILL.md:40`) | `DS-001`/`DS-002`/`DS-003` audit findings emitted by code |
| Deep Review: per-IC datasheet comparison by the LLM (`SKILL.md:671-721`) | `deep_review_gate.py` checks every cited component, net, or pin exists in analyzer JSON; failures go to `quarantined[]` (`skills/kicad/review/README.md:33-49`) |
| Probing etiquette: announce each probe; defensive JSON patterns (`SKILL.md:787-808`) | `--schema` on every analyzer; field cheat sheet (`SKILL.md:118-136`) |
| Fab readiness wording | `fab_release_gate.py` exit codes |

Session state lives on disk: `analysis/<run_id>/` folders with a manifest, SHA-256 staleness, retention, and auto-diff against the prior run (`skills/kicad/scripts/analysis_cache.py` per `ARCHITECTURE.md:79`, `SKILL.md:328-366`). Versioning is the run folder plus git; rollback of KiCad edits is the timestamped `.bak` only. Token control: `--compact`, `--stage`, `--audience`, `summarize_findings.py --top N`, and "read JSON, do not write ad-hoc extractors" (`SKILL.md:103-105`, `308-326`). LLM overlays never mutate detector output; stripping `llm_*` keys recovers the deterministic baseline (`review/README.md:35-40`).

## Comparison matrix

| Axis | kicad-happy | This package (locked ADRs) |
| --- | --- | --- |
| Product shape | Skill pack + CLI analyzers + GitHub Action | Installable library of KiCad capabilities |
| Design home | KiCad files, read into derived JSON | KiCad files plus project and library context |
| Write model | Read-only analysis; two narrow regex-span property writers with atomic replace | Source-preserving localized edit over one lossless representation (ADR 0003) |
| Lifecycle | One-shot CLI run; on-disk run folders | Open, read, modify, validate, write, close (ADR 0008, 0011) |
| Executive vs primitives | Analyzers are composite pipelines; gates are separate named scripts over JSON; core layer is stdlib-only and imports nothing above it | Primitives only; client or recipes own sequence (ADR 0009) |
| Hierarchy | Strong read: multi-instance, multi-root, variants, `${VAR}` sheet names | Core project and schematic model (ADR 0011) |
| Library tables / `${VAR}` | Project-local raw URIs only | First-class area with real resolution (ADR 0002) |
| Connectivity | Pure-Python re-implementation; `kicad-cli` only as recorded test oracle | `project.netlist()` through private `kicad-cli`; client before/after compare |
| Reuse across apps | Skill-internal; `kicad_core` is importable but not packaged for others | One package, many consumers after 1.0 |
| Agent host concerns | In the skill text and run folders; five hosts supported without MCP | Out of package; host or future MCP server (ADR 0012) |
| License | MIT | MIT |

## Pressure on our decisions

### Claims that hold

| Claim | Why kicad-happy does not overturn it |
| --- | --- |
| ADR 0003 one source-preserving representation | kicad-happy needs **two** parsers: a nested-list reader for analysis (`kicad_core/sexp.py`) and a regex span scanner for writes (`skills/bom/scripts/kicad_sexp.py`). The split exists because the read model cannot write. Its writer also loses CRLF bytes. This is the cost ADR 0003 avoids. |
| ADR 0008 artifact lifecycle | kicad-happy edits only one property family, one file per run. It has no multi-file pending state, no discard, no revert. A wider edit surface would need what ADR 0008 defines. |
| ADR 0009 primitives, not an executive | kicad-happy keeps file parsing in a stdlib-only core that imports nothing above it (`ARCHITECTURE.md:18-23`, CI-enforced by `tools/check_refactor.py`). Gates (`fab_release_gate.py`, `deep_review_gate.py`) are separate named scripts over JSON. This matches our layering. |
| ADR 0009 peer lock is a query | kicad-happy warns on `~name.kicad_sch.lck` and still writes (`edit_properties.py:360-370`). Same policy as ours; the warning lives in the client CLI. |
| ADR 0011 `Schematic` is a set of sheet trees | `hierarchy.py` merges declared `top_level_sheets` as separate trees, falls back to `<project>.kicad_sch`, and dedupes by real path (`kicad_core/project.py:240-278`, `378-385`). Independent confirmation of our noun. |
| ADR 0012 domain gates stay out of the library | EMC, SPICE, sourcing, lifecycle, thermal, and fab gates all consume analyzer JSON, never raw files (`ARCHITECTURE.md:104-132`). Optional skills may import the core but never each other (`ARCHITECTURE.md:18-19`). The placement holds. |
| ADR 0012 rule 6 structured evidence | kicad-happy's envelope, `diagnostics`, and quarantine list show the shape works across hosts and CI. |

### Claims worth attacking

| Pressure | Possible crack | What would change if the crack is real |
| --- | --- | --- |
| "Domain gates live outside `kicad_primitives`" (ADR 0012 §4, ADR 0002) | Placement holds, but the gates need a **deep read model**: instance-resolved references, variant overrides, nets with pin electrical types, PCB copper connectivity, zones, net classes, DFM measurements. kicad-happy built about 13k lines of reader, hierarchy, ERC-pin, and connectivity code to get it (`kicad_core/`, `schematic/{reader,legacy_reader,hierarchy,connectivity,erc_pins}.py`, `pcb/{reader,geometry,connectivity}.py`), before any detector. If our package exposes edit nouns but not these read facts, each domain consumer grows its own parser, against "one parser" and "each fact has one source". | Scope check on ADR 0002 Connectivity and PCB areas and the ADR 0006 B list: name which read-only facts the package owns. Follow-up: **grill**. |
| "Connectivity verify uses `kicad-cli` netlist" (ADR 0009, ADR 0011, `src/kicad_primitives/netlist.py:213-290`) | kicad-happy gets KiCad-equal net names and pin sets in pure Python, checked against recorded `kicad-cli 10.0.6` output, with no KiCad install. CI runners and cloud agents often lack KiCad. | Backend is already implementation detail (ADR 0006). A second backend would be a large build and a second source of connectivity truth. Keep `kicad-cli` as reference; record "no-KiCad host" as a known limit. Follow-up: **ticket** (record the limit and the oracle-test pattern). |
| "Future agent surface is an MCP server" (ADR 0012 candidate C) | kicad-happy reaches five agent hosts and a GitHub Action with skill text plus CLIs that emit schema'd JSON (`--schema`). No MCP transport. | ADR 0012 should name MCP as one transport, not the only one. Tool contracts (inputs, envelope, exit codes) stay the same; a skill-plus-CLI shell is a valid sibling. Follow-up: **ADR 0012 wording**. |
| "Edit surfaces are the main 1.0 value" (ADR 0006 A/B) | kicad-happy's agent value is almost all **read and review**. Writes are two property scripts. The dominant agent job may be inspect, not edit. | No change to the edit model. It strengthens the first row: read depth deserves its own line in the 1.0 bar. Follow-up: **grill** (merge with row 1). |
| "Native backup only" (ADR 0008 symbol `.bak`) | kicad-happy writes timestamped `.bak` files beside the schematic for every write-back run. Users get a backup history, but the project folder fills up. | No change. Confirms that backup policy belongs to the client CLI, not the primitive. Follow-up: **none**. |
| "Structured evidence lives at MCP and CI edges" (HITL note, ADR 0012 rule 6) | kicad-happy puts evidence fields (`confidence`, `evidence_source`, `diagnostics`) in its analysis layer, one level above parsing. Our primitives return typed objects but no degradation record. A silent partial read in a primitive (an unparsed node, a near-miss join) would not reach the agent. | Possible need for a typed "degraded read" signal on read primitives, not a report framework. Follow-up: **grill**. |

## Steal list (apply outside or beside the package)

1. **Recorded-oracle tests** — paste `kicad-cli` output into fixture tests so the normal suite needs no KiCad (beside the package, in `tests/`).
2. **`diagnostics` list** in every result envelope — degraded steps are data, not stderr (MCP and recipe layer; a typed hook in primitives is a grill item).
3. **Skipped-step findings** (`LC-007` pattern) — an omitted gate emits an info record so a report cannot hide it (MCP or recipe layer).
4. **Evidence gate with quarantine** — LLM claims must cite IDs that exist in tool output, else quarantine (host skill or MCP server).
5. **`--schema` on every tool** — machine-readable output contract for agents (MCP server or CLI shell).
6. **Dry-run JSON change log** before a write (client CLI or MCP tool over `pending changes` inspection that ADR 0008 already gives).
7. **CI-enforced import layering** with a shrink-only baseline (`tools/check_refactor.py imports`) — protects "primitives never call recipes" (beside the package, dev tooling).
8. **Run folders with manifest and auto-diff** — session memory for agents (MCP server or host skill).
9. **Frozen contract list** for a release line: input formats, IDs, flags, exit codes (release process; fits ADR 0005).
10. **Honest limits section** (`how-it-works.md:93-117`) — states what green does not mean (host skill text).

## Reject list (do not pull into this package)

1. A nested-list parser beside `lossless_sexpr` (violates ADR 0003 "one parser").
2. Regex span writers that normalize line endings.
3. Reference-text keyed edits that ignore sheet-instance paths.
4. Circuit detectors, EMC rules, SPICE, distributor clients, fab tables (`JLCPCB_LIMITS_*`) as library APIs. They belong to domain consumers.
5. Prompt-only "required step" rules as the only gate. Use machine gates beside them.
6. Timestamped backup sprawl as a primitive behavior.
7. A second connectivity engine inside the package without an owner decision.

## Overlap with our donors

| Donor | kicad-happy overlap | Strength |
| --- | --- | --- |
| jBOM | BOM extraction, part-number field aliases (`bom_fields.py`), sourcing gaps, tracking CSV, per-distributor order files, JLCPCB BOM/CPL format | High. Same jobs, separate code. jBOM also has project discovery and variables; kicad-happy has its own (`kicad_core/project.py`) |
| kDoctor | Design review product; ERC semantics; DFM/DRC-like checks | High on review. Different method: kicad-happy re-implements ERC pin rules and never interprets KiCad ERC/DRC reports; kDoctor interprets reports |
| kproj | None. No `kicad-cli` use, no exporters. Gerber **reading** only | None |
| EagleLib2KiCad | Library tables | Low. kicad-happy reads project-local raw URIs only |
| FieldUnit-Subdivision | Localized `.kicad_sch` property edits; connectivity gate | Medium. Both edit spans in place; Subdivision is byte-preserving, kicad-happy loses CRLF. Connectivity: kicad-happy computes nets in Python; Subdivision reads KiCad netlists |

## Sources read

| Path | Use |
| --- | --- |
| `ARCHITECTURE.md` (full) | Module map, layering rules, contracts, write helpers |
| `how-it-works.md` (full) | Parse model, agent split, limits, test layers |
| `README.md` (lines 16–450) | Product claims, install hosts, version table, release notes |
| `skills/kicad/SKILL.md` (lines 1–420, 597–850) | Review contract, analyzer commands, envelope, Deep Review, security notes |
| `skills/kicad/scripts/kicad_core/sexp.py` (full) | Parser model |
| `skills/kicad/scripts/kicad_core/fileio.py` (full) | Atomic write, newline policy |
| `skills/kicad/scripts/kicad_core/project.py` (196–394, 732–852) | Top-level sheets, `${VAR}` sheet names, `.kicad_dru`, lib tables |
| `skills/bom/scripts/edit_properties.py` (full) | Write path |
| `skills/bom/scripts/kicad_sexp.py` (full) | Span scanner, sub-sheet discovery |
| `skills/kicad/review/README.md` (1–49) | Deep Review gate invariants |
| `skills/kicad/scripts/fab_release_gate.py` (1–60) | Gate shape |
| `skills/kicad/scripts/schematic/erc_pins.py` (1–40), `connectivity.py` (1–80), `hierarchy.py` (1–40) | ERC port, bus logic, hierarchy |
| `skills/bom/scripts/bom_manager.py` (1–45) | BOM tool scope |
| `action.yml`, `action/entrypoint.sh` (summarized), `github-action.md` (grep) | Action mode |
| `.github/workflows/ci.yml` (1–60), `.claude-plugin/plugin.json`, `LICENSE` | CI, packaging, license |
| `tools/tests/test_net_driver_priority.py`, `test_top_level_sheets_kicad10.py`, `test_bom_spans.py`, `test_bom_write_roots.py` (heads) | Oracle pattern, write tests |
| This repo: `docs/adr/README.md`, ADR 0012, HITL note, `AGENTS.md`, `src/kicad_primitives/netlist.py` (grep) | Our side |

Skimmed or grep only: `skills/emc/SKILL.md` and `skills/bom/SKILL.md` headings, `VALIDATION.md` headings, `CONTRIBUTING.md` test commands, `skills/*/scripts` write-site grep. Not read: detector modules (`signal_detectors.py`, `domain_detectors.py`), EMC rules, SPICE, datasheet extraction, distributor adapters, PCB reader internals.

## Confidence and gaps

- I did not run any script or test. The claims "no KiCad needed" and "pure stdlib" rest on code grep and `ARCHITECTURE.md`, not on a run.
- Corpus size (about 5,800 projects), 30,000 SPICE runs, and 141,000 EMC findings are README claims, not verified in code. The harness is a separate repo (`kicad-happy-testharness`) that I did not clone.
- The multi-instance reference risk in `edit_properties.py` is inference from code. I did not build a fixture to prove it.
- The CRLF loss is inference from the `newline` arguments. I did not test a CRLF file.
- I did not check how close the Python connectivity is to `kicad-cli` beyond the tests that quote oracle output.
- Stars, issue volume, and contributor count were not checked (no network calls made).
- ADR 0003, 0008, 0009, and 0011 were read through the ADR index and `AGENTS.md` summaries, not in full.
