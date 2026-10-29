# kicad-primitives

Stand-alone Python package for reading, editing, and writing KiCad **10** projects and libraries — consolidating KiCad I/O that today lives across jBOM, kproj, kDoctor, EagleLib2KiCad, FieldUnit-Subdivision, and Railroad.

| | |
| --- | --- |
| **Distribution** | `kicad-primitives` |
| **Import** | `kicad_primitives` |
| **License** | MIT |
| **Python** | 3.11+ |
| **Status** | Pre-alpha (`0.0.0` informational); symbols, projects, schematic attribute edits, library tables, and netlist exchange implemented |
| **Production dependency** | Not before `1.0.0` on public PyPI ([ADR 0005](docs/adr/0005-distribution-and-versioning.md)) |

Identity is canonical in [`docs/PACKAGE_IDENTITY.md`](docs/PACKAGE_IDENTITY.md), [ADR 0001](docs/adr/0001-package-identity.md), and its [ADR 0003 amendment](docs/adr/0003-source-preserving-parser-and-writes.md).
Dependency rules are in [ADR 0005](docs/adr/0005-distribution-and-versioning.md).

## Start here

- [`AGENTS.md`](AGENTS.md) — working agreements and API area list
- [Documentation contract](docs/DOCUMENTATION.md) — usage pages, docstrings, and PR doc gates
- [ADR 0002](docs/adr/0002-functional-service-toc.md) — accepted functional TOC, ownership, donor basis, and exclusions
- [ADR 0003](docs/adr/0003-source-preserving-parser-and-writes.md) — accepted source-preserving parser, write guarantees, and Python floor
- [ADR 0004](docs/adr/0004-first-symbol-library-slice.md) — accepted first slice and done-bar
- [ADR 0005](docs/adr/0005-distribution-and-versioning.md) — distribution, versioning, and probe install rules
- [Symbol-library usage](docs/symbol-libraries.md) — inspect declarations/inheritance, edit existing values, and save explicitly
- [Project context usage](docs/projects.md) — open a project, list hierarchical sheets, read text variables
- [Schematics](docs/schematics.md) — inspect/edit supported objects, restore concrete definitions, save with electrical proof, and get full-project pending ERC reports
- [Library tables](docs/tables.md) — global/project symbol and footprint table resolve and localized writes
- [Connectivity and netlist exchange](docs/netlist.md) — `Project.netlist()` on pending source; parse kicadsexpr `.net` files; obtain/export via private `kicad-cli`
- [`CONTEXT.md`](CONTEXT.md) — capability and release terminology
- [`docs/kicad-services-survey-2026-10-12.md`](docs/kicad-services-survey-2026-10-12.md) — founding survey
- [Wayfinder map #1](https://github.com/plocher/kicad-primitives/issues/1) — package design decisions

## Install (owner development and probes)

Pre-1.0 labels carry **no** compatibility promise.
Donor **released** packaging must not depend on this package until **`1.0.0`** on public PyPI.
Do not add `sys.path` hacks to this tree.

### Package work (this repo)

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
python -c "import kicad_primitives as kp; print(kp.__version__)"
```

### Disposable donor probe

Use a separate venv or throwaway branch environment. Do not merge a pre-1.0 dependency into donor `main`.

```bash
uv venv
source .venv/bin/activate
uv pip install -e /path/to/kicad-primitives
```

Optional Test PyPI wheels are probe-only. Use public PyPI as an extra index for transitive dependencies such as `circuitdk-lossless-sexpr`.
Day-to-day donor work without a probe leaves `kicad-primitives` uninstalled so local donor code remains the source of truth.

### After 1.0 (donor cutover note)

When a donor migrates, that donor adds an ordinary pin such as `kicad-primitives>=1.0.0,<2` and removes its local duplicate modules.
Exact ranges belong in the donor migration PR. No jBOM (or other donor) version line couples to this package before that cutover. Do not vendor this tree into a donor.

## Scope and implementation status

The package supplies KiCad artifact objects and capabilities, not client application workflows.
Clients select objects, inspect and edit them, then decide whether to save, save as, or discard.
Edits belong on the relevant objects. Source persistence is explicit.
[ADR 0008](docs/adr/0008-artifact-objects-and-explicit-persistence.md) records this package-wide direction and the current implementation gaps.
Schematics support pending-change observation and explicit same-location saves.
Save-as relocation and general close/discard/session interfaces remain later work.

The accepted functional TOC includes projects, schematics, PCBs, symbol libraries, footprint libraries, library resolution, and connectivity.
This is intended scope, not a list of shipped capabilities.
Implemented services today:
- `kicad_primitives.symbols.SymbolLibrary` — explicit-path inspection and localized existing-attribute updates, with byte-preserving output ([usage](docs/symbol-libraries.md)).
- `kicad_primitives.projects.Project` — open a project directory or `.kicad_pro`, list hierarchical schematic paths with parent-relative `Sheetfile` resolution, and read `text_variables` ([usage](docs/projects.md)).
- `kicad_primitives.schematics` via project context — placed attributes, selected concrete embedded restore, verified saves, typed pending `Project.erc()` reports, title block, and geometry read ([usage](docs/schematics.md)).
- `kicad_primitives.tables.LibraryTables` — global/project symbol and footprint tables, `${VAR}` resolve, nested tables, localized add/remove/rename ([usage](docs/tables.md)).
- `kicad_primitives.netlist` — kicadsexpr netlist **exchange** parse and obtain/export; project-owned obtain is `Project.netlist()` ([usage](docs/netlist.md)).
PCB document models, project-owned Connectivity beyond exchange, and the remaining TOC areas are not implemented yet.
PCB editing follows the same high-level patterns as schematic and library editing.
Exposed unimplemented operations must fail explicitly before making changes.

3D models remain out of scope until a consumer asks.

## Validate

After installing the package in the active Python 3.11+ environment:

```bash
uv run python -m unittest discover -s tests -q
```

The normal suite has no KiCad installation or donor checkout dependency.
Opt-in real-library/KiCad checks and their recorded limits are documented in the usage recipe.
