# Package identity

Canonical record (ADR 0001). Do not fork these values in docs without amending the ADR.

| Field | Value |
| --- | --- |
| Distribution name | `kicad-primitives` |
| Import name | `kicad_primitives` |
| License | MIT (`LICENSE`) |
| Python | 3.10 or later (`requires-python = ">=3.10"`) |
| KiCad target | KiCad 10 for write and edit |
| Format contract | Per-file `(version …)` (and related format markers) |
| Older formats | Read-only when practical |
| Runtime deps | `sexpdata` only if the chosen sexp reader keeps it (open until parser ticket) |
| Home | This repository is the only long-term home for shared KiCad I/O services |

See [ADR 0001](adr/0001-package-identity.md).
