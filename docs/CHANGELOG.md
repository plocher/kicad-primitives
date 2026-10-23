# Changelog

## Unreleased

- Implement explicit-path symbol-library inspection, including private property modifiers, inheritance provenance, immutable snapshots, and unit/body-style pin membership.
- Add byte-localized existing-property edits with reparsing and explicit atomic single-file saves, conflict detection, and link/permission safeguards.
- Port donor behavior tests; add failure/preservation contracts and an opt-in real-library/KiCad gate with a hashed verification record.
- Publish a symbol-library usage recipe and installed typing information; correct ADR 0004's private-property observation.
- Ratify symbol-library inspection and localized existing-property updates as the first functional slice, with its acceptance gates, in ADR 0004 (decision recorded before implementation).
- Accept CircuitDK's source-preserving parser and write contract in ADR 0003, including the verified UUID insertion rule.
- Raise the Python floor to 3.11 and declare the verified `circuitdk-lossless-sexpr==0.1.1` dependency.
- Ratify seven public functional areas and their ownership rules in ADR 0002.
- Keep parsing, text editing, runtime safeguards, and KiCad execution internal.
- Include PCB editing in intended scope, with explicit failure for exposed unimplemented operations.
- Distinguish parity, consumer usability, and package completeness.
