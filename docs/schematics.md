# Schematics: attributes, embedded restore, explicit saves, and geometry

## Vocabulary

Symbol **attributes** are named values such as Reference, Value, Footprint, and MPN.
Symbol **flags** control behavior, such as DNP and exclusion from BOM or simulation.
**Reference annotation** assigns or updates reference designators and associated instance records.
It does not mean general attribute editing.

KiCad stores these attributes in `(property …)` nodes.
The glossary in `CONTEXT.md` defines settings, text variables, and drawing-sheet terminology.

## Scope

[ADR 0008](adr/0008-artifact-objects-and-explicit-persistence.md) selects artifact-owned editable objects and explicit persistence.
Placed symbols support localized attribute edits in memory.
The schematic owns their source and exposes pending changes, byte previews, and explicit same-location saves.

`Project.schematic()` and `Project.schematics()` open schematic **content** inside
project context (ADR 0002).
They return owned `kicad_primitives.schematics.Schematic` documents: title block and
**merged** placed symbols (attributes, identity, transform, unit, flags).
Selected concrete embedded definitions support source-backed restore.
Geometry editing and general cache synchronization remain unsupported.
`Project.erc()` checks a pending full-project snapshot and returns typed per-sheet reports.
`Project.export_svgs()` writes SVGs of the same pending snapshot to a new directory.

## Surface (ADR 0006 A)

- **Supported:** merged placed-symbol read; title block; geometry and electrical-structure read; `PlacedSymbol.set_attribute` and custom `delete_attribute`; selected concrete embedded restore; explicit save with electrical verification; project-scope ERC and SVG export.
- **Defined, explicit failure:** a differing Reference (reference annotation); flag names; mandatory-attribute deletion; power-symbol Value changes; document-only `Schematic.erc()`; `extends` materialization on restore; restore electrical changes outside the proved pin-type depth; edits to formats other than `20260306`.
- **Deferred past 1.0:** reference annotation and flag editing as operations; geometry editing; general embedded-cache synchronization; multi-instance sheet models; SVG plot options and drawing-sheet staging.

## Open via a project

```python
from kicad_primitives.projects import Project

project = Project.open("/path/to/board")
root = project.schematic()                 # root .kicad_sch
for sheet in project.schematics():         # hierarchy walk order
    print(sheet.path, sheet.version)
```

An explicit path must belong to `project.schematic_files()`.
Outsiders raise `InvalidProjectError`.
Missing root schematic raises `InvalidProjectError`.

Prefer these accessors over `schematics.open_schematic` in application code.
The free function exists for already-validated hierarchy paths and tests.
It does not supply the project context required by `save()`.
Repeated project accesses reuse the same owned documents and placed-symbol handles.
Previously obtained handles observe pending attribute edits.

## Placed symbols

`PlacedAttribute` holds one named value. `PlacedSymbol.attributes` keeps occurrences in file order.
`attribute(name)` returns one occurrence and raises `KeyError` if absent.
It raises `AmbiguousPlacedSymbolError` if ambiguous.

```python
for symbol in root.symbols:
    print(symbol.reference, symbol.lib_id, symbol.uuid)
    print(symbol.x, symbol.y, symbol.rotation, symbol.mirror, symbol.unit)
    print(symbol.value, symbol.footprint, symbol.in_bom, symbol.dnp)

j22 = root.symbol("J22")
print(j22.attribute("MPN").value)
```

Only **top-level** `(symbol …)` nodes with `lib_id`, `at`, and a non-empty
`Reference` count as placements.
Definitions under `(lib_symbols …)` are not placements.
Power symbols and DNP parts are included; BOM filtering stays a consumer policy.

`symbol(reference)` raises `KeyError` if missing and `AmbiguousPlacedSymbolError`
if several instances share the reference on that sheet.

## Edit attributes in memory

```python
symbol = root.symbol("J22")  # clients select targets
symbol.set_attribute("Value", "New value")
symbol.set_attribute("MPN", "ABC-2")  # create if missing
print(symbol.attribute("MPN").value)  # retained handles see the change
print(root.is_modified, project.is_modified)
preview = root.to_bytes()
```

