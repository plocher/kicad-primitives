# External survey synthesis and adversary pass (2026-11-11)

Status: adversary output for PR #83. Not an ADR. Recommends follow-ups; the owner decides.

Method: Structured-B ([brief](external-survey-brief-2026-11-11.md)). Five external projects, one rubric, one synthesis, one critical review of this package.

Inputs:

| Subject | Shape | Note |
| --- | --- | --- |
| HITL (claude-hardware-in-the-loop) | Method + skill + generator pipeline | [hitl-comparison-2026-11-10.md](hitl-comparison-2026-11-10.md) |
| kicad-happy | Skill pack + stdlib CLI analyzers + GitHub Action | [ext-kicad-happy-2026-11-11.md](ext-kicad-happy-2026-11-11.md) |
| Seeed kicad-mcp-server | Stateless MCP server, 47 tools | [ext-seeed-kicad-mcp-server-2026-11-11.md](ext-seeed-kicad-mcp-server-2026-11-11.md) |
| KiCad-AI-Assistant | In-KiCad plugin with own LLM loop + MCP server, about 110 tools | [ext-kicad-ai-assistant-2026-11-11.md](ext-kicad-ai-assistant-2026-11-11.md) |
| KiCadAI | Go CLI generator + evidence and refusal engine | [ext-kicadai-2026-11-11.md](ext-kicadai-2026-11-11.md) |

## Portfolio at a glance

| Axis | HITL | kicad-happy | Seeed MCP | AI-Assistant | KiCadAI |
| --- | --- | --- | --- | --- | --- |
| Agent transport | Claude skill | Skill + CLI + JSON Schema (5 hosts, CI) | MCP (stdio) | MCP + in-app chat | CLI + JSON + skill doc |
| Parser | String / regex writers | Own nested-list reader + regex span writer | Regex + paren counting | kicad-skip + sexpdata + span splice | Own parser + renderer |
| Edit model | Generate whole project | Read-only; 2 property writers | Append-only splice, write on call | Whole-file rewrite, write on call | Whole-file render; imported edit off by default |
| Byte preservation | No | Partial (CRLF lost) | Partial (append only) | No (sch, pcb) | No (object-level check) |
| Connectivity | `kicad-cli` gates + parity | Own Python engine; `kicad-cli` as recorded oracle | `kicad-cli` netlist (pin types dropped) | Own per-sheet geometry | Own PCB geometry + DRC parity |
| `pcbnew` / IPC | `pcbnew` | None | `pcbnew` in process | IPC for GUI sync; `pcbnew` in plugin | IPC probe only |
| Tables / `${VAR}` from `kicad_common.json` | No | No | No | No (env only) | No (env + aliases) |
| Session state | Repo + harness | Run folders on disk | None | Plugin turn state; server stateless | Output dir + `.kicadai/` |
| Evidence | Results JSON + hashes | Schema'd envelopes, diagnostics, quarantine | Markdown + emoji | JSON `success` dicts, some false positives | Verdict enums, hashes, claim boundary, refusal receipts |
| License | HIL-ASA-1.0 | MIT | MIT declared, no LICENSE file | MIT | MIT |

## Convergent observations

1. **No subject edits existing KiCad files byte-locally.** Each one either generates, rewrites whole files, appends, or edits a narrow property family with line-ending loss. The package's core niche (ADR 0003) has no peer in this set.
2. **Every subject that writes needs more than one parser or a full re-render.** The "one parser" rule is the expensive part that others skip.
3. **Four of five create schematic items** (symbols, wires, labels, sheets, or whole files). The package creates library items but no schematic items today.
4. **Three of five have no MCP.** Skill text plus CLI plus JSON reaches more hosts (five, plus CI) than the two MCP servers do.
5. **Both MCP servers are stateless and save on every call.** Neither holds document handles. That shape fights ADR 0012 rule 3 directly.
6. **Domain gates always sit above the file layer** (EMC, SPICE, sourcing, fab, review). No subject puts them in its parser layer.
7. **No subject resolves `${VAR}` from KiCad's own settings.** The tables area (EagleLib2KiCad donor) is unique in this set.
8. **Nobody verified KiCad 10 IPC board writes.** KiCadAI's IPC table is static and schematic-only. AI-Assistant uses IPC only for flush, revert, refill, and GUI actions.
9. **Evidence quality varies widely.** Structured envelopes (kicad-happy, KiCadAI, HITL) carry verdicts that code can read. Prose and success flags (Seeed, AI-Assistant) produced real false passes in both projects.

