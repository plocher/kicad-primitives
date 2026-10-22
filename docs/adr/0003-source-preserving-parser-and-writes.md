# ADR 0003: One source-preserving representation for KiCad reads and writes

Date: 2026-10-22

Status: Accepted by the owner on 2026-10-22.

Ticket: [Write philosophy: byte-preserve vs tree rewrite vs one parser](https://github.com/plocher/kicad-primitives/issues/4)

## Decision

- Use CircuitDK's lossless S-expression module as the private structural foundation.
- Require Python 3.11 or later and use the unmodified upstream distribution.
- Declare `circuitdk-lossless-sexpr==0.1.1` as the initial verified dependency.

The one-representation and write guarantees below record existing owner locks.
The owner explicitly accepted CircuitDK and moved the Python floor to 3.11.
This supersedes ADR 0001's Python 3.10+ floor and conditional `sexpdata` dependency, not its other identity decisions.
The published artifact verification below satisfies the adoption check.

## Problem

jBOM reads BOM data. Subdivision reads and edits detailed symbol and schematic structures.
Both needs are valid. Their current implementations do not share one representation.

A semantic tree alone loses source details needed for localized writes.
Independent text scans can disagree with the semantic reader about structure.
The package needs one structural foundation that supports both uses without exposing it to external callers.

## Constraints and requirements

The owner locked these requirements during the write-philosophy discussion:

- One internal structural representation serves reads and writes.
- Content outside an operation's required understanding remains opaque and byte-preserved.
- An operation fails when it cannot establish correctness without understanding that content.
- No-op saves preserve original bytes. Targeted edits preserve untouched content and satisfy their own postconditions.
- Connectivity-preserving edits also verify unchanged connectivity. Intentional electrical edits verify their requested changes instead.
- Consumer-specific migration adapters belong in consumers, not in the shared package.
- Shared development happens here without an intermediate Subdivision service layer.

ADR 0002 keeps parsing, text editing, and execution mechanisms private.
Projects own schematic and PCB context. A file-level experiment does not authorize independent public document entry points.
KiCad 10 is the write target. Per-file format versions remain the contract under ADR 0001.

The one-parser rule concerns S-expressions.
It does not replace JSON handling for `.kicad_pro`, or prohibit typed domain views derived from the structural representation.

## Definition of success

- Semantic queries and edit locations derive from the same parsed structure.
- Unchanged content, including unrecognized nodes and lexical details, survives edits unchanged.
- Ordered insertion has a source-backed requirement and a reproducible acceptance case.
- Functional services do not depend on a donor's old tree or regex interface.
- The dependency, license, Python requirement, and measured limitations are explicit.

The proof supplies evidence toward these goals. It does not deliver production services.

## Candidates and evidence

The [proof results](https://github.com/plocher/kicad-primitives/issues/4#issuecomment-6352494608) record revisions, article hashes, limitations, and reproduction details.
The primary articles were the four Railroad symbol libraries, SPCoast root schematic, and GilroyCalTrain.
A frozen 21-file snapshot provided project context. All originals remained unchanged.

### A: Keep or extend sexpdata

The baseline used sexpdata 1.0.2 at `29170a5daed7c07a8d035856356416141210d963`, under BSD-2-Clause.
It has established donor usage and useful semantic helpers.
Its native serialization changed bytes in all six real files.
Its returned values do not retain the source representation needed for lossless edits.

An extension could address that gap, but requires work beyond a wrapper around `loads()`.
The proof did not evaluate such an extension.
Keeping it beside an independent structural scanner would violate the single-foundation requirement.

### B: Use parts2kicad's whitespace-aware tree

The proof used version 0.1.4 source at `7b00d7ce223379f03183cf40482667e608258dd1`, under MIT.
Its metadata declares Python 3.8+. Its native tree reproduced four of the six real files exactly.

It dropped escaped quotes in Railroad-Trackplan and GilroyCalTrain.
The defect also affected edits where the escaped content was unrelated to the selected field.
It accepted extra closing parentheses, including a bare closing parenthesis.
These are current defects, not proof that this architecture cannot work.
Selection would require repairs before it meets the agreed behavior.

### C: Use CircuitDK's lossless S-expression module

The proof used version 0.1.1 source at `aca240a0404f6bb2162bb60257f7b1f0c756db06`, under MIT.
Its distribution is `circuitdk-lossless-sexpr`. Its import name is `lossless_sexpr`.
It has no declared runtime dependencies. Its metadata requires Python 3.11+.

It retains raw tokens, whitespace, source spans, and unknown structure.
All six real no-op cases preserved bytes. All five available Description edits preserved every other byte.
Each targeted case included a second edit after reparsing.
The root schematic had no Description property, so that edit was not exercised.

Seven lexical cases passed: escaped quotes, backslashes, Unicode, CRLF, number spellings, opaque nodes, and an unrelated escaped string.
All four malformed-input cases and the overlapping-edit rejection passed.
With the KiCad checks below, the Python 3.11 run recorded 79 passing observations and one unavailable target.
These observations cover the stated cases, not all KiCad syntax or operations.

The module returns an immutable document containing source text and structure.
Edits produce text. The caller must parse that text to get an updated structural view.
It does not supply KiCad domain models, general insertion formatting, or filesystem write safety.

### D: Implement a new focused parser

A new parser could directly meet the required representation contract.
It would make this project responsible for lexical rules, diagnostics, and maintenance from the start.
No new parser was implemented in the proof.
Candidate C already demonstrates the central requirements, so current evidence does not justify that extra work.

### Weighing the candidates

All 30 unchanged upstream tests passed under Python 3.10.22 and 3.11.17.
Those tests alone did not expose the real-file failures in A and B.

C is the only tested candidate that passed the full exercised preservation and insertion set without source changes.
A requires a source-preserving extension. B requires correctness repairs. D adds parser maintenance.
Choose C, with compatibility and integration work explicit.

## Implementation contract

### One private structural foundation

Use `lossless_sexpr` internally for structure, source retention, and edit spans.
Functional services interpret the parts they need.
Derived models must not become a separately parsed, independently writable account of the same source.
Do not retain sexpdata as a second runtime parser solely to preserve donor interfaces.

Use spans from the current representation.
Reparse changed text before subsequent structural queries or edits.
Do not reuse spans from an older source state.
The proof's two successive targeted edits exercise this requirement.

Keep dependency types and edit mechanisms out of public interfaces.
Private module names and public function signatures remain undecided.

### Source-preserving writes

Reuse original source for unchanged content.
Format only created or changed content, with KiCad's save output as the reference.
Do not serialize the whole semantic model merely to change one field.
Do not normalize the whole document implicitly through KiCad.

Prevent unintended newline conversion.
The tested library's spans index Python characters, not UTF-8 bytes.
The proof used byte I/O and explicit UTF-8 decoding and encoding.
Production file handling must preserve that distinction.

Input syntax validation and operation-specific preconditions remain necessary.
An unsupported or unsafe operation must fail before modifying original files.
This does not impose universal cache freshness or select a multi-file transaction design.

### Ordered insertion: W4-ORDER-01

The [ordering requirement](https://github.com/plocher/kicad-primitives/issues/4#issuecomment-6351903705) pins KiCad 10.0.1 source at `2db9e5a72b7cf1e71bb8dff5257a88d4b41f812f`.

- `eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr.cpp:435-459` saves schematic items by ascending item type, then UUID.
- `include/kiid.h:129-132` delegates UUID comparison to the underlying UUID value.

Within an already KiCad-ordered placed-symbol section, insert a new symbol at its UUID position.
Position, reference, unit number, and insertion order are not sort keys.
Preserve existing blocks, UUIDs, and their relative order.
Do not sort unrelated or opaque content.

The proof cloned a real single-unit Bumper with new identities and retained project-instance context.
Beginning, middle, and end insertions preserved every original block.
Removing the inserted bytes recovered the exact input.
Reference order deliberately disagreed with UUID order.

KiCad accepted all three outputs and left them byte-identical on two successive forced resaves.
A negative control appended the middle-UUID symbol at the end.
KiCad moved it and produced exactly the correctly ordered output.

This validates placed-symbol insertion in the tested format, not every item type or unsupported format.
The experiment reused an existing block's formatting. General node generation remains implementation work.

### Operation-specific verification

- **No-op:** exact byte equality.
- **Targeted edit:** required changes are present, untouched content is unchanged, and the operation's postconditions hold.
- **Connectivity-preserving edit:** the above guarantees plus unchanged connectivity.
- **Intentional electrical edit:** validate the requested electrical change rather than require unchanged connectivity.

An allow list permits a change. It does not prove a required change happened.
Netlist equality does not establish preservation of all document properties or presentation.

Record source preservation separately from KiCad normalization stability.
KiCad acceptance, equality after the first forced save, and stability after the second save are separate observations.
The proof passed those checks for six baselines, five property edits, and three correctly ordered insertions.
It did not measure electrical correctness or ERC/DRC results.

### Dependency and Python treatment

The first proof imported reviewed, pinned source without packaging hooks.
Before declaring the dependency, the published 0.1.1 wheel and source archive were inspected.
Both contain exactly the same seven parser modules as the tested revision.
The artifact hashes match PyPI's published SHA-256 values:

- Wheel: `5a41a4f4d8b83e6d43b449c281e08ceb66ca8c6ffb0b09c5f398d609f860108f`.
- Source archive: `3337b298b30916bc196137dc5f9c9a8c23eebee0225bca787b424594a8199068`.

The wheel includes the MIT license, declares Python 3.11+, and has no runtime dependencies.
It was installed into a fresh Python 3.11.17 environment, without running source-build hooks.
The installed release passed its six upstream tests and all 79 exercised acceptance observations.
One Description case remained unavailable because the root sheet lacks that property.
All original designs and snapshots remained unchanged.
This repeats the real-file, localized-edit, insertion, negative-control, and KiCad-resave checks against the actual release.

Use the unmodified upstream dependency rather than a local fork.
Retain MIT notices if source is ever copied.

The owner reassessed ADR 0001's Python floor and selected Python 3.11.
The alternatives considered were:

- **Require Python 3.11+:** follow declared upstream support without a fork or local metadata override.
- **Retain Python 3.10+:** seek upstream-supported metadata and compatibility, then verify the distribution on 3.10.
- **Fork or vendor:** accept ongoing source and compatibility maintenance. The current evidence does not justify this for metadata alone.

The pinned source, upstream tests, and shared non-KiCad measurements passed unchanged on Python 3.10.22.
No code-level need to raise the floor was demonstrated.
That supports an upstream compatibility request, not a claim of supported distribution installation.

Python 3.11 follows the upstream support declaration without a fork, metadata override, or upstream-change dependency.
The owner selected it explicitly, not because the proof demonstrated a 3.10 runtime failure.
The identity record, package metadata, and guidance now require Python 3.11+.

### Donors and consumers

Port useful behavior and its tests, refactoring representation-dependent code as required.
Do not first build another shared service architecture in Subdivision.
Keep Railroad-specific policy, urgent dated scripts, and migration adapters in the consumer.
A ready capability gets a consumer issue with the freeze-and-replace recipe.
Package implementation does not wait on that migration.

## Consequences and open work

The decision replaces competing S-expression readers and text scans inside the package with one structural foundation.
It does not require immediate consumer migration or make the intended package scope complete.

Further work includes supported-format intake checks, KiCad-specific formatting, and safe persistence.
Performance, deep nesting, general insertion, and additional file types need evidence as their services are implemented.
Do not expose the representation as an escape hatch for missing public services.

Keep the proof outside the shipped package.
The [runner](https://github.com/plocher/kicad-primitives/blob/62a0b890ab3f948f53e49e8270c13a68e4c04f0f/experiments/write_representation.py) and [compact result record](https://github.com/plocher/kicad-primitives/blob/62a0b890ab3f948f53e49e8270c13a68e4c04f0f/experiments/write_representation_results.json) are captured on `prototype/write-representation`.
Commit `62a0b890ab3f948f53e49e8270c13a68e4c04f0f` retains the experiment without merging it into the decision branch.
The ticket records local evidence locations. Raw scratch data remain local. No original designs are committed with the proof.

This decision does not resolve the job/session seam, complete lift inventory, CLI locator policy, or 1.0 completeness.
Those remain their own tickets and owner decisions.
