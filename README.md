# kicad-primitives

Stand-alone Python package for reading, editing, and writing KiCad **10** projects and libraries — consolidating KiCad I/O that today lives across jBOM, kproj, kDoctor, EagleLib2KiCad, FieldUnit-Subdivision, and Railroad.

| | |
| --- | --- |
| **Distribution** | `kicad-primitives` |
| **Import** | `kicad_primitives` |
| **License** | MIT |
| **Python** | 3.11+ |
| **Status** | Pre-alpha (`0.0.0`); first symbol-library read/edit service implemented |

Identity is canonical in [`docs/PACKAGE_IDENTITY.md`](docs/PACKAGE_IDENTITY.md), [ADR 0001](docs/adr/0001-package-identity.md), and its [ADR 0003 amendment](docs/adr/0003-source-preserving-parser-and-writes.md).

## Start here

- [`AGENTS.md`](AGENTS.md) — working agreements and API area list
- [ADR 0002](docs/adr/0002-functional-service-toc.md) — accepted functional TOC, ownership, donor basis, and exclusions
- [ADR 0003](docs/adr/0003-source-preserving-parser-and-writes.md) — accepted source-preserving parser, write guarantees, and Python floor
- [ADR 0004](docs/adr/0004-first-symbol-library-slice.md) — accepted first slice and done-bar
- [Symbol-library usage](docs/symbol-libraries.md) — inspect declarations/inheritance, edit existing values, and save explicitly
- [`CONTEXT.md`](CONTEXT.md) — capability and release terminology
- [`docs/kicad-services-survey-2026-10-12.md`](docs/kicad-services-survey-2026-10-12.md) — founding survey
- [Wayfinder map #1](https://github.com/plocher/kicad-primitives/issues/1) — package design decisions

## Install (editable, local)

```bash
python3 -m pip install -e .
python3 -c "import kicad_primitives as kp; print(kp.__version__)"
```

## Scope and implementation status

The accepted functional TOC includes projects, schematics, PCBs, symbol libraries, footprint libraries, library resolution, and connectivity.
This is intended scope, not a list of shipped capabilities.
The implemented first slice is `kicad_primitives.symbols.SymbolLibrary`: explicit-path inspection and localized existing-property updates, with byte-preserving output.
See the [usage recipe and limitations](docs/symbol-libraries.md). The other functional areas are not implemented yet.
PCB editing follows the same high-level patterns as schematic and library editing.
Exposed unimplemented operations must fail explicitly before making changes.

3D models remain out of scope until a consumer asks.

## Validate

After installing the package in the active Python 3.11+ environment:

```bash
python -m unittest discover -s tests -q
```

The normal suite has no KiCad installation or donor checkout dependency.
Opt-in real-library/KiCad checks and their recorded limits are documented in the usage recipe.