## Claim matrix

Cells: **holds** (subject supports the claim), **presses** (subject exposes a crack), **silent**.

| Our claim | HITL | happy | Seeed | Assistant | KiCadAI | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| ADR 0003 one lossless parser, localized edits | holds | holds | holds | holds | holds; presses on new nodes | **Holds.** Add a canonical-token gate for inserted nodes (C5). |
| ADR 0008/0011 buffered lifecycle, explicit save | silent | holds | holds | holds | holds | **Holds for the library.** Presses on the MCP layer (C1). |
| ADR 0009 primitives, not an executive | holds | holds | holds | holds | holds | **Holds.** Every executive in the set lives in a tool, skill, or client. |
| ADR 0009 peer lock is a query | silent | holds | silent | presses | holds | **Holds as library rule.** GUI coexistence is a separate, real problem (C2). |
| ADR 0009 connectivity is a client before/after compare | silent | presses (no-KiCad hosts) | holds | silent | presses (PCB needs parity too) | **Holds for schematics.** PCB release needs netlist plus DRC parity (C7). |
| ADR 0011 `Schematic` is a set of sheet trees; instances matter | silent | holds | holds | holds | holds | **Holds.** Only kicad-happy models instances; all writers ignore them. |
| ADR 0011 D7 backup holds all project files | silent | silent | silent | presses (theirs is root-only) | silent | **Holds.** Verified in `src/kicad_primitives/_project_backup.py:26-41,101-127`. No ticket. |
| ADR 0002 tables and `${VAR}` are first-class | holds | holds | holds | holds | holds | **Holds strongly.** |
| ADR 0006 read scope sufficient for consumers | silent | presses | presses | silent | presses | **Crack** (C3). |
| Item creation is not a 1.0 need | presses | silent | presses | presses | presses | **Crack** (C4). |
| ADR 0006 `pcbnew` / IPC out of default scope | presses | holds | presses | presses | holds | **Holds for the library.** Server-side lane is open (C9). |
| ADR 0012 MCP is the agent surface | silent | presses | holds | holds | presses | **Crack in wording** (C6). |
| ADR 0012 rule 3 buffered mutations in MCP | silent | silent | presses | presses | holds | **Crack** (C1). |
| ADR 0012 rule 5 engine tools explicit | holds | holds | presses | presses | holds | **Holds with a freshness clause** (C8). |
| ADR 0012 rule 6 structured evidence | holds | holds | holds (by failure) | holds (by failure) | holds | **Holds strongly.** Add vocabulary prior art (C8). |
| ADR 0012 rule 8 isolate KiCad profile | holds | silent | presses (no damage seen) | silent | silent | **Open.** Needs evidence, not taste (C9). |
| ADR 0012 §5 generators stay outside layer-0 nouns | holds | silent | silent | silent | holds as ontology; presses as capability | **Holds as ontology.** See C4. |

## Attacks that failed

1. **"Backup misses sub-sheets."** It does not. `_inventory` walks the project directory and keeps every KiCad extension, library table, and local library. AI-Assistant's root-only checkpoint is their defect, not ours.
2. **"Hidden netlist reuse goes stale."** `Project.netlist()` stages the pending content on every call and returns `provenance` with content hashes (`projects.py:293-318`). No cache is reused. Seeed's stale-netlist bug cannot occur through the public primitive.
3. **"Primitives should embed gates."** Every subject that ships gates keeps them above the file layer. No evidence for moving any gate down.
4. **"Peer locks should guard writes."** No subject guards with locks. The data-loss path in AI-Assistant is unsaved GUI state, which a lock file does not describe. A lock guard would not fix it.
5. **"One parser is too costly."** Each subject that skipped it now carries two or three writers, line-ending loss, or whole-file churn. The cost is real and it pays.

