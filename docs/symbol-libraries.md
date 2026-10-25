# Symbol libraries

## Scope

`kicad_primitives.symbols.SymbolLibrary` opens one explicit `.kicad_sym` path.
It does not discover libraries, open a project, edit schematic caches, or invoke KiCad.
The package remains pre-alpha (`0.0.0` informational). This is not the whole functional TOC.
Released donor dependencies wait for `1.0.0` on public PyPI ([ADR 0005](adr/0005-distribution-and-versioning.md)).

## Open and inspect

```python
from kicad_primitives.symbols import SymbolLibrary

library = SymbolLibrary.open("Example.kicad_sym")
print(library.version)
for symbol in library.symbols:
    print(symbol.name, symbol.extends)

declared = library.symbol("Part")
for prop in declared.properties:
    print(prop.name, prop.value, prop.is_private)

effective = library.resolve("Part")
for prop in effective.properties:
    print(prop.name, prop.value, prop.origin_symbol)
for body in effective.bodies:
    print(body.unit, body.body_style, body.origin_symbol)
    for pin in body.pins:
        print(pin.number, pin.name, pin.electrical_type, pin.x, pin.y)
```

Symbols, properties, bodies, and pins are immutable dataclass snapshots.
Query again after editing; previous snapshots do not become live handles.
Graphics, fonts, unrelated metadata, and unrecognized nodes remain in the source without a public parser escape hatch.
The service exposes property visibility/autoplace/position and pin position/orientation/length/shape/hidden state, not a full graphics or text-effects model.

`symbol(name)` is declared content, including empty values.
`resolve(name)` follows same-library parents in either file order and retains the origin of inherited fields and bodies.
KiCad's empty mandatory-field and keyword/filter inheritance rules are not a generic dictionary update.
Resolution fails explicitly for missing parents, cycles, duplicate effective field identities, or unsupported derived definitions with their own bodies.
Declared inspection remains available when effective resolution fails.

Properties are an ordered tuple, not a dictionary: repeated names remain visible.
`symbol.property(name)` returns one occurrence, raises `KeyError` if absent, and raises `AmbiguousPropertyError` if ambiguous.
Mandatory names (Reference, Value, Footprint, Datasheet, Description) use KiCad's case-insensitive identity; custom names are case-sensitive.
The `private` modifier is distinct from a property literally named `"private"`.

Bodies retain their `(unit, body_style)` identity.
Zero means common content, not an additional placed unit/style.
Choose the body style your client needs; do not sum alternate styles into a pin count or join pins by name alone.
There is intentionally no lossy, flattened `.pins` adapter.

## Edit, preview, save

Work on a disposable copy while trying the recipe.

```python
from kicad_primitives.symbols import SymbolLibrary

library = SymbolLibrary.open("Example.kicad_sym")
library.set_property("Part", "Description", 'Updated description with "quotes"')
assert library.symbol("Part").property("Description").value == 'Updated description with "quotes"'
library.add_property("Part", "Role", "DEVICE")
library.add_property("Part", "KLC_S3.3", "reason", private=True)
library.delete_property("Part", "Role")
library.add_pin(
    "Part", 1, 1, "2", "OUT", "output", x=5.08, y=0.0, rotation=180.0, length=2.54
)
library.set_pin("Part", 1, 1, "2", name="Y", hidden=True)
library.delete_pin("Part", 1, 1, "2")
preview = library.to_bytes()  # No disk write.
library.save()               # Explicit write to the opened path.
```

`set_property` changes one existing declared value token.
`add_property` inserts a new declared field after the last property (or after `extends`/name when none exist).
Optional `private=True` writes the KiCad private modifier.
Inserted nodes use a minimal `(at 0 0 0)` body and match the symbol's newline and indent style when the definition is multi-line; compact single-line symbols stay single-line.
`delete_property` removes one unambiguous declared property and its leading separator.

`add_pin` / `set_pin` / `delete_pin` target one existing body by `(unit, body_style)` and pin number.
They do not create bodies, collapse alternate body styles, or edit a parent.
`add_pin` requires coordinates (`x`, `y`); optional `rotation` (default `0`), `length` (default `2.54`), `shape` (default `"line"`), and `hidden`.
`set_pin` updates only the fields you pass; equal values are a lexical no-op.
Pin electrical type and shape must be single sexpr tokens (no spaces).
Duplicate pin numbers on the same body fail on insert; ambiguous numbers fail on edit/delete.

Private modifiers, field placement/effects on untouched fields, other definitions, newline spelling, and unrelated bytes survive unchanged.
Setting an already equal value is a lexical no-op, even if its source escape spelling is noncanonical.
Each changed edit reparses before further queries/edits; callers never manage spans.
Edits are all-or-nothing in memory, not a public multi-edit transaction.

