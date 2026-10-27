# Symbol libraries

## Scope

[ADR 0008](adr/0008-artifact-objects-and-explicit-persistence.md) sets the package-wide artifact-object editing direction.
The library owns live editable Symbol, SymbolBody, and SymbolPin objects.
Edits change pending source. Only an explicit `save()` writes that source.

`kicad_primitives.symbols.SymbolLibrary` opens one explicit `.kicad_sym` path.
It does not discover libraries, open a project, or edit schematic caches.
The optional SVG export invokes KiCad on a temporary copy.
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
for prop in declared.attributes:
    print(prop.name, prop.value, prop.is_private)

effective = library.resolve("Part")
for prop in effective.attributes:
    print(prop.name, prop.value, prop.origin_symbol)
for body in effective.bodies:
    print(body.unit, body.body_style, body.origin_symbol)
    for pin in body.pins:
        print(pin.number, pin.name, pin.electrical_type, pin.x, pin.y)
    for rect in body.rectangles:
        print(rect.start_x, rect.start_y, rect.end_x, rect.end_y)
    for text in body.texts:
        print(text.text, text.x, text.y, text.rotation)
```

`SymbolAttribute` holds one named value and its declaration provenance.
Symbol, SymbolBody, and SymbolPin are stable source-backed handles.
Attributes, rectangles, and body texts are immutable inspection values.
KiCad stores attributes in `(property …)` nodes.
A live handle shows current values after edits and symbol renames.
A deleted symbol or pin handle raises `StaleSymbolError`, even after recreation under the same name or number.
The read-only `SymbolDefinition` from `resolve()` is an immutable inheritance view, not an editing target.
Stroke/fill, fonts, unrelated metadata, and unrecognized nodes remain in the source without a public parser escape hatch.
The service exposes attribute visibility/autoplace/position, pin position/orientation/length/shape/hidden state, and minimal rectangle/text geometry—not a full graphics or text-effects model.

`symbol(name)` is declared content, including empty values.
`resolve(name)` follows same-library parents in either file order and retains the origin of inherited attributes and bodies.
KiCad's empty mandatory-attribute and keyword/filter inheritance rules are not a generic dictionary update.
Resolution fails explicitly for missing parents, cycles, duplicate effective attribute identities, or unsupported derived definitions with their own bodies.
Declared inspection remains available when effective resolution fails.

Attributes are an ordered tuple, not a dictionary: repeated names remain visible.
`symbol.attribute(name)` returns one occurrence, raises `KeyError` if absent, and raises `AmbiguousAttributeError` if ambiguous.
Mandatory names (Reference, Value, Footprint, Datasheet, Description) use KiCad's case-insensitive identity; custom names are case-sensitive.
The `private` modifier is distinct from an attribute literally named `"private"`.

Bodies retain their `(unit, body_style)` identity.
Zero means common content, not an additional placed unit/style.
Choose the body style your client needs; do not sum alternate styles into a pin count or join pins by name alone.
There is intentionally no lossy, flattened `.pins` adapter.

## Edit, preview, save

Work on a disposable copy while trying the recipe.

```python
from kicad_primitives.symbols import SymbolLibrary

