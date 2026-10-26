# Schematics: placed symbols, title block, and geometry

## Vocabulary

Symbol **attributes** are named values such as Reference, Value, Footprint, and MPN.
Symbol **flags** control behavior, such as DNP and exclusion from BOM or simulation.
**Reference annotation** assigns or updates reference designators and associated instance records.
It does not mean general attribute editing.

The existing read API uses `PlacedProperty`, `properties`, and `property()`.
These names remain available. They describe attributes in the package vocabulary.
KiCad stores these attributes in `(property …)` nodes.
The glossary in `CONTEXT.md` defines settings, text variables, and drawing-sheet terminology.

## Scope

`Project.schematic()` and `Project.schematics()` open schematic **content** inside
project context (ADR 0002).
They return `kicad_primitives.schematics.Schematic` snapshots: title block and
**merged** placed symbols (fields, identity, transform, unit, flags).
Placed-symbol and geometry structure are read-only. Field edit and embedded
restore remain later tickets.

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

## Placed symbols

```python
for symbol in root.symbols:
    print(symbol.reference, symbol.lib_id, symbol.uuid)
    print(symbol.x, symbol.y, symbol.rotation, symbol.mirror, symbol.unit)
    print(symbol.value, symbol.footprint, symbol.in_bom, symbol.dnp)

j22 = root.symbol("J22")
print(j22.property("MPN").value)
```

Only **top-level** `(symbol …)` nodes with `lib_id`, `at`, and a non-empty
`Reference` count as placements.
Definitions under `(lib_symbols …)` are not placements.
Power symbols and DNP parts are included; BOM filtering stays a consumer policy.

`symbol(reference)` raises `KeyError` if missing and `AmbiguousPlacedSymbolError`
if several instances share the reference on that sheet.

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

- Read-only. No localized field annotate and no geometry edit on this surface.
- Embedded `lib_symbols` restore is later work.
- Sheet instance path / multi-instance models are not first-class here.
- Prefer `Project.schematic` over free `open_schematic` in application code.

## Errors

- `InvalidSchematicError`: bad path, syntax, or required structure.
- `AmbiguousPlacedSymbolError`: non-unique reference (or property) lookup.
- `InvalidProjectError`: project-context open rules (no root sheet; path not in hierarchy).

## Tests

Donor gates from jBOM schematic/title-block tests and Subdivision placement
fields are ported in `tests/functional/test_schematic_placed_symbols.py`.
Geometry gates live in `tests/functional/test_schematic_geometry.py`.

```bash
uv run python -m unittest discover -s tests -q
```
