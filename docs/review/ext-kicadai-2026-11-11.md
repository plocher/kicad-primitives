# External survey: KiCadAI (2026-11-11)

Status: research input for Structured-B synthesis. Not an ADR.

Subject: [dshills/KiCadAI](https://github.com/dshills/KiCadAI) (local clone `~/Dropbox/workspace/KiCadAI`, HEAD `48c178b2`, 2026-11-04). Compared with this package's ADRs and with the [HITL comparison](hitl-comparison-2026-11-10.md).

All external paths below are relative to the KiCadAI clone root. "README claim" marks statements that I did not check in code.

## What it is

KiCadAI is a **generator plus an evidence-and-refusal engine**, shipped as a Go CLI. It is not a reusable library, not an MCP server, and not a KiCad plugin.

| Field | Value | Source |
| --- | --- | --- |
| Shape | CLI binary `kicadai` plus about 35 evaluator/publisher CLIs under `cmd/` | `cmd/`, `SUPPORT.md:56-59` |
| Library? | No. "This repository publishes a CLI, not an importable Go library." All code is under `internal/`. | `SUPPORT.md:56-59` |
| Language | Go 1.26 (pinned patch in `.go-version`); one Rust reference client under `integrations/netform-client` | `go.mod`, `.go-version` |
| License | MIT. Vendored KiCad proto files keep upstream licenses. | `LICENSE`, `third_party/kicad/` |
| KiCad target | KiCad 10.0.3 is the reference for ERC, DRC, round-trip, and promotion claims. KiCad 9 is "experimental". | `SUPPORT.md:31-40` |
| Version | 1.0.1 released; maintained source is ahead of the tag | `VERSION`, `README.md` |
| Activity | 1,851 commits from 2026-06-08 to 2026-11-04, one author, branch names `codex/...` | `git log`, `git shortlog` |
| Size | About 388k lines of non-test Go and 225k lines of test Go under `internal/` and `cmd/` | `wc -l` over `*.go` |
| Maturity signals | CI workflows, checksum-pinned KiCad promotion toolchain, frozen evaluation corpora, a self-review that found unsound certificates and evidence-hash errors in its own V21 evaluator | `.github/workflows/`, `toolchain/kicad-promotion.lock.json`, `docs/project-review-2026-09-06.md` (README claim for the review findings) |

Inference: commit rate and branch names show a heavily agent-authored codebase. Many versioned evaluator packages (`corpusfreezev6`…`v10`, `kicadai-discovery-baseline-v10`…`v23`) are frozen history kept beside live code.

Product claim: "AI proposes. KiCadAI proves—or refuses." The AI boundary accepts behavior only. Deterministic code owns topology, part choice, values, simulation, schematic and PCB generation, placement, routing, validation, and the pass-or-refuse verdict (`README.md`, intro).

## How it touches KiCad

### Parse model

- **Own S-expression parser and renderer** in `internal/kicadfiles/sexpr/` (`parse.go` 241 lines, `sexpr.go` 363 lines). The parser keeps each node's `Raw` source slice (`parse.go:13-20`, `:148`). The renderer emits a canonical KiCad-style layout from a typed node tree and accepts validated `Raw` fragments (`sexpr.go:86-172`).
- Typed read models exist for schematic, PCB, and project files (`internal/kicadfiles/schematic/read.go`, `pcb/read.go`, `project/read.go`). Unmodeled nodes are kept as raw strings in item order and tagged with a `PreservationCapability` of `fully_modeled`, `raw_preserved`, or `unsupported_for_mutation` (`internal/kicadfiles/preservation.go:7-31`; `schematic/read.go:52-135`).
- Duplicate singleton nodes (for example two `title_block` nodes) mark the file `unsupported_for_mutation` (`schematic/read.go:128-135`).

### Write model

- **Whole-file render from Go data structures.** `schematic.Write`, `pcb.Write`, and the project writer write to an `io.Writer` only. Filesystem writes go through `design.WriteProjectDirectory` (`docs/kicad-file-writers.md`, "Go API"; `internal/kicadfiles/pcb/render.go:17-30`).
- **Overwrite is a directory swap.** A full project is staged in a sibling directory, then swapped in with a move-aside backup, a lock file, and a recovery journal `.<name>.kicadai-journal` (`internal/kicadfiles/design/commit.go:13-60`; `docs/kicad-file-writers.md`).
- **Imported-project mutation exists but is off by default.** `transactions.Apply` refuses unless `AllowImportedMutation` is set or a current KiCadAI manifest proves the target is generated (`internal/transactions/apply.go:74-112`). The imported path re-renders the whole root `.kicad_sch` and/or `.kicad_pcb` from the typed model plus raw fragments (`apply.go:1105-1132`) and writes them as one atomic group (`apply.go:1139-1165`, `internal/atomicfile/group.go`).
- **Preservation is object-level, not byte-level.** `ValidatePreservedMutation` checks that raw paper, title block, raw items, junctions, and sheets are unchanged as strings (`internal/kicadfiles/schematic/preservation_compare.go:10-40`). Formatting and the order of modeled items follow the renderer, not the source file. The writer docs state: "Existing KiCad files are not parsed or edited losslessly" (`docs/kicad-file-writers.md`, "Current Limits").
- Imported writes keep the source file's `(version …)` and fill a missing `generator_version` with `"10.0"` (`apply.go:1225-1240`). Inference: a KiCad 9 file is re-rendered by a KiCad 10-shaped writer under a KiCad 9 version stamp. I did not test this.

### Format versions targeted

| File | Version written | Source |
| --- | --- | --- |
| `.kicad_sch` | `20260306` (same as this package's schematic write format) | `internal/kicadfiles/model.go:23`, `internal/kicadfiles/designapi/builder.go:396` |
| `.kicad_pcb` | `20260206` | `model.go:21`, `builder.go:404` |
| `.kicad_mod` (footprint library module) | `20240108` | `internal/kicadfiles/pcb/render.go:15` |
| `.kicad_pro` | KiCad-shaped JSON; `meta.version` from the project schema | `docs/kicad-file-writers.md`, "Project Structure Support" |

Other constants: `20230121` and `20260512` (schematic) are defined in `model.go:19-24`. `generator_version` is required from schematic `20231120` (`model.go:31`, `schematic/schematic.go:446-462`).

Generated files claim KiCad as generator: `(generator "eeschema")` / `(generator "pcbnew")` with `generator_version "10.0"` (`builder.go:396-406`). Provenance lives in `.kicadai/manifest.json` instead of the file header.

Inference: `20240108` for footprint modules is an older format number than the board and schematic stamps. I did not check it against KiCad 10 source.

### `kicad-cli`

Used for ERC (`sch erc --format json --severity-all --exit-code-violations`), DRC (`pcb drc --schematic-parity --all-track-errors --severity-all`), SVG previews, fabrication plots, and round-trip upgrade (`internal/boardfamily/validate.go:201-275`, `internal/fabrication/plot.go`, `internal/kicadfiles/roundtrip/`). Discovery uses `KICADAI_KICAD_CLI` / `KICAD_CLI` and a platform path list that includes Windows 8/9/10 install roots (`internal/kicadfiles/roundtrip/roundtrip.go:~140-166`). Promotion runs bootstrap a checksum-pinned KiCad distribution (`internal/promotiontoolchain/`, `toolchain/kicad-promotion.lock.json`).

### Round-trip gate (the strongest writer check)

The writer output is copied to scratch, `kicad-cli sch upgrade --force` or `pcb upgrade --force` rewrites the copy, and the two files are compared as **token streams with whitespace and comments removed** (`internal/kicadfiles/roundtrip/README.md`; `roundtrip.go:224-307`). Zero token diffs means KiCad's own save produced the same tokens in the same order. Exceptions need an allowlist entry with a mandatory reason and a narrow matcher (`roundtrip/allowlist.go`). KiCad never runs on checked-in fixtures directly.

### `pcbnew` / SWIG

None found. No Python. Board work is direct file generation.

### KiCad IPC

- Transport: nanomsg via `go.nanomsg.org/mangos/v3` (`internal/ipc/mangos.go`). Bindings are generated from vendored proto files at KiCad commit `030baaeac904084a640784320f7d055a80f1bf91` (`third_party/kicad/README.md`, `third_party/kicad/VERSION`).
- Calls actually made: `Ping`, `GetVersion`, `GetOpenDocuments` (`internal/kiapi/client.go:227-238`, `internal/kiapi/documents.go:34-47`). Nothing else.
- **The capability report is static, not probed.** `CapabilitiesForVersion` adds `schematic.read` when KiCad major ≥ 9 and always lists `schematic.write`, `schematic.symbol.place`, `schematic.wire.place`, `schematic.label.place` as missing. Its notes say the decision "is based on the generated KiCad API surface pinned in this repository" (`internal/kiapi/capabilities.go:33-57`).
- **The report covers schematic workflows only.** It says nothing about board writes. The vendored proto does contain generic editor mutation messages (`BeginCommit`, `EndCommit`, `CreateItems`, `UpdateItems`, `DeleteItems`, `ParseAndCreateItemsFromString`) and board setters (`UpdateBoardStackup`, `SetBoardDesignRules`, `SetBoardOrigin`, `ImportNetlist`) (`third_party/kicad/api/proto/common/commands/editor_commands.proto`, `third_party/kicad/api/proto/board/board_commands.proto`). KiCadAI uses none of them.
- `draw-led-demo --execute` returns a structured "blocked" result because schematic writes are missing (`docs/cli-reference.md:490-502`).

Consequence for ADR 0006: KiCadAI is **not evidence about KiCad 10 PCB IPC write limits**. It is evidence that, against one pinned proto snapshot, the schematic API exposes hierarchy and netlist read only. Any claim about IPC board writes needs a separate source.

### Hierarchy

Generation emits child sheets, validates that every sheet reference resolves, rejects cycles, and allows reused child files. It does not manage per-instance annotation for reused sheets; it tells users to run KiCad annotation (`docs/kicad-file-writers.md`, "Hierarchical Sheets", "Current Limits"). Read keeps `sheet` nodes raw (`schematic/read.go:100-107`). Imported apply writes only `<base>.kicad_sch` (`apply.go:1113`). Inference: imported mutation is root-sheet only.

### Library tables and `${VAR}`

- Writes project `sym-lib-table` / `fp-lib-table` when the model has entries. Does not generate `.kicad_sym` or `.pretty` content (`docs/kicad-file-writers.md`, "Library Tables").
- Reads `sym-lib-table` with its own parser (`internal/libraryresolver/symbol_table.go:114-155`).
- `${VAR}` expansion uses process environment variables, `KIPRJMOD`, and synthetic aliases that map `KICAD_SYMBOL_DIR` and `KICAD6_SYMBOL_DIR`…`KICAD20_SYMBOL_DIR` all to one configured root, plus lowercase aliases (`symbol_table.go:157-230`). A grep found no read of `kicad_common.json`. Inference: user-defined path variables from KiCad's settings are not resolved.
- Library roots come from flags or `KICADAI_SYMBOLS_ROOT` / `KICADAI_FOOTPRINTS_ROOT` (`docs/library-resolver.md`).

### Connectivity

Own geometry. PCB connectivity uses a spatial grid of pad, track, arc, and via anchors (`internal/kicadfiles/pcb/connectivity.go:12-30`). Schematic electrical checks are internal (`internal/schematicrules`, not read in depth). `kicad-cli` netlist export appears in an integration test only (`docs/kicad-file-writers.md`, "Validation"). DRC with `--schematic-parity` is the KiCad-side cross-check.

## API / tool surface

Agent surface is the `kicadai` CLI with JSON on stdout (one document on success and failure) and logs on stderr (`docs/cli-reference.md:69-70`). Main commands:

| Command | Job | Granularity |
| --- | --- | --- |
| `capability generation --json` | Report supported graph features, catalog vocabulary, evidence gates | one-job (query) |
| `intent compile` | Behavior text → strict requirement, clarification, or capability gap (provider-backed) | one-job |
| `circuit preflight` | Validate a `generic-circuit-v1` graph; `ready_for_write` | one-job |
| `circuit patch`, `circuit repair-plan` | Typed graph corrections; plan only when one safe fix is derived | one-job |
| `circuit create` / `intent create` / `design create` | Graph or intent → schematic, PCB, placement, routing, validation, evidence | **composite** |
| `schematic-ir validate|normalize|transaction|write` | Strict JSON schematic IR to transactions or files | one-job each |
| `generate-led-demo`, `generate breakout` | Fixed generators | composite |
| `inspect project`, `evaluate project|schematic|pcb` | Read-only readiness checks | one-job |
| `validate board` | Generated-board connectivity | one-job |
| `check erc`, `check drc` | `kicad-cli` wrappers | one-job |
| `writer check` | Writer correctness, optional round-trip | one-job |
| `repair plan|export-bundle|apply` | Repairs against generated targets; `--execute` gates mutation | one-job each, apply is composite |
| `library index|symbol|footprint|symbols …` | Resolver queries and KLC checks | one-job |
| `component list|show|find|select|validate` | Curated catalog | one-job |
| `fabrication profile …`, `export preview|fabrication` | Profiles and fab output | one-job / composite |
| `ping`, `kicad-version`, `documents`, `capabilities` | Live IPC probes | one-job |
| `adapter` | Fixed stdin/stdout protocol for the NetForm client | one-job |

Sources: `docs/cli-reference.md` (`:421-620`), `docs/kicadai-agent-skill.md`, `README.md`, `integrations/netform-client/README.md`.

## Agent and tooling glue

**Prompt side.** One long operational skill (`docs/kicadai-agent-skill.md`, 843 lines). It tells agents to query capability first, consume JSON, stop on blockers, "not work around blockers by editing KiCad files manually", and preserve `.kicadai/` evidence with any handoff (`agent-skill.md:7-56`, `:755-770`). Imported-project review is read-first: treat preservation-only content as read-only unless the plan marks an operation `safe_add` and the user approves (`agent-skill.md:452-462`).

**Code side: the verdict model.** This is the part most worth studying.

- **Capability gate before any write.** Each request is classified `supported`, `experimental`, or `unsupported`. Unsupported refuses before filesystem mutation with stable gap codes. Experimental refuses unless `--experimental`; then it can reach at most `candidate`, never `pass` (`docs/capability-gating.md`, "Classifications").
- **Evidence states.** `verified` (stable source plus SHA-256), `inferred`, `missing`, `failed`. Inferred evidence on a required claim forces `experimental` (`capability-gating.md`, "Evidence lifecycle").
- **Monotonic classification.** Later stages may keep or lower confidence. They cannot raise it (`capability-gating.md`).
- **Verdict vocabulary.** Promotion status `pass | warn | failed | expected_fail | unexpected_pass | blocked | skipped | error | not_run`; gate status `pass | warn | failed | skipped | not_run`; readiness `expected_fail | candidate | pass | blocked` (constants under `internal/creationevidence`, `internal/designworkflow`, found by grep). Repair results use `repaired | partial | blocked` (`cli-reference.md:553-559`).
- **What is recorded.** Six core files under `<output>/.kicadai/`: `design-request.json`, `transaction.json`, `workflow-result.json`, `validation-summary.json`, `design-promotion.json`, `manifest.json`. Each has a `schema_version`. The manifest lists every core artifact with path, SHA-256 of exact bytes, schema version, and generation stage. Evidence outside the project is indexed with `external-evidence://` content URIs (`docs/creation-evidence.md`).
- **Skipped is visible.** Skipped stages stay as gates with `status: "skipped"` and a rationale. Inapplicable promotion writes `applicability.status: "inapplicable"` instead of omitting the file (`creation-evidence.md`).
- **Refusal emits no project.** The public refusal receipt records `result: refused`, `status: exhausted`, `stop_reason: search_exhausted`, a coded diagnostic, budget consumption, and `kicad_project_emitted: false`. Its own interpretation says this is "a bounded capability refusal, not proof that no physical solution exists" (`examples/public-demo/protected-programmable-current-output/evidence/refusal-receipt.json`). The README frames the same demo as a thermal/SOA refusal (README claim); the receipt shows budget exhaustion, and points to a separate audit for the SOA rejection.
- **Pass receipt** binds input, inventory, model registry, catalog, policy hashes, search counts, selected topology and physical hashes, per-gate status (route completion, connectivity, writer correctness, ERC, strict DRC, round-trip, deterministic replay with two project hashes), and a `claim_boundary` with `fabrication_release: false` (`evidence/receipt.json`).
- **Check allowlists** need a reason and return allowed findings separately, so they stay visible (`internal/kicadfiles/checks/allowlist.go`, `roundtrip/allowlist.go`). ERC findings are also classified by source (`writer_semantics` vs `electrical_design`) and stage (`checks/erc_classification.go`).

**Session state and rollback.** No session object. State is the output directory plus `.kicadai/`. Rollback is the directory-swap journal for generated projects and the atomic group write for imported files. Repair loops carry `input_hash` / `--previous-hash` to stop cycles (`agent-skill.md`, "Capability Boundaries").

**Determinism.** UUIDv5 from design ID, seed, and a length-prefixed NFC scope path (`internal/kicadfiles/model.go:150-186`). Replays compare project hashes.

**Token/context management.** JSON-only stdout; compact receipts beside full raw evidence that "can approach 1 GB" (`README.md`). No explicit context budgeting in code.

## Comparison matrix

| Axis | KiCadAI | HITL | This package (locked ADRs) |
| --- | --- | --- | --- |
| Product shape | Go CLI; generator plus evidence engine; no library API | Method + skill + per-project skeleton | Installable Python library of KiCad capabilities |
| Design home | Behavior request → typed graph → Go structs; KiCad files are output | Python generator | KiCad files plus project and library context |
| Write model | Whole-file render; imported files re-rendered with raw-node carry-through; object-level preservation check | Full generate / rewrite | Source-preserving localized edit; byte-identical no-op (ADR 0003) |
| Lifecycle | Pipeline run plus directory commit; imported apply is one transaction with a final `write_project` op | Pipeline run | Open, read, modify, validate, write, close; revert, discard (ADR 0008, 0011) |
| Executive vs primitives | Executive. `design create` sequences search, write, place, route, check, promote | Executive (`Board.run()`) | Primitives only (ADR 0009) |
| Hierarchy | Generates child sheets; reads sheets raw; imported apply root-only | Weak | Core (`SheetFile`, `SheetSymbol`, `Schematic`) |
| Library tables / `${VAR}` | Reads and writes project tables; env + synthetic `KICADn_SYMBOL_DIR` aliases; no `kicad_common.json` found | Minimal seed tables | First-class area (ADR 0002) |
| Connectivity | Own geometric PCB graph + internal schematic rules; DRC schematic parity | Buried in parity gates | Client before/after `netlist()` compare |
| Reuse | One binary; JSON contracts; subprocess adapter for one consumer | Copy templates | One package, many consumers after 1.0 |
| Agent host concerns | In tool: capability gate, refusal, evidence files, skill doc | In repo: swarm, slots, hooks | Out of package (ADR 0012 proposed) |
| KiCad IPC | Probe only: ping, version, open documents; static capability table | None noted | Out of default scope (ADR 0006) |
| License | MIT (vendored KiCad proto keeps upstream licenses) | HIL-ASA-1.0 | MIT |

## Pressure on our decisions

### Claims that hold

| Claim | Why KiCadAI does not overturn it |
| --- | --- |
| ADR 0003 source-preserving localized edit | KiCadAI built a typed model with raw carry-through and still documents "not parsed or edited losslessly". Its imported writes reorder and reformat modeled items. Our donors (Railroad edits, Subdivision) need byte-local edits; KiCadAI's approach would churn their diffs. |
| ADR 0003 one parser | KiCadAI shows the cost of a writer-owned parser: two parsers would exist if a client used both tools. It also shows that a renderer keyed to KiCad's canonical form is achievable and testable. |
| ADR 0008 explicit persistence | KiCadAI never saves on mutation. Imported apply requires an explicit final `write_project` op (`apply.go:186-190`, `:433`). This is the same instinct as our buffered-then-save model, expressed as a transaction stream. |
| ADR 0009 primitives, not an executive | KiCadAI's value is its executive (search, gate, refuse). It shipped as a CLI, not a library, and states that `internal/` is not API. That supports keeping the executive outside `kicad_primitives`. |
| ADR 0009 policy above primitives | Ownership (generated vs imported), `safe_add`, and refusal live in `transactions` and `preservation`, not in the file writers. The writers write to `io.Writer` only. This is the layering ADR 0009 asks for. |
| ADR 0011 nouns | KiCadAI's `SchematicFile` is one file, and sheets are a separate raw-carried node. It has no cross-file `Schematic` noun and no instance model. Its own docs list per-instance annotation as a gap. That gap is the reason ADR 0011 has `SheetInstance`. |
| ADR 0006 IPC out of default path | KiCadAI found IPC useful only for probes. Live schematic writes are blocked. IPC also needs a running GUI. Nothing here argues for an IPC default. |
| ADR 0012 sibling server, structured evidence | KiCadAI's `.kicadai/` evidence set is a working example of rule 6 (structured evidence). It lives in the tool, not in the I/O layer. |

### Claims worth attacking

| Pressure | Possible crack | What would change if the crack is real |
| --- | --- | --- |
| "Generator-first stays outside layer-0 library nouns" (HITL note; ADR 0012 §5) | KiCadAI started generator-only and then needed read, evaluate, and imported mutation. It reused the generator's structs (`schematic.SchematicFile`, `pcb.PCBFile`) as the read model. Generators converge on file-level nouns. If our layer 0 offers no **create-from-empty and add-item** operations (new `SheetFile`, add symbol, wire, label; deterministic UUIDs), a generator client will build its own writer and its own parser. That is a second sexpr stack, which ADR 0012 forbids. | The ontology claim holds: do not redefine `SheetFile` as a generator DTO. The capability claim cracks: generator clients need layer-0 creation primitives. Follow-up: **ADR 0012 wording** to say generators sit on public layer-0 creation and add-item primitives, plus a **grill** on whether item creation (not only attribute edits) is in the ADR 0006 bar. |
| "Byte preservation is the right default for every write" (ADR 0003) | KiCadAI gets strong confidence from a different gate: token-level equality with KiCad's own `upgrade --force` output. For newly created files and inserted nodes, "matches KiCad's canonical save" may be the better contract than byte preservation, which has nothing to preserve. | No change for edits. For inserted nodes and new files, add KiCad canonical-token equality as a functional gate beside byte preservation of untouched content. Follow-up: **ticket** (functional gate on the KiCad-formatting rule already in AGENTS). |
| "pcbnew / IPC stays out of default scope" (ADR 0006) | The vendored proto snapshot has generic `CreateItems` / `UpdateItems` / `DeleteItems` with commits and several board setters. KiCadAI never tests them. If KiCad 10 board IPC writes work, a live-editor PCB path exists that needs no SWIG. | No change to the default path: IPC needs a running GUI and is a different runtime. If the owner wants a live-editor lane, it belongs in the sibling server (ADR 0012 open question 5), not the library. Follow-up: **grill**, only when PCB edit scheduling starts. Do not cite KiCadAI as evidence either way. |
| "Peer locks are only a query" (ADR 0008/0009) | KiCadAI takes its own advisory lock and recovery journal for overwrites (`design/commit.go:47-55`, `internal/atomicfile/lock.go`). That is a writer-side lock, not a KiCad peer lock, but it shows tools want one. | Package rule can stay. Directory-swap journaling is a whole-project generate concern, not a layer-0 file save. Follow-up: **none**. |
| "Connectivity verify is only a client sequence" (ADR 0009) | KiCadAI does not trust one connectivity source. It runs its own geometric graph, then KiCad DRC with schematic parity, and records both. A single `netlist()` before/after compare may miss physical-only breaks on PCBs. | For schematic edits, before/after netlist still fits. For PCB edits, a client may need netlist compare plus DRC parity. Follow-up: **ADR 0012 wording** for release composites to name both steps. |
| "Structured gate evidence is out of scope for the library" (HITL note) | KiCadAI's evidence shape (status enums incl. `skipped` and `not_run`, content hashes, monotonic downgrade, `claim_boundary`) is mature and language-neutral. Without a shared vocabulary, each MCP or CLI invents its own. | Library still returns typed objects only. A shared evidence vocabulary could be a **cross-language contract document** owned by the future server. Follow-up: **ADR 0012 wording** (cite this vocabulary as prior art for rule 6). |

## Steal list (outside or beside the package)

1. **KiCad canonical-token round-trip gate** — copy to scratch, `kicad-cli … upgrade --force`, compare whitespace-free token streams, allowlist only with reason (`internal/kicadfiles/roundtrip/`). Layer: package functional tests for inserted nodes and new files. Contract, not code.
2. **Verdict vocabulary** — `pass | warn | failed | blocked | skipped | not_run | error`, evidence states `verified | inferred | missing | failed`, monotonic downgrade rule (`docs/capability-gating.md`, `docs/creation-evidence.md`). Layer: future MCP server envelope (ADR 0012 rule 6).
3. **Manifest of evidence by content hash** — path, SHA-256, schema version, stage; external evidence by content URI; no self-hash (`docs/creation-evidence.md`). Layer: server or CI edge.
4. **Claim boundary field** — every pass receipt says what it does **not** prove (`fabrication_release: false`). Layer: server and host skill.
5. **Refusal as a first-class result** — coded diagnostic, budget consumption, "no project emitted", and an honest interpretation line (`refusal-receipt.json`). Layer: server composites.
6. **Ownership and mutability labels** — `generated_owned | imported_user | preservation_only`, `read_only | plan_only | safe_add | unsafe` (`internal/preservation/model.go:27-43`). Layer: server session policy for agent writes to user projects. Not a library guard.
7. **Capability probe as a tool** — agents call `capability generation` before acting (`agent-skill.md`). Layer: MCP `capabilities` tool that reports shipped primitives. Make it **probed**, not a static table (see Reject 5).
8. **Deterministic UUIDv5 recipe** — design ID namespace, seed, length-prefixed NFC scope path (`internal/kicadfiles/model.go:150-186`). Layer: a generator client; optionally a layer-0 creation helper if creation primitives land.
9. **Subprocess adapter discipline** — fixed argument, one request on stdin, bounded input/output/stderr and timeout, credential env stripped (`integrations/netform-client/README.md`). Layer: any consumer that shells out to a CLI.

## Reject list

1. Whole-file re-render with object-level preservation as the edit core. It conflicts with ADR 0003 byte preservation.
2. A second S-expression parser or renderer inside or beside `kicad_primitives`. ("One parser" rule.)
3. The executive pipeline (`design create`, search, placement, routing, promotion) as library API. ADR 0009.
4. Writing `(generator "eeschema")` / `"pcbnew"` from a non-KiCad tool. It hides provenance in the file. Our edits keep the source header; new-file policy needs its own decision.
5. A static IPC capability table derived from pinned bindings. It reports what the bindings expose, not what the running KiCad does, and it is silent on board writes.
6. Synthetic `KICAD6…20_SYMBOL_DIR` aliases mapped to one root. It masks wrong tables. EagleLib2KiCad's real `kicad_common.json` resolution is the donor to keep.
7. Frozen versioned evaluator packages kept as live code (`corpusfreezev6`…`v10`, `discovery-baseline-v10`…`v23`). Debt pattern, not a model.

## Overlap with our donors

| Donor job | KiCadAI equivalent | Note |
| --- | --- | --- |
| jBOM: sexpr read, project discovery, BOM | `internal/kicadfiles/sexpr`, `project/read.go`, `internal/fabrication` | Own parser; BOM/fab export inside fabrication. |
| kproj: `kicad-cli` locator and exporters | `roundtrip.go` candidate paths, `promotiontoolchain`, `fabrication/plot.go` | Adds checksum-pinned KiCad bootstrap. ADR 0007 already covers discovery. |
| kDoctor: ERC/DRC interpretation, footprint read | `internal/kicadfiles/checks` (JSON parse, ERC classification, allowlist), `libraryresolver/footprint_parser.go` | ERC source/stage classification is a useful idea for kDoctor. |
| EagleLib2KiCad: tables and `${VAR}` | `libraryresolver/symbol_table.go` | Weaker: env vars and synthetic aliases, no `kicad_common.json` found. |
| FieldUnit-Subdivision: byte-preserving edits, symbol model, netlist gate | `schematic/read.go` raw carry-through, `libraryresolver/symbol_parser.go`, `pcb/connectivity.go` | Not byte-preserving. Own geometric connectivity instead of a KiCad netlist gate. |

## Sources read

| Path (KiCadAI clone) | Depth |
| --- | --- |
| `README.md`, `SUPPORT.md`, `LICENSE`, `VERSION`, `go.mod`, `.go-version` | Read |
| `docs/kicad-file-writers.md`, `docs/creation-evidence.md`, `docs/capability-gating.md` | Read |
| `docs/kicadai-agent-skill.md` | Read lines 1-175, 450-480, 755-775; rest skimmed by grep |
| `docs/cli-reference.md` | Read 421-620; IPC section by grep |
| `docs/library-resolver.md` | Read 1-60 |
| `internal/kicadfiles/model.go`, `preservation.go` | Read |
| `internal/kicadfiles/sexpr/parse.go`, `sexpr.go` | Read 1-200 each |
| `internal/kicadfiles/schematic/read.go` | Read 1-200 |
| `internal/kicadfiles/schematic/schematic.go`, `templates.go`, `preservation_compare.go` | Excerpts |
| `internal/kicadfiles/pcb/render.go` | Read 1-200 |
| `internal/kicadfiles/pcb/connectivity.go` | Header only |
| `internal/kicadfiles/design/commit.go` | Read 1-60 |
| `internal/kicadfiles/designapi/builder.go` | Read 306-505 |
| `internal/kicadfiles/roundtrip/README.md`, `roundtrip.go` (161-360), `allowlist.go` | Read / excerpts |
| `internal/kicadfiles/checks/erc_classification.go`, `allowlist.go` | Read 1-60 / 1-40 |
| `internal/kiapi/capabilities.go` | Read |
| `internal/kiapi/client.go`, `documents.go` | Function list by grep |
| `third_party/kicad/README.md`, `VERSION`; proto `message` names in `editor_commands.proto`, `schematic_commands.proto`, `board_commands.proto` | Grep |
| `internal/transactions/apply.go` | Function list and 1105-1165, 1225-1245 |
| `internal/transactions/plan.go` | Grep for imported/safe_add |
| `internal/preservation/model.go` | Read 1-80 |
| `internal/libraryresolver/symbol_table.go` | Read 91-230 |
| `internal/pinmap/pinmap.go` | Read 1-50 |
| `internal/boardfamily/validate.go` | `kicad-cli` call lines by grep |
| `examples/public-demo/.../EVIDENCE.md`, `evidence/receipt.json`, `evidence/refusal-receipt.json` | Read / structure dump |
| `integrations/netform-client/README.md` | Read head |
| `specs/`, `internal/opentopologysynthesis`, `internal/capabilityfeedback`, `internal/simmodel`, placement and routing | Not read (directory listing only) |

This repo: `AGENTS.md`, `docs/adr/README.md`, `docs/adr/0012-future-mcp-tool-surface.md`, ADR 0006 IPC lines (grep), `docs/review/hitl-comparison-2026-11-10.md`, `docs/review/external-survey-brief-2026-11-11.md`. ADR 0003, 0008, 0009, 0011 through the `AGENTS.md` summaries and the ADR index, not full text.

## Confidence and gaps

- **Not run.** I did not build or run KiCadAI, its tests, or `kicad-cli`. All behavior claims come from code and docs.
- **Synthesis, simulation, placement, routing** were not reviewed. They are most of the code. Claims about search counts and simulation come from the receipt and README only.
- **KiCad 10 IPC write limits.** Not verified. KiCadAI's capability table is static and schematic-only. I did not check which vendored proto messages KiCad 10.0.x implements for the board or schematic editor. The vendored commit hash is not mapped to a KiCad release tag.
- **Format stamps.** I did not check whether `20240108` (footprint module) and `20260206` (board) match what KiCad 10.0.3 writes. The round-trip gate would catch drift for generated files; I did not see its artifacts.
- **Imported-write version drift.** The "KiCad 9 stamp with KiCad 10 shapes" risk is inference from `apply.go:1225-1240` and the read path. Not tested.
- **`kicad_common.json`.** Absence is from a grep of `internal/libraryresolver` and `internal/kicadfiles/library` only.
- **Self-review claims** in `docs/project-review-2026-09-06.md` were taken from the README summary; I did not read the review.
- **ADR full text.** I worked from `AGENTS.md` summaries of ADR 0003, 0008, 0009, 0011. An adversary should re-check the "claims that hold" rows against full ADR text.
