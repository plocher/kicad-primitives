# Domain glossary

## KiCad data and operations

**Flag**:
A typed behavior switch on a symbol or footprint, such as DNP or exclusion from BOM, board, or simulation.
_Avoid_: Attribute or text field for these switches.

**Attribute**:
A named value on a symbol or footprint, such as Reference, Value, Footprint, MPN, or a custom name=value item.
_Avoid_: Property or field as the canonical package term for these values.

**Setting**:
Project-wide configuration.
_Avoid_: Property or metadata as an unqualified name for project configuration.

**Text variable**:
A user-defined project name and substitution value, referenced with syntax such as `${PART_FAMILY}`.

**Title-block field**:
A title, revision, date, company, or comment value belonging to a schematic sheet or board.

**Drawing-sheet field**:
A field displayed by a drawing-sheet template.
It can reference title-block values, text variables, and built-in values.
_Avoid_: Keyword, which also names symbol-library search terms.

**Reference annotation**:
Assignment or update of reference designators, including consistent associated instance records.
Reference is an attribute, but its update requires reference annotation semantics.
_Avoid_: Annotation for general attribute editing.

## Package capabilities

- **Functional area:** A group of client-facing responsibilities organized around projects, documents, collections, or connectivity.
- **Project context:** The owning design scope and the settings, hierarchy, and resolution information needed to operate on its documents.
- **Used capability:** An implemented capability consumed by a current client.
- **Unused capability:** An implemented capability not consumed by a current client. It can still be necessary for package completeness.
- **Unimplemented capability:** An intended capability that does not yet exist.
- **Parity:** Coverage of the used capabilities.
- **Consumer usability:** The capabilities required by a consumer, together with migration recipes and documentation needed to use the replacement.
- **Completeness:** The capability coverage needed for general KiCad use, beyond a single consumer's minimum needs.
- **Releasability:** Satisfaction of the owner-approved release bar (ADR 0006), including the A/B/C model, selected proven cores, defect fixes, and functional evidence.
- **Surface (A):** The complete functional contract defined for a service, independent of how much is implemented yet.
- **Proven core (B):** The implemented portion of a surface that must work in practice before that service counts toward 1.0.
- **Donor floor (C):** Used donor capabilities that must be possible through the package surface; a usability check, not the API shape.
- **Pre-1.0 label:** An informational `0.x` package version with no compatibility promise (ADR 0005).
- **Production dependency bar:** First public PyPI version a donor may pin for released use: `1.0.0` (ADR 0005). Capability content of that release: ADR 0006.
- **Validation probe:** Disposable install and exercise of WIP against a donor without merging a released pre-1.0 dependency. Not a substitute for package functional tests.