## Cracks that landed

Ranked by strength of evidence and by cost if ignored. Each names a follow-up kind and the existing ticket it feeds, where one exists.

### C1. MCP session model for buffered edits (strong; 2 of 2 MCP servers)

Both MCP servers are stateless and save on every call. ADR 0012 rule 3 needs server-held document handles, handle lifetime, idle and exit behavior, and a crash story. ADR 0012 does not define these.

Follow-up: **ADR 0012 wording** (name a session and handle model; map server exit and idle timeout to ADR 0011 `on_close`; allow an explicitly named per-call "open, edit, save" composite for stateless clients). Then **grill** when MCP is scheduled (open question 6).

### C2. Coexistence with a running KiCad (strong; real data-loss path)

KiCad 10 IPC cannot save or revert a schematic. A file writer beside a running eeschema can lose the agent's edit or the user's unsaved edit. Nothing in the file system tells which. AI-Assistant hits this. Seeed tells users to reopen KiCad.

Follow-up: **input to #78** (the `KiCad` scope is #78 work). Also **ADR 0012 wording**: servers check `is_locked`, refuse or warn by policy, and never revert the GUI silently. Usage pages may need a "KiCad is open" caution. The library rule (lock is a query) stays.

### C3. Read-model depth for consumers (strong; kicad-happy built about 13k lines to get it)

Domain gates need instance-resolved references, typed pin nets, variants, PCB copper connectivity, zones, and net classes. If the package ships edit nouns without these read facts, each consumer grows a second parser. That defeats "one parser" and "each fact has one source" one level up.

Follow-up: **grill**, scoped to which read facts ADR 0006 B owns for PCBs and Connectivity. Feeds **#34** (PCB read) and **#79** (sheet instances).

### C4. Schematic item creation (strong; 4 of 5 subjects create items)

The package creates and edits library items. It does not create schematic items (symbol placement, wire, label, sheet, new sheet file). Generator and agent clients need these. Without them they write a second sexpr stack. KiCadAI shows the drift: its generator structs became its read model.

Follow-up: **grill** on whether item creation is in the 1.0 bar or post-1.0. Plus **ADR 0012 §5 wording**: generators sit on public layer-0 creation primitives and never on their own writers. Related: W4-ORDER-01 already fixes insertion order for placed symbols.

### C5. Canonical-token gate for inserted nodes and new files (medium; cheap)

Byte preservation has nothing to preserve for new nodes. KiCadAI tests inserted output against `kicad-cli … upgrade --force` as whitespace-free token streams, with a reasoned allowlist. AGENTS already names KiCad's save as the formatting reference. This makes it testable.

Follow-up: **ticket** (functional gate, opt-in native, beside the existing verifiers). Check existing native gates first; part of this may exist.

### C6. MCP is one transport, not the surface (medium; 3 of 5 have no MCP)

kicad-happy reaches five hosts and CI with skill text, CLIs, and `--schema` JSON. KiCadAI uses CLI plus JSON. The stable part is the tool contract (inputs, envelope, verdict), not the transport.

Follow-up: **ADR 0012 wording**: candidate C becomes "sibling agent surface", with MCP and CLI-plus-schema as transports over one contract.

### C7. PCB release needs more than a netlist compare (medium)

KiCadAI and HITL both pair connectivity with DRC schematic parity. A before/after netlist compare cannot see physical-only breaks.

Follow-up: **ADR 0012 wording** for release composites (name netlist compare and DRC parity as separate steps). Feeds **#34** when DRC lands.

### C8. Freshness and evidence vocabulary (medium)

Seeed moved from an explicit netlist step to hidden reuse and got stale answers. AI-Assistant reports "success" for GUI dialogs that return no verdict. KiCadAI has a mature verdict vocabulary: `pass | warn | failed | blocked | skipped | not_run | error`, evidence states `verified | inferred | missing | failed`, monotonic downgrade, and a `claim_boundary` field.

