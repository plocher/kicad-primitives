# Architecture Decision Records

| ADR | Status | One-line |
| --- | --- | --- |
| [0001-package-identity.md](0001-package-identity.md) | Accepted, amended by 0003 | Distribution `kicad-primitives`, import `kicad_primitives`, MIT, KiCad 10 write target. ADR 0003 updates Python to 3.11+ and selects the parser. |
| [0002-functional-service-toc.md](0002-functional-service-toc.md) | Accepted | Replace the mixed mechanism/domain TOC with seven functional areas. Projects own document context, internals stay private, and parity differs from completeness. |
| [0003-source-preserving-parser-and-writes.md](0003-source-preserving-parser-and-writes.md) | Accepted | CircuitDK's private lossless representation serves reads and localized writes, with source-backed UUID insertion. Python 3.11+; published 0.1.1 artifacts verified. |
| [0004-first-symbol-library-slice.md](0004-first-symbol-library-slice.md) | Accepted | First functional slice: explicit-path symbol-library inspection and localized updates to existing declared properties, with inheritance/unit/style fidelity and preservation gates. |
| [0005-distribution-and-versioning.md](0005-distribution-and-versioning.md) | Accepted | No released donor dependency before `1.0.0` on public PyPI; pre-1.0 is informational only; WIP via `uv` editable installs and optional Test PyPI probes; no jBOM version coupling or vendoring. |
| [0006-1.0-capability-and-releasability-bar.md](0006-1.0-capability-and-releasability-bar.md) | Accepted | `1.0.0` bar: macro service surfaces (A), proven cores (B), donor-used floor (C); FieldUnit schematic ingest and symbol authoring in B; functional tests as evidence; cutover not a gate. |
| [0007-internal-kicad-cli-discovery.md](0007-internal-kicad-cli-discovery.md) | Accepted | Private lazy `kicad-cli` path discovery: explicit path, then `KICAD_CLI`, platform defaults, `PATH`; hard discovery error; no public `cli` module. |
| [0008-artifact-objects-and-explicit-persistence.md](0008-artifact-objects-and-explicit-persistence.md) | Accepted; ZIP minimum selected | Artifact-owned nouns edit buffered source. Roots require current save decisions or terminal discard. Symbols use native `.bak`; Projects add strict file-set saves, ZIP history, and bounded original-safe save-as with stable identity. Git `.history` remains deferred. |

Form and process: see root `AGENTS.md` (Proposals are ADRs).
