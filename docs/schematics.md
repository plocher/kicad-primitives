# Schematics: the document, sheet files, edits, save, and revert

## Vocabulary

A **schematic** is the project's set of sheet trees (KiCad `SCHEMATIC`).
A **sheet file** is one `.kicad_sch` file (KiCad `SCH_SCREEN`). Content edits to it reach every instance of it.
A **sheet symbol** is the box on a parent sheet file that points at a target sheet file (KiCad `SCH_SHEET`).
A **sheet instance** is one placement in the hierarchy, identified by its UUID path (KiCad `SCH_SHEET_PATH`). Instance models are [#79](https://github.com/plocher/kicad-primitives/issues/79) work.
Symbol **attributes** are named values such as Reference, Value, Footprint, and MPN.
Symbol **flags** control behavior, such as DNP and exclusion from BOM or simulation.
**Reference annotation** assigns reference designators. It does not mean general attribute editing.
`CONTEXT.md` holds the full glossary.

## Scope

[ADR 0011](adr/0011-schematic-document-model-save-and-revert.md) defines two layers here:

- **Layer 0:** `SheetFile` is one file with the full lifecycle: open, read, modify, validate, save, revert, discard, and close. It knows nothing about the hierarchy, so it cannot keep a parent sheet symbol's pins matched with its hierarchical labels.
- **Layer 1:** `Schematic` joins the sheet files of a project. Its `save()` applies the write set and failure policy below over the sheet-file saves. Its `revert()` reloads the whole hierarchy.

Placed symbols support localized attribute edits in memory. Embedded definitions can be replaced from a library.
No save runs KiCad, makes a backup, checks a lock, or verifies connectivity. A client that cares compares `project.netlist()` before and after an edit ([netlist.md](netlist.md)).
`Project.erc()` and `Project.export_svgs()` work on the pending full-project snapshot without saving it.

## Surface (ADR 0006 A)

- **Supported:** `Project.schematic()`; `Schematic.files`, `root_files`, `file(path)`, `save()`, `validate()`, `revert()`; `SheetFile.open()` and its lifecycle; merged placed-symbol read; title block; geometry and electrical-structure read; `PlacedSymbol.set_attribute` and custom `delete_attribute`; `EmbeddedSymbol.update_from_library`; project-scope ERC and SVG export.
- **Defined, explicit failure:** a differing Reference (reference annotation); flag names; mandatory-attribute deletion; power-symbol Value changes; document-only `SheetFile.erc()`; edits to formats other than `20260306`; inherited or structurally different library definitions in `update_from_library`; `close()` or `discard()` on one project-owned sheet file ([#78](https://github.com/plocher/kicad-primitives/issues/78)).
- **Deferred:** sheet instances, per-instance data, and sheet-symbol edits (#79); reference annotation and flag editing; geometry editing; SVG plot options.

## Open

```python
from kicad_primitives.projects import Project
from kicad_primitives.schematics import SheetFile

project = Project.open("/path/to/board")
schematic = project.schematic()          # every sheet tree, loaded once
for sheet_file in schematic.files:       # each tree depth-first, roots first
    print(sheet_file.path, sheet_file.version)
root = schematic.root_files[0]
child = schematic.file("/path/to/board/sub/child.kicad_sch")  # KeyError for outsiders

one = SheetFile.open("/path/to/any.kicad_sch")  # layer 0, outside a project
```

`Project.schematic()` loads every sheet file reachable from the root sheet files.
A file that several sheet symbols use loads once, as one `SheetFile`.
Each `Sheetfile` resolves relative to its parent sheet's directory.
A missing sheet file raises `InvalidSchematicError`. A cycle or a `${...}` Sheetfile raises `UnsupportedSchematicOperationError`.
Repeated access returns the same objects. Retained handles observe pending edits.

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
if several instances share the reference on that sheet file.
This per-file reference lookup is documented debt; #79 replaces it with instance lookups.

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
Other attributes can affect electrical names through substitutions. Save does not check this; compare netlists when it matters.

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
The client owns alias maps and conflict policy, for example when alias and canonical values differ.

## Update one embedded definition from a library

```python
from kicad_primitives.symbols import SymbolLibrary

for definition in root.embedded_symbols:
    print(definition.lib_id)

embedded = root.embedded_symbol("Device:R")
library = SymbolLibrary.open("/path/to/Device.kicad_sym")
embedded.update_from_library(library, "R")
preview = root.to_bytes()
```

Clients select the embedded definition and the opened library. [Library tables](tables.md) can locate it.
The package does not select libraries or synchronize the whole cache.
`embedded_symbols` follows source order with stable handles. `embedded_symbol(lib_id)` raises `KeyError` for a missing identity.
Missing or duplicate cache containers and duplicate identities fail explicitly.

`update_from_library(library, name)` replaces the whole embedded definition with the library definition, in memory.
It adapts only the outer identity and the nested body-name prefix: for `Lib:Part`, bodies are `Part_unit_style`.
Other library source stays exact, including opaque payloads and quoted multiline strings. Nothing is reindented.
Placements, attributes, flags, UUIDs, instances, and unrelated definitions stay unchanged. Existing handles stay valid.
An identical replacement is a byte no-op. The operation never runs KiCad or writes a file.

Pin electrical types can change: this is a plain in-memory edit, with no prediction and no proof.
The library must use format `20251024` and the sheet file `20260306`.
These changes are not supported yet and fail before any change: `extends` inheritance; added, removed, or renumbered pins; changed pin names, positions, lengths, visibility, or alternates; changed unknown definition content.

## Save

```python
sheet_file.save()        # layer 0: this file only
schematic.save()         # layer 1: every changed sheet file
project.save()           # every changed document the project owns
schematic.save(overwrite=True)   # the explicit way through a conflict
```

**Layer 0.** `SheetFile.save()` writes only that file when it has unsaved changes. A clean save writes nothing.
It runs `validate()`, then replaces the file atomically and keeps its permission bits.
If the disk file is not the file that was read (its fingerprint does not match), it raises `SchematicConflictError` and writes nothing, unless `overwrite=True`.

**Layer 1.** `Schematic.save()` writes only the sheet files that have unsaved changes and touches no others: no rewrite, no time change.
This is a deliberate deviation from KiCad, which rewrites every sheet file. A byte-preserving writer gains nothing from it.
Child sheet files are written before their parents. Written files become saved; all others keep their changes.
The failure policy (ADR 0011 D4):

- Invalid content or a read-only format, found by `validate()` before any write: nothing is written.
- A file that is not a regular, unlinked, writable file, or a directory that is not writable, found before any write: nothing is written.
- A conflict, checked before any write and again before each replace: that file stays unsaved and is never retried or overwritten.
- A permission change during a write: reported, not retried.
- A short-lived system error (interrupted, busy, timed out): the save continues; at the end it retries that file once after a fixed short wait, after a new conflict check.
- A lasting or unknown system error (disk full, read-only volume, I/O error): the save stops at once.

When not every changed file is written, `SchematicSaveError` lists each changed file as `written`, `conflict`, `failed`, or `unsaved`, with the reason.
A later save writes only what is still unsaved. `Schematic.validate()` runs the content checks without a write.

Only format `20260306` supports edits. Do not confuse it with symbol-library format `20251024`.
`is_modified` is a flag that edits set (ADR 0009). An edit back to the original content leaves it set.
The package keeps no in-memory copy of what it read. A fingerprint detects conflicts: size, a stat stamp (device, inode, modification time), and a content hash. A check stats the file first. A different size is a change; the same size and stamp are no change; only otherwise is the file read and hashed, so a touched but identical file is no conflict.

## Revert

```python
sheet_file.revert()      # this file
schematic.revert()       # the whole hierarchy
```

Revert drops unsaved changes and reloads from disk. The object keeps its identity and `is_modified` becomes false.
Placed-symbol and embedded-symbol handles taken before the revert become stale: their edits raise. Get fresh ones.
Revert reads the disk, so it can fail: a missing file or a fingerprint mismatch raises `SchematicConflictError` and changes nothing.
`Schematic.revert()` checks every sheet file first, then reloads each one and walks the trees again.

## Close and discard

A standalone `SheetFile` has `close()` (save when changed, then end), `discard()` (end without writing), and `with` support.
A project-owned sheet file ends with its project. Its own `close()` and `discard()` raise `UnsupportedSchematicOperationError` until #78 decides.
Use `project.close()` or `project.discard()` ([projects.md](projects.md#close-discard-and-with)).

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
for sheet_symbol in root.sheet_symbols:
    print(sheet_symbol.name, sheet_symbol.filename, sheet_symbol.x, sheet_symbol.y)
```

Wires keep polyline points in file order. Each `SheetSymbol` exposes `Sheetname`,
`Sheetfile`, and the box rectangle. Open child content through `Schematic.files`
or `Schematic.file(path)`, not a second walker.

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
It does not save source or clear pending changes. Locked projects and read-only original files remain checkable.
The backend writes only temporary snapshot/report files.

`SheetFile.erc()` explicitly raises `UnsupportedSchematicOperationError`.
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

## SVG export

```python
result = project.export_svgs("/path/to/new-svg-dir")  # optional kicad_cli=
for svg in result.files:
    print(svg.path, svg.sheet_path, svg.source_path)
root_page = next(f for f in result.files if f.sheet_path == "/")
```

`Project.export_svgs(output_dir)` renders the full hierarchy, including every document's pending `to_bytes()` content.
It uses the same private staging as `Project.erc()` and `Project.netlist()`.
It does not save source or clear pending changes.
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

- No reference annotation, flag editing, mandatory-attribute deletion, geometry editing, or sheet-symbol editing.
- No instance model yet: `SheetFile.symbol(reference)` is per file (#79).
- `update_from_library` supports structurally equal concrete definitions only.
- No save checks connectivity, locks, or backups; those are client sequences.
- ERC, netlist, and SVG staging need the root sheet file and project to share a basename, and support parent-relative sheets inside the project directory only.
- No automatic KiCad resave or whole-file normalization occurs.

## Errors

- `InvalidSchematicError`: bad path, syntax, required structure, or a missing sheet file.
- `AmbiguousPlacedSymbolError`: non-unique reference or attribute lookup.
- `AmbiguousEmbeddedSymbolError`: duplicate cache containers, identities, or pin occurrences.
- `UnsupportedSchematicOperationError`: unsupported format, identity, edit, hierarchy, or staging case; stale handles.
- `SchematicConflictError`: the disk file is not the file that was read, or it is missing.
- `SchematicSaveError`: `Schematic.save()` or `validate()` did not pass every changed sheet file; see `results`.
- `SchematicLifecycleError`: a closed or discarded standalone sheet file.
- `ProjectLifecycleError`: the owning project exited.
- Library lookup and lifecycle errors propagate from `update_from_library`.
- `ErcAcquisitionError`, `ErcContextError`, `SchematicSvgError`: ERC or SVG acquisition failed.
- `KicadCliNotFoundError` and ordinary filesystem errors propagate.

## Tests

Donor gates from jBOM schematic/title-block tests and Subdivision placement fields: `tests/functional/test_schematic_placed_symbols.py`.
Geometry: `test_schematic_geometry.py`. Edits: `test_schematic_editing.py` and `test_schematic_attribute_deletion.py` (jBOM alias normalization as client code).
Layer-0 lifecycle: `test_sheet_file_lifecycle.py`. Layer-1 save policy: `test_schematic_persistence.py`. Revert and `on_close`: `test_project_lifecycle.py`.
Library updates: `test_schematic_restore.py`. ERC: `test_schematic_erc.py`. SVG: `test_schematic_svg_export.py`.
Fixture provenance is in `tests/fixtures/schematics/*/PROVENANCE.txt`. These tests need no KiCad installation.

```bash
uv run python -m unittest discover -s tests -q
```

Opt-in real KiCad gates use disposable fixture copies:

```bash
uv run python tests/verify_schematic_editing.py --kicad-cli /path/to/kicad-cli
uv run python tests/verify_schematic_restore.py --kicad-cli /path/to/kicad-cli
uv run python tests/verify_schematic_erc.py --kicad-cli /path/to/kicad-cli
uv run python tests/verify_schematic_svg.py --kicad-cli /path/to/kicad-cli
```

The editing gate checks that attribute edits leave `project.netlist()` equal, then saves.
The restore gate checks exact source recovery and that the pin-type correction changes the exported pin types.