Follow-up: **ADR 0012 wording**: (a) a derived tool may reuse an engine result only when source fingerprints match, and must name what it used (our netlist provenance already supplies the hashes); (b) dispatch-only tools report `dispatched`, never a verdict; (c) cite KiCadAI and kicad-happy envelopes as prior art for rule 6.

### C9. `pcbnew` and IPC on the server side (open; needs evidence)

Seeed's best PCB numbers come from `pcbnew`. AI-Assistant needs IPC for board flush and revert. Nobody verified KiCad 10 IPC board writes. Seeed ran CLI exports on the user profile with no reported harm, which questions how broad ADR 0012 rule 8 must be.

Follow-up: **grill** when PCB edit work is scheduled. **ADR 0012 wording** now: list IPC beside `pcbnew` as server-only and purpose-limited. Keep rule 8, and mark its scope as open.

### C10. Hosts without KiCad (low)

`netlist()` and `erc()` need `kicad-cli`. kicad-happy works on CI and cloud hosts with no KiCad, using a pure-Python engine checked against recorded `kicad-cli` output. A second connectivity engine in the package is a large build and a second source of truth.

Follow-up: **none** for the engine. Record the limit in `docs/netlist.md` when next touched. The recorded-oracle test pattern is worth noting for tests.

### C11. Degraded-read signal (low; speculative)

kicad-happy carries `diagnostics` for near-miss joins and skipped steps. Our primitives raise on unsupported content but return no "partial read" record. No concrete failure was found.

Follow-up: **park**. Revisit if a consumer reports a silent partial read.

## Proposed ADR 0012 edits (for owner decision, not applied)

1. §6 becomes "Relationship to external KiCad-agent projects". HITL plus the four surveyed projects, each with one line on what it informs. Reviews live in `docs/review/`; popularity accepts nothing.
2. Candidate C wording: sibling **agent surface** with one tool contract; MCP and CLI-plus-JSON-Schema are transports (C6).
3. Rule 3: add a session and handle model, server exit and idle mapping to `on_close`, and a named per-call composite for stateless clients (C1).
4. New rule: coexistence with a running KiCad (C2).
5. Rule 5: add the freshness clause (C8a).
6. Rule 6: dispatch-only tools report `dispatched`; cite verdict vocabulary prior art (C8b, C8c).
7. §4: list KiCad IPC beside `pcbnew` as server-only and purpose-limited (C9).
8. §5: generators use public layer-0 creation primitives (C4).
9. Release composites: netlist compare and DRC parity as separate named steps (C7).
10. Open questions: add rule 8 scope (C9) and item-creation timing (C4).

## Proposed tickets and grills (for owner decision, not filed)

| Item | Kind | Attach to |
| --- | --- | --- |
| C2 GUI coexistence | input | #78 |
| C3 read-fact scope for PCB and Connectivity | grill | #34, #79 |
| C4 schematic item creation in or after 1.0 | grill | new, or ADR 0006 follow-up |
| C5 canonical-token gate for inserted nodes | ticket | new |
| C9 `pcbnew` / IPC server lane | grill | when PCB edit is scheduled |

## Blind spots of this survey

1. **Nothing was executed.** All five notes come from reading code. Claimed defects in Seeed and AI-Assistant are code facts or labeled inference.
2. **Agents read our ADRs through AGENTS summaries**, not full text. The lead re-checked the backup and netlist rows against `src/`. Other "holds" rows rest on summaries.
3. **No library peer was surveyed.** None of the five is a reusable KiCad I/O library. The package-shape claim (one installable library, many consumers) was not pressed by a true peer. A second wave should cover library peers: `kiutils`, `kicad-skip`, KiCad's `kicad-python` (`kipy`), and the sexpr layer of KiCad's own tooling.
4. **Library authoring is unpressed.** No subject edits symbol or footprint libraries in depth. Our deepest shipped area got no adversary.
5. **Snapshots move.** Each clone is one commit. Two subjects changed in the last week.

## Effect on PR #83

- The HITL note needs no correction. Its "claims worth attacking" rows are now answered or sharpened here.
- ADR 0012 stays **Proposed only**. The edits above wait for the owner.
- Recommended: land this synthesis and the four notes in #83, apply the ADR 0012 edits the owner accepts, then merge.
