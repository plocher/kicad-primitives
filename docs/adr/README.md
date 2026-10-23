# Architecture Decision Records

| ADR | Status | One-line |
| --- | --- | --- |
| [0001-package-identity.md](0001-package-identity.md) | Accepted, amended by 0003 | Distribution `kicad-primitives`, import `kicad_primitives`, MIT, KiCad 10 write target. ADR 0003 updates Python to 3.11+ and selects the parser. |
| [0002-functional-service-toc.md](0002-functional-service-toc.md) | Accepted | Replace the mixed mechanism/domain TOC with seven functional areas. Projects own document context, internals stay private, and parity differs from completeness. |
| [0003-source-preserving-parser-and-writes.md](0003-source-preserving-parser-and-writes.md) | Accepted | CircuitDK's private lossless representation serves reads and localized writes, with source-backed UUID insertion. Python 3.11+; published 0.1.1 artifacts verified. |
| [0004-first-symbol-library-slice.md](0004-first-symbol-library-slice.md) | Accepted | First functional slice: explicit-path symbol-library inspection and localized updates to existing declared properties, with inheritance/unit/style fidelity and preservation gates. |

Form and process: see root `AGENTS.md` (Proposals are ADRs).
