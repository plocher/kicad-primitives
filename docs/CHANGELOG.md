# Changelog

## Unreleased

- Correct native peer-lock naming to `~<full-original-filename>.lck`. Guard actual project/root/PCB/strict child paths and reject lock presence before source/history writes, including newly appearing locks after partial saves. Remove implicit `pcbnew` importability as a filesystem-save bypass while keeping read/ERC access and explicit helper assertions (#56).

- Preserve latest explicit restore provenance across late exact-revert edits while a frozen Project save advances its baseline. Protect known newer concurrent ZIP history during retention instead of deleting another root's completed snapshot (#56).

- Add strict complete Project file-set persistence, raw PCB freshness, current-state save decisions, and terminal zero-write discard/close guards on owned handles. Prebuild complete native-allowlisted ZIPs from frozen post-save bytes, publish after selected writes, preserve same-second history and latest snapshots under a soft size budget, and report partial-I/O/retry limits. Selected document saves archive saved sibling baselines, not pending edits. Replace regex Sheetfile discovery with the selected structural parser. Project save-as remains the next phase; Git `.history` is deferred (`docs/projects.md`; #55, #56).

- Reject same-inode, same-byte backup rewrites after publication. Compare staged data facts captured before linking or replacing, rather than adopting a concurrent `.bak` version for recovery (#54).

- Add independent SymbolLibrary save-as and current-state close decisions. Discard is terminal and invalidates editable handles. Changed overwrites create native `Foo.bak` backups with safe failure recovery. Guard closed-parent copy/restore while retaining captured restore intent. Record the accepted lifecycle in ADR 0008, AGENTS, and CONTEXT. Project backup/history and multi-file save-as remain pending the owner's backend choice (`docs/symbol-libraries.md`; #54).

- Add physical `LibraryTable` and live `TableEntry` nouns. Buffer localized registration edits, expose pending nested resolution, remove `apply`/dry-run commands, and add explicit single-file save/save-as plus terminal discard/close with current-decision checks. Preserve full raw rows and flags (`docs/tables.md`; #54).

- Expose stable source-backed Symbol, SymbolBody, and SymbolPin objects. Move declared attribute upsert, body/pin edits, and graphics insertion onto those nouns without library-command aliases. Preserve authoring, inheritance inspection, source-local edits, and deleted-handle rejection (`docs/symbol-libraries.md`; #54).

- Fix public table resolution to replay repeated includes in order and detect cycles only on the active branch. Resolve relative includes and leaves from the project directory or a captured standalone base. Share URI resolution with native ERC projection without losing raw registration metadata (`docs/tables.md`; #52).

- Require proof of all requested native ERC severities. Replay repeated nested-table includes in order, and anchor relative include/leaf URIs to the original project's explicit native working directory. Preserve strict cycle and acquisition failures (#40).

- Add `Project.erc()` typed per-sheet reports over pending hierarchy snapshots. Preserve item coordinates/UUIDs, severities/exclusions, check metadata, and original-path/hash provenance. Project native symbol/footprint registrations with raw metadata and original-context paths. Reject report acquisition/context failures explicitly. Document-only ERC remains unsupported (`docs/schematics.md`, `docs/projects.md`; #40).

- Reject cross-cache placement reference ambiguity and unqualified type-correction identities before a restore changes pending source (#37).

- Add stable `EmbeddedSymbol` objects and selected concrete `restore_from` in memory. Preserve placement source and unrelated cache definitions. Support bounded ordinary pin-type corrections with baseline-derived electrical predictions and full exported pin-inventory checks at explicit save. Inheritance, pin names, geometry, hidden/power edits, and ambiguous proof mappings fail explicitly (`docs/schematics.md`; #37).

- Reject duplicate mandatory schematic attributes at intake. Validate raw electrical evidence without collapsing duplicate component references, and preflight all changed destination-directory permissions before replacing any source (#36).

- Add source-backed `PlacedSymbol.set_attribute`: create, localized update, exact no-op, and explicit ambiguity/unsafe-edit failures. Project-owned document and symbol identity retain pending edits across accesses. Add `is_modified`, byte previews, and explicit same-location schematic/project saves with strict source/guard preflight and staged-hierarchy electrical verification. Document bounded lifecycle and staging limits (`docs/schematics.md`, `docs/projects.md`; #36).

- Record the artifact-object library model in ADR 0008: focused in-memory edits, client-owned workflows, observable changes, and explicit persistence choices. Schematic object editing now implements a bounded part of that direction.

- Rename symbol and placed-symbol APIs directly to the canonical Attribute vocabulary: `SymbolAttribute`, `PlacedAttribute`, `attributes`, `attribute()`, `AmbiguousAttributeError`, and `SymbolLibrary.set_attribute` / `add_attribute` / `delete_attribute`. No old-name aliases remain. Behavior and KiCad `(property …)` syntax stay unchanged (`docs/symbol-libraries.md`, `docs/schematics.md`).
- Lock KiCad domain vocabulary in `CONTEXT.md`: flags, attributes, settings, text variables, title-block fields, drawing-sheet fields, and reference annotation.

- Add `kicad_primitives.netlist`: parse kicadsexpr `.net` exchange files, `connectivity_sets` compare helper, and obtain/export via private ADR 0007 `kicad-cli` discovery—distinct from project-owned Connectivity (`docs/netlist.md`; #33).
- Enable cross-library `SymbolLibrary.copy_symbol_from` (declared definition + body rename; `extends` parent must already exist in the destination) (`docs/symbol-libraries.md`).
- Add `kicad_primitives.tables.LibraryTables`: global/project symbol and footprint table discover/read/resolve/write with `${VAR}` expansion, nested `Table` rows, project-over-global nickname resolve, and localized add/remove/rename (`docs/tables.md`; #32).
- Add same-library symbol `create_symbol` / `rename_symbol` / `delete_symbol` / `copy_symbol`; cross-library `copy_symbol_from` fails explicitly until library tables (#38).
- Add symbol graphics B anchors: `ensure_body`, `add_rectangle`, `add_body_text`, body rectangle/text inspection, and `export_svgs` via private ADR 0007 `kicad-cli` discovery—prefer unit-0 shared artwork over copying into every unit (`docs/symbol-libraries.md`; #31).
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