`set_attribute(name, value)` creates a missing attribute and updates a differing value.
An equal value is an exact byte no-op.
The setter rejects ambiguous attributes or symbol UUIDs.
Editing requires a nonempty, unique placed-symbol UUID.
Mandatory names use KiCad's case-insensitive identity. Custom names are case-sensitive.
Duplicate mandatory attributes fail when the schematic opens, rather than supplying first-wins convenience values.
Repeated custom attributes remain in `attributes`. Their named lookup and mutation reject ambiguity.
Names must be nonempty strings. Values must be strings. Neither may contain NUL.
Empty values are valid.

Updates replace only the value token and preserve existing presentation.
New attributes use a hidden 1.27 mm font at the symbol position.
Other source, including cached definitions, flags, instances, UUIDs, and opaque nodes, stays unchanged.
Each successful edit reparses the source before another edit.
The setter never writes files or runs KiCad.

A differing Reference requires reference annotation and fails explicitly.
An equal Reference is a no-op.
Flags are not attributes. The setter rejects flag names such as `dnp` and `in_bom`.
Power-symbol Value changes are electrical edits and fail explicitly.
Other attributes can affect electrical names through substitutions. Save verification rejects such changes.

## Delete attributes in memory

```python
symbol = root.symbol("R3")
# Client-owned alias normalization (jBOM style): set canonical, delete alias.
if "W" in {a.name for a in symbol.attributes}:
    symbol.set_attribute("Power", symbol.attribute("W").value)
    symbol.delete_attribute("W")
project.save()
```

`delete_attribute(name)` removes one custom attribute.
It removes only the selected `(property …)` node and its leading separator. Other bytes stay unchanged.
A missing name raises `KeyError`. A repeated custom name raises `AmbiguousPlacedSymbolError`.
Custom names are case-sensitive.
Mandatory attributes (Reference, Value, Footprint, Datasheet, Description) are not deletable.
Flag names such as `dnp` and `in_bom` are not attributes.
Both raise `UnsupportedSchematicOperationError`.
The same format and placed-symbol UUID rules as `set_attribute` apply.
Retained handles observe the deletion. The operation never writes files or runs KiCad.
Explicit save proves unchanged connectivity, as for other attribute edits.
The client owns alias maps and conflict policy, for example when alias and canonical values differ.

## Restore one embedded definition

```python
from kicad_primitives.symbols import SymbolLibrary

for definition in root.embedded_symbols:
    print(definition.lib_id)

embedded = root.embedded_symbol("Device:R")
parent = SymbolLibrary.open("/path/to/Device.kicad_sym")
embedded.restore_from(parent, "R")
preview = root.to_bytes()
# Later, when the client chooses:
root.save()
```

Clients select the cache object and opened parent library.
Existing [library tables and resolution](tables.md) can locate that library.
The package does not select parents or run a cache-wide synchronization workflow.
`embedded_symbols` follows source order and keeps stable `EmbeddedSymbol` handles.
`embedded_symbol(lib_id)` raises `KeyError` for a missing identity.
Missing or duplicate cache containers and duplicate cache identities fail explicitly.

`restore_from(parent_library, parent_name)` captures the current concrete parent source.
Later parent edits cannot change that pending restore.
It replaces the whole selected definition, including supported graphics and default attributes.
It adapts only the outer cache identity and the required nested body-name prefix.
For cache `Lib:Part`, nested names use `Part_unit_style`, not `Lib:Part_unit_style`.
Other parent source stays exact, including opaque payloads and quoted multiline strings.
The implementation does not reindent or serialize the parent.
Source outside the selected definition stays byte-identical.
All placed symbols, attributes, flags, UUIDs, instances, and unrelated definitions remain unchanged.
Reparsing keeps existing placed and embedded handles valid.
Exact materialized equality and repeated identical restores are byte no-ops.
Restore never runs KiCad or writes a file.

### Supported electrical depth

Parents must be concrete and use symbol-library format `20251024`.
`extends` materialization is unsupported. Typed inheritance inspection is not a source-complete parent serializer.
The schematic must use format `20260306`.

Restore inventories every source pin occurrence by unit, body style, and number.
Pin names, numbers, connection points, length, shape, visibility, alternates, and opaque pin structure must remain unchanged.
Power behavior, jumpers, and unknown electrical definition content must remain unchanged.
Changed unknown content fails explicitly rather than being discarded or copied without a proof.
Body graphics and default attributes can change without changing those pin facts.

