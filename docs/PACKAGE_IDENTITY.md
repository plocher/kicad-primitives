# Package identity

Canonical record: ADR 0001, with the Python floor and parser updated by ADR 0003.
Do not fork these values in docs without an accepted ADR.

| Field | Value |
| --- | --- |
| Distribution name | `kicad-primitives` |
| Import name | `kicad_primitives` |
| License | MIT (`LICENSE`) |
| Python | 3.11 or later (`requires-python = ">=3.11"`) |
| KiCad target | KiCad 10 for write and edit |
| Format contract | Per-file `(version …)` (and related format markers) |
| Older formats | Read-only when practical |
| Runtime deps | `circuitdk-lossless-sexpr==0.1.1` (private import `lossless_sexpr`) |
| Home | This repository is the only long-term home for shared KiCad I/O services |

See [ADR 0001](adr/0001-package-identity.md) and [ADR 0003](adr/0003-source-preserving-parser-and-writes.md).
