# Schematics: placed attributes, explicit saves, and geometry

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
Geometry and embedded definition edits remain unsupported.

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
Unchanged saves preserve bytes and do not replace files or invoke KiCad.

Before writing, save checks the project guard, project settings baseline, and every reachable schematic baseline.
It requires regular, non-symlink, singly linked files.
Changed files must have write permission bits. Replacement preserves their permission bits.
An external edit or deletion fails rather than overwriting or recreating a file.

Verification stages only the complete schematic hierarchy and the opened `.kicad_pro` bytes.
It exports the root before and after pending changes, at the same staged location.
Comparison retains net names, singleton and empty nets, duplicate occurrences, and all pin attachments.
Pin attachments include reference, pin, pin function, and electrical type.
Component reference, library identity, and sheet path must remain unchanged.
Value and custom attributes may change. Reparsing establishes their required source deltas.
Net codes and export order do not define electrical identity.
This is connectivity verification, not ERC or simulation.

`root.save()` stages only that document's pending changes.
Other documents remain pending and contribute their saved baselines.
`project.save()` stages all changed owned documents together.
The package checks all inputs again after verification and before persistence.
Known preflight failures stop before any original file changes.
Files then save separately. A later I/O failure can leave earlier files saved.
This is not a crash-atomic multi-file transaction or coordination with another writer.
An unsuccessful document retains pending changes for inspection and retry.
The final check/replace race remains possible.

No mutation, finalizer, or close action implicitly saves.
Save-as relocation and general close/discard/session interfaces are not implemented.
To abandon pending work, stop using its project and documents and open a new project.

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

## Limits

- No reference annotation, flag editing, attribute deletion, or geometry editing.
- Embedded `lib_symbols` restore is later work.
- Sheet instance path / multi-instance models are not first-class here.
- Prefer `Project.schematic` over free `open_schematic` in application code.
- Same-location saves require the root schematic and project to share a basename.
- Save verification supports parent-relative sheets only within the project directory.
- Absolute, variable-based, external, cyclic, missing, or symlink sheet paths fail explicitly.
- Verification does not copy arbitrary project trees, external resources, or library tables.
- No automatic KiCad resave or whole-file normalization occurs.

## Errors

- `InvalidSchematicError`: bad path, syntax, or required structure.
- `AmbiguousPlacedSymbolError`: non-unique reference (or attribute) lookup.
- `UnsupportedSchematicOperationError`: unsupported format, identity, edit, or safe staging case.
- `SchematicConflictError`: changed or missing source or project verification context.
- `SchematicVerificationError`: pending content changes the electrical signature.
- `InvalidProjectError`: project-context open rules (no root sheet; path not in hierarchy).
- `ProjectWriteBlockedError`: the project write guard blocks persistence.
- `KicadCliNotFoundError`, netlist export/parse errors, and ordinary filesystem errors propagate from explicit saves.

## Tests

Donor gates from jBOM schematic/title-block tests and Subdivision placement
fields are ported in `tests/functional/test_schematic_placed_symbols.py`.
Geometry gates live in `tests/functional/test_schematic_geometry.py`.
Object editing and persistence gates live in `test_schematic_editing.py` and `test_schematic_persistence.py`.
The native fixture provenance is in `tests/fixtures/schematics/attribute-edit/PROVENANCE.txt`.
These tests need no KiCad installation. The verifier test double exercises failure paths through an executable boundary.

```bash
uv run python -m unittest discover -s tests -q
```

An opt-in real KiCad gate edits only disposable fixture copies:

```bash
uv run python tests/verify_schematic_editing.py --kicad-cli /path/to/kicad-cli
```

This checks fresh exported Value and inserted attributes, six singleton nets, byte previews, explicit persistence, and no-op saves.