`set_property` does not insert a missing field; use `add_property`.
`add_property` fails when the identity already exists (including mandatory case-insensitive clashes).
No parent is edited implicitly. Deleting a local override leaves any inherited effective value visible through `resolve()`.
Symbol rename, unit restructuring, body create/delete, and cross-library copying remain outside this surface.
Changing a declared empty mandatory field changes its declared value; inspect `resolve()` separately to understand the effective inherited value.
Generic field values are not validated against Railroad or procurement policy.

Writes support library format `20251024` (KiCad 10), not the generator-version string.
Older compatible structures can be inspected read-only; the older donor fixture is covered, not every historical variation.
Future formats and older-format writes fail explicitly. A read-only library can still be previewed with `to_bytes()`.
Invalid UTF-8, malformed required structure, non-finite coordinates, or ambiguous edit targets fail rather than silently dropping content.
Replacement values must be strings without NUL and must encode as UTF-8.

## Limits

- No library discovery, project open, or schematic cache edit on this surface.
- No symbol rename, body create/delete, unit split, or cross-library copy on this surface.
- Pin ops require an existing `(unit, body_style)` body; they do not author shared unit-0 graphics.
- Inserted properties get a minimal position node only; full text-effects authoring is out of scope.
- No public parser, span, or node types.
- Graphics and full text-effects models are out of scope here.

## Persistence and errors

`save()` compares disk bytes with the last successful open/save baseline.
External changes or deletion raise `FileConflictError`, even for a no-op save.
Reopen and reconcile external edits; do not blindly retry with a new baseline.
Current-format no-op saves perform no replacement.

Changed saves use a same-directory temporary file, preserve permission mode, flush/fsync output, recheck the baseline, and atomically replace the original.
Symlinks and multiply linked files are readable but cannot be saved through this service.
The writer does not bypass a source file with no write permission bits.
This preserves permission mode, not every platform-specific ACL, extended attribute, ownership detail, or inode identity.

OS errors propagate. A failed save leaves validated edits in memory for inspection and retry; the baseline advances only on success.
These are optimistic single-file safeguards, not a filesystem transaction, crash-durability guarantee, or lock/session protocol.
There is still a final check/replace race with an arbitrary external writer.
Do not save concurrently with KiCad's symbol editor or another writer.

Errors exported from `kicad_primitives.symbols`:
- `InvalidLibraryError`: invalid syntax or required structure.
- `UnsupportedOperationError`: unsupported format/operation, absent declared `set_property` target, duplicate `add_property` / `add_pin` identity, or unsafe replacement target.
- `AmbiguousSymbolError` / `AmbiguousPropertyError` / `AmbiguousPinError`: non-unique identity.
- `InheritanceError`: effective definition cannot be established.
- `FileConflictError`: opened file changed or disappeared.
- `SymbolLibraryError`: shared base for the package errors.

Missing symbol/property/body/pin lookup raises `KeyError`; filesystem errors remain ordinary `OSError` subclasses.
No public signature or error requires dependency node/span types.

## Tests

### Normal suite and real-library verification

The normal suite uses unittest and has no donor-checkout, KiCad, or network requirement after package installation:

```bash
uv run python -m unittest discover -s tests -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict --follow-untyped-imports src/kicad_primitives
```

Fixture and assertion provenance is recorded in `tests/functional/test_symbol_inspection.py`.
Donor pin-contract and overview library assertions move here; the consumer's HTML controls and Railroad policy do not.
No new behave framework is introduced.

The opt-in runner accepts explicit paths. It refuses an existing output directory and invokes KiCad only on copies beneath the new directory:

```bash
python tests/verify_symbol_libraries.py \
  --output /tmp/new-symbol-proof \
  --kicad-cli /absolute/path/to/kicad-cli \
  /absolute/path/to/Example.kicad_sym
```

Omit `--kicad-cli` to run source/edit gates without KiCad.
The runner emits JSON input hashes, counts, and individual preservation/normalization observations.
It uses assertions as gates; do not run it with Python optimization (`-O`).

The [recorded KiCad 10.0.1 run](review/first-symbol-slice-results.json) covers 11 libraries, 2,230 inspected/resolved symbols, and 13 edited cases with quotes, backslashes, Unicode, and successive edits.
All package no-op bytes and edit deltas passed. Four installed libraries normalized on the first KiCad save; all baseline/edited second saves were stable, and normalized comparisons contained only the required edits.
KiCad trims leading Description whitespace, so the successful probes do not introduce leading whitespace when the original Description is empty.
The production editor preserves the literal requested value; it does not run KiCad or promise KiCad normalization stability for arbitrary values.
These are bounded library-level observations, not project connectivity, ERC, or universal format compatibility proof.
