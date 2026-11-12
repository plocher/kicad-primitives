# Domain glossary

## KiCad data and operations

ADR 0010 sets the words load, save, open, and close. The code moves to them with the implementation tickets.

**Artifact**:
A KiCad project, document, library, table, drawing sheet, or other supported KiCad data object with its own content and context.

**Pending changes**:
In-memory changes to an artifact or its owned content that the client has not saved.

**Model**:
The in-memory content of one file, or of an association of files. A model carries the methods that read and change it.

**Load**:
Read one file into a new, independent model. Nothing is held after the read.

**Save**:
Write a model to its file. Save checks nothing: the "changed on disk" check, the validity check, and the backup are separate calls.

**Save as**:
Explicit persistence to a new destination, with artifact rebinding only after success.

**Open**:
Take a lock. Open fails when another session holds it. Open does nothing else.

**Close**:
Release a lock. Close does nothing else. A model has no close.

**Revert**:
Drop the unsaved edits of an artifact or item and reload it from disk. The object keeps its identity.
Revert reads the disk, so it can fail. At level 0, a new load does the same job. Further revert work is deferred (ADR 0010).

**Level 0 / Level 1 / Level 2**:
Building blocks (one file, one model, one job per call) / required to be like KiCad (the in-memory model that a client works in) / convenience choices (functions built only from the levels below).

**Schematic**:
The project's set of sheet trees, loaded and saved as one document. KiCad `SCHEMATIC`.
KiCad 10 lists peer top-level sheets in `schematic.top_level_sheets`. There is no single root.

**Sheet file**:
One `.kicad_sch` file. Content edits to it reach every instance of it. KiCad `SCH_SCREEN`.
_Avoid_: Sheet or schematic, for one file.

**Sheet symbol**:
The box on a parent sheet file that points at a target sheet file. Its pins are the electrical interface of the instance. KiCad `SCH_SHEET`.

**Sheet instance**:
One placement of a sheet file in the hierarchy, identified by its UUID path. It holds per-placement data, such as references, units, flags, and page numbers. KiCad `SCH_SHEET_PATH`.

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