Visible ordinary non-power pin electrical types can change under the explicit-save proof below.
This includes the proven output/input-to-passive repair.
Changed power types, hidden or alternate pin types, pin additions, deletions, moves, and renumbering are unsupported.
Pin-name edits are unsupported because generated net names can depend on pin names.
Type corrections require unique pin numbers, simple unit/body mapping, and unique normal placement references.
Affected references must be unique across all placements in the document, not only the selected cache.
Type correction also requires a qualified `Lib:Part` cache identity before mutation.
Multi-unit, alternate-body, DNP, excluded, or unobservable placement corrections fail explicitly.
These are bounded implementation limits, not complete donor parity or general electrical editing.

## Save explicitly

```python
root.save()       # save this schematic only
project.save()    # save all changed owned schematics
# Both also accept kicad_cli="/explicit/path/to/kicad-cli".
```

Only schematic format `20260306` supports edits. Older and future formats remain read-only.
Do not confuse this with symbol-library format `20251024`.
Changed saves require working KiCad netlist export. CLI discovery follows ADR 0007.
There is no unchecked-save flag.
Unchanged source saves preserve bytes and do not replace files or invoke KiCad.
An explicit save still requests the owning Project's complete ZIP snapshot safety net.

Before writing, save checks the project guard, project settings baseline, and every reachable schematic baseline.
It requires regular, non-symlink, singly linked files.
Changed files must have write permission bits. Replacement preserves their permission bits.
All changed destination directories must permit file creation and search before the first replacement.
An external edit or deletion fails rather than overwriting or recreating a file.

Verification stages only the complete schematic hierarchy and the opened `.kicad_pro` bytes.
It exports the root before and after pending changes, at the same staged location.
Comparison retains net names, singleton and empty nets, duplicate occurrences, and all pin attachments.
Pin attachments include reference, pin, pin function, and electrical type.
Component reference, library identity, and sheet path must remain unchanged.
Verification validates raw export structure and component identity before comparison.
Missing required evidence sections, duplicate component references, and incomplete pin attachments fail explicitly.
Value and custom attributes may change. Reparsing establishes their required source deltas.
Net codes and export order do not define electrical identity.
This is connectivity verification, not ERC or simulation.

For a restore, save also checks the complete exported `libparts` pin inventory.
This includes pins that have no connected peer.
It predicts the expected electrical signature from the baseline export and captured parent pin-type facts.
The prediction changes only requested type effects on every matching placement in the selected document.
Every net name, pin function, endpoint occurrence, component identity, and unrelated pin type must stay unchanged.
The actual pending hierarchy export must equal that prediction.
Missing requested effects and unrelated electrical drift both fail.
Save does not export a replay of the replacement to manufacture its expected result.
It does not ignore selected references or provide an allow-electrical-change bypass.

Type proof requires directly observable source-to-export mapping and complete baseline evidence.
Every corrected placement pin needs exactly one exported occurrence.
Conflicting sheet-local definitions with the same library identity can make global `libparts` evidence ambiguous.
Such cases fail explicitly rather than treating one global definition as proof for every sheet.
Attribute-only saves retain their unchanged-electrical contract.
Mixed attribute and restore edits use the same explicit persistence safeguards.

`root.save()` stages only that document's pending changes.
Other documents remain pending and contribute their saved baselines.
`project.save()` stages all changed owned documents together.
Both operations publish exact post-save Project ZIP history after their selected source files succeed.
Unselected pending sibling source is not archived as if saved.
The package checks all inputs again after verification and before persistence.
Known preflight failures stop before any original file changes.
Files then save separately. A later I/O failure can leave earlier files saved.
This is not a crash-atomic multi-file transaction or coordination with another writer.
An unsuccessful document retains pending changes for inspection and retry.
The latest explicit restore selection survives an exact old-baseline revert during an older frozen save.
If that save advances the baseline, retry proves the requested reverse correction against the bytes actually persisted.
The final check/replace race remains possible.

