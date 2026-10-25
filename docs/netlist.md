# Netlist exchange: parse and obtain/export

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

- Not a project-context Connectivity service; no live schematic graph, no
  pin-to-pin trace API beyond the exchange model.
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
- Ordinary `OSError` subclasses still apply to filesystem failures.

## Tests

Donor parse gates use `tests/fixtures/minimal_plant.net` (from
FieldUnit-Subdivision). Export paths are mocked so the normal suite needs no
KiCad install:

```bash
uv run python -m unittest discover -s tests -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict --follow-untyped-imports src/kicad_primitives
```
