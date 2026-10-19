# ADR 0002: Functional service TOC

Date: 2026-10-19

Status: Accepted by the owner in the TOC grilling session
Ticket: [Public module TOC and responsibility sentences](https://github.com/plocher/kicad-primitives/issues/3)

## Problem

The survey groups public responsibilities with internal mechanisms such as parsing, text editing, and CLI execution.
That grouping exposes file-format details and lets donor implementations dictate the public interface.
The package needs a functional TOC that separates intended scope from current capability and release completeness.

## Constraints and requirements

- Public interfaces describe what clients can accomplish, not how the package performs the work.
- Schematics and PCBs require their owning project context.
- Library resolution also works without a project. Project context adds lookup locations and variables.
- Parsing and byte-preserving editing remain internal. Package services are their callers.
- PCB editing follows the same high-level patterns as schematic and library editing, even before implementation.
- Consumer migration does not gate package development.

## Definition of done

The TOC defines each functional area's responsibility, donor basis, and exclusions.
It distinguishes used, unused, and unimplemented capabilities without declaring the whole intended scope complete.
Function names, import paths, parser choice, and execution mechanisms remain later decisions.

## Options and evaluation

### A: Publish the survey's eleven mechanism and domain areas

This follows existing donor modules and makes their implementation pieces easy to locate.
However, it exposes changing parser interfaces and treats CLI execution as a public responsibility.
It also separates checks from the objects whose context they require.

### B: Publish individual client tasks

This emphasizes outcomes such as property edits and connectivity comparisons.
However, a task catalog alone does not express the document ownership and project context those operations need.

### C: Organize public services by functional area

Projects, documents, and collections own their operations.
Internal layers share representations and implementation machinery.
This preserves context and permits implementation changes without requiring callers to reproduce the internal workflow.

## Decision

Choose C. The owner approved these seven responsibility sentences:

1. **Projects:** Establish design context and provide access to project settings, schematics, PCBs, and project-wide operations.
2. **Schematics:** Inspect and edit schematic content within its project, including placed symbols, embedded definitions, hierarchy, and electrical checks.
3. **PCBs:** Inspect and edit board content within its project, including placed footprints, board structures, and design-rule checks.
4. **Symbol libraries:** Inspect and edit reusable symbol definitions and their library collections.
5. **Footprint libraries:** Inspect and edit reusable footprint definitions and their library collections.
6. **Library tables and resolution:** Manage library registrations and resolve references using available global and project context.
7. **Connectivity:** Obtain, inspect, trace, and compare electrical connections within project context, with explicit data exchange where needed.

These are functional areas, not seven independent entry points or final Python namespace names.

### Ownership and internal layers

Projects provide access to their schematics and PCBs. The public interface does not open those documents independently.
Library services own reusable definitions. Document services own placed instances and embedded definitions.
They share internal machinery rather than maintain competing implementations.

Checks belong to the object being checked.
Project ERC covers the project hierarchy.
Scoped schematic ERC must honor its requested scope or reject it explicitly.
PCB DRC follows the same ownership pattern.
Preconditions and postconditions belong to each abstraction, not to a separate public checks area.

Connectivity belongs to project context.
A service can build its model through CLI export and parsing, or directly from the loaded design.
Callers do not need a file export/import sequence to obtain that model.
Netlist files are exchange datasets that can lack current provenance and freshness.

The internal hierarchy comprises file representation, shared KiCad primitives, document models, and project context.
Operations use those models.
Runtime safeguards and external execution support these layers.
This dependency view helps classify and prioritize work without prescribing a strict bottom-up delivery sequence.

`sexp` and `text` are internal details, not advanced public interfaces.
`checks` is not a separate public area.
`cli` is provisional KiCad integration machinery, not a locked public module.
Wrapping, replacing, refactoring, or forking KiCad functionality remains open.

### Capability profile and release meaning

Each area records its remit, current interface and maturity, client dependencies, capability groups, known shortcomings, and explicit exclusions.

- **Used capabilities:** Implemented capabilities consumed by current clients.
- **Unused capabilities:** Implemented capabilities not consumed by current clients. Unused does not mean out of scope.
- **Unimplemented capabilities:** Intended capabilities that do not yet exist.

Known bugs, technical debt, and blind spots are a separate dimension across implemented capabilities.
The inventory must establish usage. Do not guess classifications from the presence of donor code.

**Parity equals used capabilities.**
Consumer usability also requires migration recipes and documentation.
It is a minimum bar, not package completeness.
Unused and unimplemented capabilities can be necessary for completeness, reliability, and general KiCad use.
Evolution issues inform which capabilities and defect fixes must join parity for 1.0 releasability.
The owner locks that release bar. This TOC does not select it.

An exposed but unimplemented operation raises an explicit unsupported-operation exception before making changes.
It does not silently succeed. Exact exception types and method names remain undecided.
This permits consistent editing interfaces without claiming their implementations exist.

### Donor basis

The founding survey, sections 1–3, is the source for these paths and limitations.
This mapping identifies source material, not a fresh usage inventory or a claim of package implementation.

- **Projects:** jBOM `src/jbom/services/project_context.py`, `project_discovery.py`, `project_file_resolver.py`, and `project_variables_reader.py`.
- **Schematics:** jBOM `src/jbom/services/schematic_reader.py` and `annotation_service.py`.
  Subdivision contributes `tools/kicad_services/schematic_reader.py`, `sch_text.py`, and retired edit recipes.
  kDoctor contributes `poc/sch_symbol_transfer.py` and symbol-lineage work.
- **PCBs:** jBOM `src/jbom/services/pcb_reader.py`.
  kDoctor contributes `poc/services/footprint_lineage_service.py`.
  These are partial read capabilities, not a complete board model or editor.
- **Symbol libraries:** Subdivision `tools/kicad_services/symbol_library_reader.py`, `sch_text.py`, and retired recipes.
  kDoctor contributes `poc/services/symbol_lineage_service.py` inheritance handling.
- **Footprint libraries:** kDoctor `poc/services/footprint_lineage_service.py`.
  EagleLib2KiCad contributes footprint enumeration in `src/eaglelib2kicad/services/kicad_library_context_service.py`.
  A complete definition editor remains unimplemented.
- **Library tables and resolution:** EagleLib2KiCad `src/eaglelib2kicad/services/kicad_environment_service.py`.
  kDoctor contributes nested-table handling from `poc/services/symbol_lineage_service.py`.
- **Connectivity:** Subdivision `tools/kicad_services/netlist_reader.py` and archived connectivity gates in `docs/archive/unify/build_spcoast.py`.
- **Cross-cutting internals:** jBOM `src/jbom/common/sexp_parser.py` and `kicad_runtime.py`.
  Subdivision contributes byte-preserving edit machinery.
  kproj contributes `src/kproj/common/kicad_install.py`, `services/design_analyzer.py`, and exporters.
  kDoctor contributes report interpretation from `poc/erc_drc_summary.py`.

Ports bring their donor unit tests and functional scenarios.
This decision does not authorize a new test-framework or CI project.

### Exclusions and deferred decisions

- Project services do not own consumer product logic, fabrication orchestration, publishing workflows, or railroad domain compilers.
- Library resolution owns registrations and reference resolution, not definition content.
- Library services do not own placed document instances.
- Connectivity does not infer circuit behavior.
- PCB editing is intended scope, not an exclusion. Its implementation remains unimplemented where absent.
- 3D models remain out of scope until requested.
- Detailed contracts, lookup precedence, execution strategy, and the 1.0 capability selection remain later work.

## Consequences

The accepted TOC supersedes the survey-derived public area list and PCB-editing exclusion in earlier repository guidance.
The survey remains historical evidence and is not rewritten.
Future inventory and implementation work use the functional areas without exposing internal file-format mechanisms.
Consumer migration issues provide freeze-and-replace recipes when a capability is ready for that consumer.
