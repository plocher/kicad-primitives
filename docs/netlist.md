# Connectivity: project netlist obtain and netlist exchange

## Scope

`kicad_primitives.netlist` reads and obtains KiCad **kicadsexpr** netlist
files (`.net` exports).

This is the ADR 0006 Connectivity **proven-core** exchange slice. It is **not**
the full project-owned Connectivity area from ADR 0002 (inspect/trace/compare
from live design context without treating a file as the model of record).

A `.net` file is an **exchange dataset**. It can lack current provenance and
freshness. Callers that keep a saved netlist accept staleness. Prefer
`obtain_netlist` when KiCad is available and you need a fresh parse.

The package remains pre-alpha (`0.0.0` informational). There is no public
`cli` module; export uses private ADR 0007 discovery.

## Connectivity surface (ADR 0006 A)

Connectivity belongs to the project (ADR 0002). The 1.0 surface is:

- **Supported — obtain:** `Project.netlist()` exports the full pending
  hierarchy and returns a `Netlist` with `provenance`.
- **Supported — inspect:** the `Netlist` exchange model (`components`,
  `component()`, `nets`, `net()`, `sheets`, `sheet_files`).
- **Supported — compare:** `connectivity_sets()` on two `Netlist` values.
  Save verification uses its own stricter electrical signature.
- **Supported — exchange:** `Netlist.open`, `export_netlist`, and
  `obtain_netlist` for explicit `.kicad_sch` or `.net` paths.
- **Not offered — document-only obtain:** a single child sheet is not a
  complete design. Use `Project.netlist()`. No document method exists.
- **Deferred — trace:** pin-to-pin trace from live design context without an
  export. ADR 0006 defers a live connectivity engine past 1.0.
- **Deferred:** other netlist formats, multi-instance sheet models, and
  PCB connectivity.

## Obtain from a project

```python
import hashlib
from kicad_primitives.projects import Project

project = Project.open("/path/to/board")
project.schematic().symbol("R1").set_attribute("Value", "22K")
netlist = project.netlist()  # optional kicad_cli="/explicit/path/to/kicad-cli"
print(netlist.component("R1").value)  # "22K" from pending content
snapshot = netlist.provenance
for document in snapshot.documents:
    fresh = hashlib.sha256(project.schematic(document.path).to_bytes()).hexdigest()
    print(document.path, document.is_modified, document.sha256 == fresh)
```

`Project.netlist()` stages the captured `.kicad_pro` bytes and every hierarchy
document's pending `to_bytes()` content. It uses the same private staging as
save verification and `Project.erc()`.
It does not save source, clear pending changes, or require the write guard.
Locked projects and read-only original files remain obtainable.

`provenance` is a `ProjectSnapshot` from `kicad_primitives.projects`.
It holds the project file, the SHA-256 of the captured project settings, and
one `SnapshotDocument` per hierarchy document: original path, SHA-256 of the
exported content, and pending-change state. Compare these hashes with current
content to judge freshness. File-based `Netlist.open` and `obtain_netlist`
results have `provenance=None`.

`Netlist.path` and `Netlist.source` name the deleted temporary export and
staged root. Use `provenance` for original paths.

The hierarchy rules match save verification: the root schematic and project
share a basename, and sheets are parent-relative inside the project directory.
Other layouts raise `UnsupportedSchematicOperationError`. A missing child sheet
raises `SchematicConflictError`. Backend failures raise
`KicadCliNotFoundError`, `NetlistExportError`, or `NetlistParseError`. They never
become an empty netlist.

## Open an existing netlist

```python
from kicad_primitives.netlist import Netlist

netlist = Netlist.open("/path/to/design.net")
print(netlist.source, netlist.version)
print(netlist.component("R1").lib_id, netlist.component("R1").value)
print(netlist.net("/GND").nodes)
for name, path in netlist.sheet_files.items():
    print(name, path)
```

`Netlist.open` needs no KiCad install. It requires a file whose root is
`(export …)`.

## Connectivity compare helper

```python
from kicad_primitives.netlist import connectivity_sets

before = connectivity_sets(Netlist.open("before.net"))
after = connectivity_sets(Netlist.open("after.net"))
assert before == after  # same (ref, pin) partitions; names ignored
```

Single-node nets are dropped. Optional `ignore=` is a regex on references
(same rule as Subdivision `netlist_diff`).

## Export and obtain via kicad-cli

```python
from kicad_primitives.netlist import export_netlist, obtain_netlist

# Write a durable .net (caller owns the path and its freshness).
path = export_netlist(
    "/path/to/board.kicad_sch",
    "/tmp/board.net",
    # kicad_cli="/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
)

# Fresh parse: temp export, read, delete (volatile cache).
model = obtain_netlist("/path/to/board.kicad_sch")
```

Format is always `kicadsexpr`. Discovery order: explicit `kicad_cli`, then
`KICAD_CLI`, platform defaults, then `PATH` (ADR 0007).

## Limits

- No live schematic graph and no pin-to-pin trace API beyond the exchange
  model (deferred).
- No other netlist formats (XML, allegro, orcad, …).
- No public CLI facade; subprocess policy stays inside this module.
- `export_netlist` without `output_path` creates a temp file the caller must
  delete if not using `obtain_netlist`.
- Sheet path tokens and multi-instance sheet models beyond the export content
  remain later Connectivity work.

## Errors

- `NetlistParseError`: unreadable or non-`export` kicadsexpr content.
- `NetlistExportError`: CLI non-zero exit or missing output file.
- `KicadCliNotFoundError`: discovery failed (re-exported from private locator).
- `FileNotFoundError`: missing schematic or netlist path.
- `KeyError`: missing component reference or net name on lookup helpers.
- `UnsupportedSchematicOperationError` / `SchematicConflictError`: unsupported
  or changed hierarchy for `Project.netlist()`.
- `ProjectLifecycleError`: `Project.netlist()` after close or discard.
- Ordinary `OSError` subclasses still apply to filesystem failures.

## Tests

`tests/functional/test_project_netlist.py` covers `Project.netlist()` with a
backend test double: pending hierarchy content, provenance, captured settings,
locked/read-only sources, and acquisition failures.
The opt-in native gate `tests/verify_schematic_editing.py` also obtains a
pending-snapshot project netlist before its explicit save.

Donor parse gates use `tests/fixtures/minimal_plant.net` (from
FieldUnit-Subdivision). Export paths are mocked so the normal suite needs no
KiCad install:

```bash
uv run python -m unittest discover -s tests -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict --follow-untyped-imports src/kicad_primitives
```