No mutation, finalizer, or discard action saves.
Use `project.discard()` for terminal zero-write exit, not reload or rollback.
`project.close()` writes nothing when clean and runs a full `project.save()` when dirty.
Owned document/placed/embedded operations fail after Project exit.
Bounded Project save-as retains these document/placed/embedded identities while rebinding their paths after complete success.
ZIP history, budgets, and partial-I/O limits are defined in [projects.md](projects.md#zip-snapshots).

## Title block

```python
tb = root.title_block
print(tb.title, tb.revision, tb.date, tb.company)
print(dict(tb.comments))  # keys 1..9 when present; empty string values kept
```

Missing title blocks yield empty strings and an empty comments map.

## Geometry and electrical structure

```python
for wire in root.wires:
    print(wire.points, wire.uuid)
for j in root.junctions:
    print(j.x, j.y)
for lab in root.labels:
    print(lab.text, lab.x, lab.y, lab.rotation)
for g in root.global_labels:
    print(g.text, g.shape)
for h in root.hierarchical_labels:
    print(h.text, h.shape)
for nc in root.no_connects:
    print(nc.x, nc.y)
for sheet in root.sheets:
    print(sheet.name, sheet.filename, sheet.x, sheet.y, sheet.width, sheet.height)
```

Wires keep polyline points in file order. Sheet edges expose `Sheetname` /
`Sheetfile` and the sheet rectangle. Child path resolution for opening content
still goes through `Project.schematic_files()` / `Project.schematic(path)`
(parent-relative), not a second walker.

## Electrical rule reports

```python
report = project.erc()  # optional kicad_cli="/explicit/path/to/kicad-cli"
print(report.source_path, report.kicad_version, report.coordinate_units)
for sheet in report.sheets:
    print(sheet.path, sheet.uuid_path, sheet.source_path)
    for finding in sheet.violations:
        print(finding.type, finding.severity, finding.excluded)
        for item in finding.items:
            print(item.uuid, item.description, item.position.x, item.position.y)
```

`Project.erc()` checks the full hierarchy, including every document's pending `to_bytes()` content.
It uses the captured `.kicad_pro` settings, text variables, exclusions, and ignored checks.
It does not save source, clear pending changes, or require the project write guard.
Locked projects and read-only original files remain checkable.
The backend writes only temporary snapshot/report files.

`Schematic.erc()` explicitly raises `UnsupportedSchematicOperationError`.
The current backend cannot honor document-only sheet scope.
The package does not check an isolated child, silently filter a whole-project report, or claim document-only coverage.

### Typed findings and origin

The immutable report values are available from `kicad_primitives.schematics`.
`ErcReport.sheets` keeps `ErcSheet` groups in report order.
Each `ErcViolation` retains its type, description, raw severity, optional excluded flag/comments, and all `ErcItem` values.
`ErcPosition` holds finite numeric coordinates, not formatted strings.
Empty item lists remain legitimate violation-level findings.
Unknown severity strings remain unchanged. Exclusions are not dropped or converted to warnings.
The client owns severity thresholds and application approval policy.

`source` is KiCad's raw basename. `source_path` is the original absolute root schematic path.
Each sheet retains its human `path` and raw `uuid_path`.
The package maps `sheet.source_path` through captured hierarchy UUID chains only.
It returns `None` when it cannot prove that mapping. It never guesses from a leaf filename.
Temporary stage paths are not reported as original source origins.

`ErcSnapshot.project` is the shared `ProjectSnapshot` (also used by `Project.netlist()` and `Project.export_svgs()`).
It records the original project path, captured project-settings SHA-256, and one `SnapshotDocument` per document:
original path, exact checked-content hash, and pending-change state.
`ErcSnapshot` adds the original config home and hashes of the effective symbol and footprint registration snapshots.
The report preserves generation date, KiCad version, coordinate units, included severities, and typed ignored-check metadata.
`stdout` and `stderr` retain backend diagnostics.

### Library context and failure behavior

ERC stages native local symbol and footprint tables from the original project/config context.
It follows project-over-global and source-order precedence.
Repeated nested-table includes apply again in order. Active recursion cycles fail explicitly.
The snapshot represents effective registrations, not parity with native repeated-loader cache diagnostics.
It expands variables from the explicitly selected project's captured settings, not a discovered sibling project.
Both relative table includes and leaf URIs use the original project directory as their common logical native working directory.
The backend receives that CWD explicitly. The package does not change the caller's working directory.
Public `LibraryTables` now uses the same URI resolution and ordered repeated-include rules ([#52](https://github.com/plocher/kicad-primitives/issues/52)).
Its project base is the opened project directory. Standalone resolution captures an explicit base or process CWD.
Only library URI atoms change to absolute original-context `.kicad_sym` or `.pretty` paths.
Whole winning leaf rows retain disabled/hidden flags, options, descriptions, and opaque metadata.
Missing winning libraries remain registered. The package does not remove them or fall back to a global library.
Such missing libraries can produce legitimate KiCad findings.

This context projection supports native `KiCad` rows and unmodified nested `Table` links.
Table format 7 and tables without a version declaration are supported.
Missing/cyclic nested tables, unresolved variables, malformed metadata, nested modifiers, remote URIs, and other plugins fail explicitly.
The package does not copy arbitrary project/config trees, symbol libraries, footprint contents, or 3D assets.
Libraries and footprints remain at their original locations. The report does not coordinate with concurrent external writers.

The current command requests JSON, millimeter coordinates, and all severities.
Report metadata must confirm error, warning, and exclusion coverage. Additional severity tokens remain unchanged.
It uses neither the DRC-only refill option nor an exit-code-on-findings flag.
Only exit status 0 permits report intake.
Every nonzero status is an acquisition error, even if a JSON file exists.
A nonempty diagnostic stream, such as Fontconfig output, does not invalidate a successful, complete report.
Missing, malformed, incomplete, duplicate-key, or invalid-coordinate JSON raises `ErcAcquisitionError`.
It never becomes an empty report or a synthetic warning finding.
The supported report schema is `https://schemas.kicad.org/erc.v1.json`.
ERC findings are not a substitute for the operation-specific save verification above.

## SVG export

```python
result = project.export_svgs("/path/to/new-svg-dir")  # optional kicad_cli=
for svg in result.files:
    print(svg.path, svg.sheet_path, svg.source_path)
root_page = next(f for f in result.files if f.sheet_path == "/")
```

`Project.export_svgs(output_dir)` renders the full hierarchy, including every document's pending `to_bytes()` content.
It uses the same private staging as `Project.erc()`, `Project.netlist()`, and save verification.
It does not save source, clear pending changes, or require the project write guard.
Locked projects and read-only original files remain exportable.

`output_dir` must not exist, even as a symlink. Its parent directories must exist and must not be symlinks.
The destination directory must permit writing. The package does not create parent directories.
An existing or unsafe destination fails before KiCad runs.
KiCad renders into a temporary stage. The package creates `output_dir` exclusively only after a complete, validated render.
A later file-copy failure can leave a partial new directory. It never overwrites an existing file.

`SchematicSvgExport` holds `output_dir`, `files`, the `ProjectSnapshot` provenance (`snapshot`), and backend `stdout`/`stderr`.
Each `SchematicSvgFile` holds the produced `path`, the human `sheet_path` (`"/"` for the root, `"/A/B/"` for nested sheets), and the original `source_path`.
KiCad 10 names each page `<root-stem>-<sheet name>-….svg` from raw sheet names, then replaces `/` and `\` with `_`.
It applies no other file-name sanitizing (`SCHEMATIC::GetUniqueFilenameForCurrentSheet` and `SCH_PLOTTER`, KiCad 10.0.1 source).
The package proves the mapping from that rule and the captured hierarchy. It compares names in Unicode NFC, because macOS can return decomposed (NFD) names.
Only a file that the rule cannot account for keeps `sheet_path=None` and `source_path=None`.
A proved sheet without a produced file raises `SchematicSvgError`.
Two sheets that map to one page name would make KiCad overwrite a page, so that raises `SchematicSvgError` before KiCad runs.

The command is `kicad-cli sch export svg --output <stage> <root>`, run with the original project directory as working directory, like ERC. No plot options are exposed.
Donor use is the full hierarchy (kproj `schematic_exporter`) and a root-only page (`--pages 1`). Select the root entry by `sheet_path == "/"`.
Theme, black-and-white, drawing-sheet, and page-selection options are post-1.0.
The stage holds only the project file and hierarchy schematics. A custom drawing sheet referenced by a relative path is not staged.
A nonzero exit, no SVG output, or an omitted proved sheet raises `SchematicSvgError`. It never becomes an empty result.

## Limits

- No reference annotation, flag editing, mandatory-attribute deletion, or geometry editing.
- Only selected concrete embedded restore is implemented. General cache sync and inherited materialization remain later work.
- Sheet instance path / multi-instance models are not first-class here.
- Prefer `Project.schematic` over free `open_schematic` in application code.
- Same-location saves require the root schematic and project to share a basename.
- Save verification supports parent-relative sheets only within the project directory.
- Absolute, variable-based, external, cyclic, missing, or symlink sheet paths fail explicitly.
- Verification does not copy arbitrary project trees, external resources, or library tables.
- No automatic KiCad resave or whole-file normalization occurs.
- ERC is full-project only and uses the bounded native local reference context described above.
- SVG export is full-project only, has no plot options, and does not stage custom drawing sheets.

## Errors

- `InvalidSchematicError`: bad path, syntax, or required structure.
- `AmbiguousPlacedSymbolError`: non-unique reference (or attribute) lookup.
- `AmbiguousEmbeddedSymbolError`: duplicate cache containers, identities, or pin occurrences.
- `UnsupportedSchematicOperationError`: unsupported format, identity, edit, or safe staging case.
- `SchematicConflictError`: changed or missing source or project verification context.
- `SchematicVerificationError`: pending content does not match its required or predicted electrical signature.
- Parent-library lookup/lifecycle errors propagate for missing or ambiguous definitions and closed/discarded parent libraries.
  A restore intent captured before parent exit remains valid and does not reread that parent at save.
- `InvalidProjectError`: project-context open rules (no root sheet; path not in hierarchy).
- `ProjectWriteBlockedError`: the project write guard blocks persistence.
- `ProjectLifecycleError`: the owning Project exited, or newer pending state changed during a save.
- `ProjectBackupError`: snapshot/save-history failure; some source files may already have been persisted.
- `ErcAcquisitionError`: ERC execution or report intake failed, not a design finding.
- `ErcContextError`: the original library context cannot be staged faithfully.
- `SchematicSvgError`: SVG export execution or output intake failed.
- `FileExistsError` / `FileNotFoundError` / `PermissionError`: SVG output directory exists, lacks a parent, or is not writable.
- `KicadCliNotFoundError`, netlist export/parse errors, and ordinary filesystem errors propagate from explicit saves.

## Tests

Donor gates from jBOM schematic/title-block tests and Subdivision placement
fields are ported in `tests/functional/test_schematic_placed_symbols.py`.
Geometry gates live in `tests/functional/test_schematic_geometry.py`.
Object editing and persistence gates live in `test_schematic_editing.py`, `test_schematic_attribute_deletion.py`, and `test_schematic_persistence.py`.
The deletion tests port jBOM annotate alias normalization (`normalize_schematic_properties`) as client code.
The native fixture provenance is in `tests/fixtures/schematics/attribute-edit/PROVENANCE.txt`.
These tests need no KiCad installation. The verifier test double exercises failure paths through an executable boundary.

```bash
uv run python -m unittest discover -s tests -q
```

An opt-in real KiCad gate edits only disposable fixture copies:

```bash
uv run python tests/verify_schematic_editing.py --kicad-cli /path/to/kicad-cli
```

This checks fresh exported Value and inserted attributes, one alias deletion (`W` to `Power`), six singleton nets, byte previews, explicit persistence, and no-op saves.

Selected-restore gates are in `tests/functional/test_schematic_restore.py`.
Native provenance and independently authored expected pin types are in `tests/fixtures/schematics/embedded-restore/PROVENANCE.txt`.
The native restore gate uses only disposable fixture copies:

```bash
uv run python tests/verify_schematic_restore.py --kicad-cli /path/to/kicad-cli
```

It proves exact source recovery and output/input-to-passive corrections across three placements and six singleton pins.
Expected types come from fixed fixture requirements, not another export of the requested replacement.

ERC scenarios port kproj report and execution behavior through the public report boundary.
`tests/functional/test_schematic_erc.py` covers pending hierarchy, grouping, exclusions, acquisition failures, raw library context, and scope limits.
The native gate uses disposable source/library copies with recorded context provenance:

```bash
uv run python tests/verify_schematic_erc.py --kicad-cli /path/to/kicad-cli
```

It checks actual KiCad 10 JSON, typed findings, original URI resolution, and locked/read-only pending snapshots.

SVG export scenarios port kproj `schematic_exporter` behavior through `Project.export_svgs` with a backend test double.
`tests/functional/test_schematic_svg_export.py` covers pending content, sheet mapping, destination safety, and acquisition failures.
The native gate uses a disposable two-sheet hierarchy copy:

```bash
uv run python tests/verify_schematic_svg.py --kicad-cli /path/to/kicad-cli
```

It checks KiCad file names, root/child mapping, a non-ASCII sheet name with `/`, a rendered pending Value, unchanged sources, and existing-output refusal.
Finding totals depend on the original reference context. The gate does not filter legitimate missing-footprint findings.
