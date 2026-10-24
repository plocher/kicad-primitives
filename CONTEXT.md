# Domain glossary

- **Functional area:** A group of client-facing responsibilities organized around projects, documents, collections, or connectivity.
- **Project context:** The owning design scope and the settings, hierarchy, and resolution information needed to operate on its documents.
- **Used capability:** An implemented capability consumed by a current client.
- **Unused capability:** An implemented capability not consumed by a current client. It can still be necessary for package completeness.
- **Unimplemented capability:** An intended capability that does not yet exist.
- **Parity:** Coverage of the used capabilities.
- **Consumer usability:** The capabilities required by a consumer, together with migration recipes and documentation needed to use the replacement.
- **Completeness:** The capability coverage needed for general KiCad use, beyond a single consumer's minimum needs.
- **Releasability:** Satisfaction of the owner-approved release bar, including parity and selected completeness requirements and defect fixes.
- **Pre-1.0 label:** An informational `0.x` package version with no compatibility promise (ADR 0005).
- **Production dependency bar:** First public PyPI version a donor may pin for released use: `1.0.0` (ADR 0005).
- **Validation probe:** Disposable install and exercise of WIP against a donor without merging a released pre-1.0 dependency.