library = SymbolLibrary.open("Example.kicad_sym")
part = library.symbol("Part")
part.set_attribute("Description", 'Updated description with "quotes"')
assert part.attribute("Description").value == 'Updated description with "quotes"'
part.set_attribute("Role", "DEVICE")
part.add_attribute("KLC_S3.3", "reason", private=True)
part.delete_attribute("Role")
body = part.body(1, 1)
pin = body.add_pin("2", "OUT", "output", x=5.08, y=0.0, rotation=180.0, length=2.54)
pin.set(name="Y", hidden=True)
pin.delete()
shared = part.ensure_body(0, 1)  # shared body, not artwork copied into every unit
shared.add_rectangle(start=(-2.54, 2.54), end=(2.54, -2.54))
shared.add_text("LABEL", x=0.0, y=3.81)
library.export_svgs("/tmp/symbol-svgs")  # kicad-cli inspection hook; optional kicad_cli=
library.create_symbol("Empty")
library.create_symbol("Child", extends="Part")
library.copy_symbol("Part", "PartCopy")
other = SymbolLibrary.open("Other.kicad_sym")
other.copy_symbol_from(library, "Part", "Imported")  # parent must exist if extends
library.rename_symbol("PartCopy", "Part2")
library.delete_symbol("Empty")
preview = library.to_bytes()  # No disk write.
library.save()               # Explicit write to the opened path.
library.close()              # No write. Requires a successful current decision.
other.discard()              # Abandon the unsaved Other import and exit.
```

`Symbol.set_attribute(name, value)` creates a missing declared attribute, updates a different value, or preserves equal-value bytes exactly.
`add_attribute` inserts a new declared attribute after the last attribute (or after `extends`/name when none exist).
Optional `private=True` writes the KiCad private modifier.
Inserted nodes use a minimal `(at 0 0 0)` body and match the symbol's newline and indent style when the definition is multi-line; compact single-line symbols stay single-line.
`delete_attribute` removes one unambiguous declared attribute and its leading separator.

`Symbol.body(unit, body_style)` selects a declared body.
`SymbolBody.add_pin` creates a pin there. `SymbolBody.pin(number)` selects a live pin for `set()` or `delete()`.
They do not create bodies, collapse alternate body styles, or edit a parent.
`add_pin` requires coordinates (`x`, `y`); optional `rotation` (default `0`), `length` (default `2.54`), `shape` (default `"line"`), and `hidden`.
`SymbolPin.set()` updates only the fields you pass. Equal values are a lexical no-op.
Pin electrical type and shape must be single sexpr tokens (no spaces).
Duplicate pin numbers on the same body fail on insert; ambiguous numbers fail on edit/delete.

Graphics **B anchors** (not full artwork-editor parity):
`ensure_body` creates an empty `(unit, body_style)` body when missing (no-op when present).
Prefer **unit 0** for shared boxes/text instead of copying the same artwork into every placed unit.
`SymbolBody.add_rectangle` and `add_text` insert minimal geometry and text on that body.
`export_svgs` writes SVG via private `kicad-cli` discovery (explicit path, `KICAD_CLI`, platform defaults, `PATH`); it exports current in-memory bytes through a temp file. It is an inspection hook for contact-sheet style checks, not an HTML product.

Private modifiers, placement/effects on untouched attributes, other definitions, newline spelling, and unrelated bytes survive unchanged.
Setting an already equal value is a lexical no-op, even if its source escape spelling is noncanonical.
Each changed edit reparses before further queries/edits; callers never manage spans.
Edits are all-or-nothing in memory, not a public multi-edit transaction.

`set_attribute` always targets this symbol's declaration, including when a parent provides an inherited value.
Use `add_attribute` for create-only behavior or a private modifier.
`add_attribute` fails when the identity already exists (including mandatory case-insensitive clashes).
No parent is edited implicitly. Deleting a local override leaves any inherited effective value visible through `resolve()`.
Same-library create/rename/delete/copy are supported; rename rewrites body names and in-library `extends`.
Delete refuses when another symbol still extends the target.
Cross-library `copy_symbol_from` copies a declared definition into this library;
`extends` is kept and the parent must already exist in the destination (copy
parents first). Path discovery may use library tables; this method takes opened
libraries only.
Unit restructuring beyond `ensure_body` remains outside this surface.
Changing a declared empty mandatory attribute changes its declared value; inspect `resolve()` separately to understand the effective inherited value.
Generic attribute values are not validated against Railroad or procurement policy.

Writes support library format `20251024` (KiCad 10), not the generator-version string.
Older compatible structures can be inspected read-only; the older donor fixture is covered, not every historical variation.
Future formats and older-format writes fail explicitly. A read-only library can still be previewed with `to_bytes()`.
Invalid UTF-8, malformed required structure, non-finite coordinates, or ambiguous edit targets fail rather than silently dropping content.
Replacement values must be strings without NUL and must encode as UTF-8.

## Limits

- No library discovery, project open, or schematic cache edit on this surface.
- No unit split/restructure beyond `ensure_body` on this surface.
- `copy_symbol_from` does not open tables or resolve nicknames; pass opened libraries.
- `ensure_body` creates empty bodies only; it does not restructure multi-unit definitions.
- Rectangle/text inserts are minimal geometry; stroke/fill and full text-effects authoring stay out of scope.
- `export_svgs` needs a resolvable `kicad-cli`; pure file edits do not.
- No public parser, span, node, or `cli` module types.

## Persistence and errors

### Explicit decisions and terminal exit
`path` reports the artifact's current destination. `is_modified` compares pending bytes with the successful open/save baseline.
`save()` and `save_as(path)` settle the current state only after successful persistence.
`close()` initially errors even for a clean, never-edited library.
A successful save/save-as authorizes close for that current state.
Later edits invalidate the decision. Exact no-op edits do not.
Every failed save/save-as clears the decision, including a failed clean preflight after a previous success.

`discard()` is terminal exit without writing. It is not rollback, reload, or a baseline reset for continued editing.
Close and discard invalidate owned Symbol/Body/Pin handles.
Operational access then raises an explicit lifecycle or stale-handle error.
`path`, `is_closed`, and previously captured immutable inspection values remain diagnostic data.
Close is idempotent after terminal exit. There is no implicit persistence or finalizer.
Open a new artifact to start another editing lifetime.

### Same-location save and native backup

`save()` compares disk bytes with the last successful open/save baseline.
External changes or deletion raise `FileConflictError`, even for a no-op save.
Reopen and reconcile external edits; do not blindly retry with a new baseline.
Current-format no-op saves perform no replacement.

Changed saves use a same-directory temporary file, preserve permission mode, flush/fsync output, recheck the baseline, and atomically replace the original.
Before that replacement, changed symbol libraries capture the prior source as native `Foo.bak`.
The backup replaces the extension. It does not append `.bak` to `Foo.kicad_sym`.
Exact no-op saves replace neither source nor backup.
Backup links, multiply linked files, unwritable targets, and source/backup collisions fail before the original write.
Backup failure aborts the original save.
The [ADR 0008 native source record](adr/0008-artifact-objects-and-explicit-persistence.md#native-single-file-symbol-backup) pins the KiCad 10.0.1 behavior.

When the source replacement fails, recovery restores the prior backup or removes the new backup only if its installed identity/version is unchanged.
Recovery never overwrites or deletes a concurrent third-party backup version.
If safe recovery cannot complete, `FileConflictError` identifies any retained `.recovery.*.tmp` prior-backup file.
Keep that file for manual reconciliation. This is not a crash-atomic two-file transaction.
Same-location `save()` refuses symlinks and multiply linked files.
They remain readable and can be forked with `save_as()`.
The writer does not bypass a source file with no write permission bits.
This preserves permission mode, not every platform-specific ACL, extended attribute, ownership detail, or inode identity.

OS errors propagate. A failed save leaves validated edits in memory for inspection and retry; the baseline advances only on success.
These are optimistic single-file safeguards, not a filesystem transaction, crash-durability guarantee, or lock/session protocol.
There is still a final check/replace race with an arbitrary external writer.
Do not save concurrently with KiCad's symbol editor or another writer.

### Safe single-file save-as
`save_as(path)` writes one new destination, then rebinds the existing artifact and handles only after success.
Original bytes and permissions remain unchanged. The new file retains the source permission mode.
The destination must not exist, even as a symlink. A racing destination is not overwritten.
Its existing parent directories must not be symlinks, and its destination directory must permit writing.
No parent directories are created. Use a canonical destination directory.

Save-as can fork a read-only library or readable linked source because it does not overwrite that source.
It still checks the captured source-byte baseline and rejects external changes or deletion without refreshing pending content.
A failed save-as retains the prior path, baseline, and pending changes. It does not authorize close.
A new destination needs no backup. A subsequent changed `save()` there creates its own `.bak`.
Project same-location ZIP history is separate from this single-file operation.
Bounded Project save-as is a separate operation; Git `.history` support remains deferred.

Errors exported from `kicad_primitives.symbols`:
- `InvalidLibraryError`: invalid syntax or required structure.
- `UnsupportedOperationError`: unsupported format/operation, duplicate `add_attribute` / `add_pin` identity, or unsafe replacement target.
- `AmbiguousSymbolError` / `AmbiguousAttributeError` / `AmbiguousPinError`: non-unique identity.
- `InheritanceError`: effective definition cannot be established.
- `FileConflictError`: opened file changed or disappeared.
- `StaleSymbolError`: an editable symbol, body, or pin no longer belongs to live source.
- `LibraryLifecycleError`: closed library or missing current successful close decision.
- `KicadCliNotFoundError`: `export_svgs` could not resolve `kicad-cli`.
- `SymbolLibraryError`: shared base for the package errors.

Missing symbol/attribute/body/pin lookup raises `KeyError`; filesystem errors remain ordinary `OSError` subclasses.
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
