# ADR 0004: First slice — symbol-library inspection and property updates

Date: 2026-10-23

Status: Accepted by the owner on 2026-10-23.

Ticket: [First vertical slice: v0.1 module set and done-bar](https://github.com/plocher/kicad-primitives/issues/5)

## Problem

The package has an accepted functional TOC and source-preserving representation, but no public service.
The first functional release needs a bounded client capability, not a collection of exposed parser and execution mechanisms.
It must work on real libraries without adopting the donor readers' silent information loss.

## Constraints and requirements

- ADR 0002 keeps parsing, text editing, and KiCad execution private.
- ADR 0003 supplies the single representation, byte-preserving writes, current-span rule, and operation-specific gates.
- The slice must preserve unit and body-style identity and distinguish declared content from inherited content.
- Railroad contract vocabulary and electronics procurement or simulation policy remain consumer concerns.
- Port relevant donor behavior and tests. Do not build a separate test-framework or CI epic.
- Package delivery does not wait on consumer migration.

## Definition of success

An installed client can inspect a symbol library by explicit path and update existing, unambiguous property values declared on a selected symbol.
Inspection does not silently flatten inheritance, unit/body styles, or repeated properties.
Writes make the required change and preserve every unrelated byte.
The acceptance gates and a concrete usage recipe accompany the capability.

This ADR selects the first functional release target, called v0.1 in the ticket.
It does not change the current `0.0.0` package version or select distribution policy.

## Evidence

Read-only inspection covered the four stable Railroad libraries, SPCoast electronics, and six installed KiCad libraries: Device, 74xx, Amplifier_Operational, Transistor_BJT, Connector_Generic, and power.
All 11 files, containing 2,230 top-level symbols, declared library format `20251024` and reproduced their original bytes through CircuitDK.
This is source-preservation evidence, not proof of complete semantic support or KiCad acceptance.

- Railroad contained 13 multi-unit symbols. SPCoast's LM358 was also multi-unit.
  Shared unit-0 content and unit locking occurred in the inspected libraries.
- The installed sample contained 664 derived symbols; 372 referenced parents later in the file.
  Subdivision's overview returned no pins for `7400`, which extends the later `74LS00`.
- Twenty base symbols in 74xx contained alternate body styles.
  Combining every body's pins would count alternate representations together.
- Correction from implementation inspection: four Device symbols contained eight private properties, using `(property private "name" "value" ...)`.
  `private` is a modifier, not their name; the modifier-aware scan found no duplicate names in Device.
  Repeated-name preservation remains an approved defensive contract, exercised with synthetic inputs rather than claimed as observed in Device.
- All 22 existing Subdivision overview tests passed despite the forward-inheritance defect.

The counts describe this bounded inspection, not all installed libraries or current consumer usage.
The observed constructs establish read requirements; they do not establish that each construct has a current consumer.

### Donor basis

- Subdivision `tools/kicad_services/symbol_library_reader.py` and `sch_text.py` supply complementary inspection behavior.
  `tools/kicad_library_overview.py` and `tools/contract/lint_symbol_fields.py` demonstrate field, pin, unit, and locking consumers.
- Subdivision `tests/test_kicad_plant_graph.py` contains the reader's pin-contract test.
  `tests/test_kicad_library_overview.py` exercises fields, escaping, pins, and units through the overview.
  Port relevant library behavior assertions, not the consumer's HTML interface.
- kDoctor `poc/services/symbol_lineage_service.py` supplies inheritance-handling evidence.
  Its text scans and fallback behavior are not a replacement for the accepted parser and explicit errors.
- Railroad `symbols/edits/2026-10-12-four-libraries.py` and `2026-10-13-head-set.py` demonstrate recurring property updates alongside larger symbol and pin edits.
  They are dated consumer recipes, not generic package policy.

CircuitDK supplies syntax, source retention, and edit spans.
KiCad-specific interpretation, inheritance, validation, and safe persistence remain package responsibilities.

## Candidates and evaluation

### A: Ship the survey's parser, netlist, CLI, and runtime seed

Several donor pieces already have tests.
However, publishing implementation mechanisms conflicts with ADR 0002 and does not demonstrate one bounded read/edit workflow.
Those internals may support later services without becoming this release's public surface.

### B: Ship a broad symbol-library editor

Rename, copy, pin editing, property insertion/deletion, and unit restructuring recur in donor recipes.
They would address more tasks immediately, but require additional identity, electrical, formatting, and cross-library contracts.
Taking them together would make the first slice too broad.

### C: Ship symbol-library inspection and localized existing-property updates

This delivers a real client workflow while exercising the accepted read/write foundation.
Inspection must address observed inheritance and unit/style gaps rather than reproduce donor defects.
Restricting edits to existing declared properties avoids implicit structural changes and keeps the write delta bounded.

## Decision

Choose C. The owner approved the following scope and done-bar.

### Included

- A public symbol-library functional service opened by an explicit library path.
  At decision acceptance, exact Python names were unspecified; the owner approved the first implementation surface on 2026-10-23 (see implementation note below).
- One reader covering all properties, inheritance, units/body styles, and unit-specific pins without silent flattening.
  Declared and effective inherited values remain distinguishable, including where a value originates.
  Repeated declared properties are not silently collapsed into a dictionary.
- Localized updates to existing, unambiguous property values declared on the selected symbol.
  Do not implicitly edit a parent or materialize an inherited property.
- Opaque, byte-preserved retention of unrelated graphics and unsupported content.
  An operation must fail if correctness requires understanding content it does not support.

### Acceptance gates

- The installed package exposes the functional service without exposing parser machinery.
- Relevant donor behavior and tests move with the service.
  Add focused cases for forward inheritance, alternate styles, repeated properties, and escaping.
- No-op output matches input bytes exactly.
  Edited output contains the required property change and preserves every unrelated byte.
  Subsequent queries and edits use reparsed source, not stale spans.
- Unsupported or ambiguous edits fail before writing.
  Intake validation follows the per-file format contract and KiCad 10 write target.
- Disposable-copy KiCad checks record acceptance, first-save normalization, and second-save stability separately.
  A KiCad resave is verification evidence, not the production write mechanism.
- A concrete usage recipe accompanies the service.
  Consumer readiness leads to a freeze-and-replace recipe issue in that consumer; its migration does not gate the package.

ADR 0003's operation-specific verification still applies.
Library preservation or KiCad acceptance alone is not a claim of project connectivity verification.
There is no universal cache-refresh requirement.

### Outside this slice

- Symbol or pin renaming, property insertion/deletion, unit restructuring, and copying between libraries.
- Schematic edits, placed-instance edits, and embedded-library cache updates.
- Library-table discovery and resolution.
- Other public functional areas from ADR 0002.

These are release deferrals, not exclusions from intended package scope.
The slice is neither full donor parity nor the package's 1.0 completeness bar.

## Consequences

The first implementation can proceed as ordinary work under this bounded functional contract.
No service is delivered by recording this decision.
The parser remains private, and no consumer-specific compatibility adapter moves into the package.
Distribution, the job/session seam, full capability inventory, lookup policy, and 1.0 completeness remain separate decisions.

## Implementation note — 2026-10-23

The owner approved `kicad_primitives.symbols.SymbolLibrary` with declared inspection, explicit inheritance resolution, in-memory property edits, byte preview, and a separate `save()`.
Issue #19 implements that surface and the plan's optimistic single-file persistence safeguards.
The [usage recipe](../symbol-libraries.md) documents the shipped methods, errors, and limitations.
The [verification record](../review/first-symbol-slice-results.json) separates byte preservation, KiCad first-save normalization, and second-save stability.
This note does not reopen #3, close #11, change distribution policy, or claim consumer cutover.
