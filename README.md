# kicad-primitives

Stand-alone Python package for reading, editing, and writing KiCad **10** projects and libraries — consolidating KiCad I/O that today lives across jBOM, kproj, kDoctor, EagleLib2KiCad, FieldUnit-Subdivision, and Railroad.

| | |
| --- | --- |
| **Distribution** | `kicad-primitives` |
| **Import** | `kicad_primitives` |
| **License** | MIT |
| **Python** | 3.10+ |
| **Status** | Pre-alpha (`0.0.0`); identity locked, API modules not shipped |

Identity is canonical in [`docs/PACKAGE_IDENTITY.md`](docs/PACKAGE_IDENTITY.md) and [ADR 0001](docs/adr/0001-package-identity.md).

## Start here

- [`AGENTS.md`](AGENTS.md) — working agreements and API area list
- [`docs/kicad-services-survey-2026-10-12.md`](docs/kicad-services-survey-2026-10-12.md) — founding survey
- [Wayfinder map #1](https://github.com/plocher/kicad-primitives/issues/1) — package design decisions

## Install (editable, local)

```bash
python3 -m pip install -e .
python3 -c "import kicad_primitives as kp; print(kp.__version__)"
```

## Non-goals (until a consumer asks)

PCB editing, 3D models.
