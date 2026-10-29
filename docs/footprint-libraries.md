# Footprint libraries

## Scope

[ADR 0009](adr/0009-primitives-not-an-executive.md) fixes the shape of this surface.
A `.pretty` library is a directory of independent `.kicad_mod` files, not one file.
The model follows KiCad's footprint library editor: a cached table of contents on one side, one live object per opened footprint, edit marks, and a close decision chosen at open.

`kicad_primitives.footprints.FootprintLibrary` is the directory.
`kicad_primitives.footprints.Footprint` is one file with the full lifecycle: open, read, modify, validate, write, close.
Every public operation does one job. Nothing here runs KiCad, verifies connectivity, archives, or checks peer locks.
The package remains pre-alpha (`0.0.0` informational).

## Surface (ADR 0006 A)

- **Supported:** open by registered nickname or path; cached `summaries` with explicit `refresh()`; per-file `failures`; live `footprint(name)`; immutable `Pad` values; `pad_count`, `unique_pad_count`, and `matches_filters`; attribute set, add, and delete; `validate()`; `save(overwrite=False)`, `save_as(path, overwrite=False)`, `discard()`, `close()`, and `with`; immediate `create`, `copy`, `copy_from`, `delete`, and `rename`; library `on_close` of `save`, `discard`, or `raise`.
- **Defined, explicit failure:** edits, `validate()`, and writes on any format other than `20260206`; future formats on read; a file that changed or disappeared since it was read, unless `save(overwrite=True)`; links and read-only files on same-location save; ambiguous attribute identity; invalid names.
- **Deferred past 1.0:** pad, graphics, 3D-model, and geometry editing; fuzzy search scoring; lineage comparison (consumer logic or [#34](https://github.com/plocher/kicad-primitives/issues/34)); SVG export of footprints through this surface.

## Open

```python
from kicad_primitives.footprints import FootprintLibrary
from kicad_primitives.tables import LibraryTables

library = FootprintLibrary.open("/path/to/Resistor_SMD.pretty")
tables = LibraryTables.open(config_home="/path/to/kicad/10.0")
same = FootprintLibrary.open("Resistor_SMD", tables=tables)   # registered nickname
assert same is library
```

Every `Path` is a directory path. With explicit `tables`, a `str` is first tried as a registered footprint nickname; an unregistered `str` is a path.
Without `tables`, a `str` that names an existing path is that path at once, and the default `LibraryTables.open()` context is consulted only when it does not; a missing nickname or a malformed or unreadable table then falls back to the string as a path. Pass a `Path` to skip nickname lookup altogether.
The library binds to the resolved real path of the directory (`library.path`), so a library reached through a symlinked parent still creates, copies, renames, and saves-as.
The same directory opens to the same object until it is closed or discarded. A second `open()` of an open library with a different `on_close` raises `ValueError`; the first open's decision stands.
Opening parses every `.kicad_mod` once. A directory that does not exist raises `NotADirectoryError`. `open()` is the only constructor.

## Use

### Summaries

```python
for row in library.summaries:
    print(row.name, row.footprint_type, row.pad_count, row.unique_pad_count, row.tags)
smd = [row for row in library.summaries if row.footprint_type == "smd"]
two_pin = [row for row in library.summaries if row.unique_pad_count == 2]
candidates = [row for row in library.summaries if row.matches_filters(["R_*", "Resistor_SMD:*0603*"], nickname="Resistor_SMD")]
for failure in library.failures:
    print(failure.name, failure.error)
library.refresh()
```

`summaries` is a sorted tuple of immutable `FootprintSummary` rows, cached at open.
Clients filter and sort them as plain data without opening anything.
`name` is the file stem, which is the footprint's identity in KiCad 10.0.1. `declared_name` is the name atom inside the file; a mismatch loads under the stem, as KiCad does.
`footprint_type` is `smd`, `through_hole`, or `unspecified`; `flags` holds the other `(attr …)` tokens such as `exclude_from_bom`.
`attributes` are the `(property …)` values (`FootprintAttribute`: name, value, layer, hidden). Mandatory names (Reference, Value, Datasheet, Description) use KiCad's case-insensitive identity; custom names are case-sensitive.
`pad_count` counts every pad node, including NPTH and unnamed mechanical pads. A pad without a `(layers …)` node keeps KiCad's default layer set (`*.Cu *.Mask` for through-hole and NPTH, `F.Cu F.Paste F.Mask` for SMD and connect; `pcbnew/pad.cpp:107, 368-389`).
`unique_pad_count` is KiCad 10.0.1 `FOOTPRINT::GetUniquePadCount(DO_NOT_INCLUDE_NPTH)`: unique non-empty numbers on pads with at least one copper layer, NPTH excluded. A ganged number such as `A1_B12` counts once. This is the count KiCad's pin-count filter uses.
`matches_filters(patterns, nickname=None)` applies symbol `ki_fp_filters` as KiCad does: anchored, case-insensitive wildcards (`?`, `*`); a pattern with `:` is matched against `nickname:name`. No patterns means every footprint matches.

A file that does not read as a footprint fails for that footprint only. It appears in `failures` with its error text; the rest of the library loads. A dangling `.kicad_mod` link is listed and reported the same way, as KiCad lists it.
Nothing refreshes by itself. `refresh()` rescans the directory and re-parses files whose size, mtime, or inode changed; new files appear and deleted files disappear. Open footprints are not touched.

### Live footprints

```python
footprint = library.footprint("R_0603_1608Metric")
print(footprint.description, footprint.version, footprint.flags)
for pad in footprint.pads:
    print(pad.number, pad.pad_type, pad.shape, pad.x, pad.y, pad.rotation, pad.width, pad.height, pad.layers, pad.drill)
print(footprint.attribute("Value").value)
assert library.footprint("R_0603_1608Metric") is footprint
```

`footprint(name)` reads the file from disk and returns the same object while it is open. A missing file raises `KeyError`; an unreadable file raises its parse error.
`Pad` and `PadDrill` are immutable values: number, type token, shape, position, rotation (0 when absent), size, layers, and drill (`width`, `height`, `oval`). `pad.on_copper` tells whether any layer is copper.
`footprint.summary` is a row for the current in-memory content; `library.summary(name)` is the cached row from disk.

### Edit, validate, save

Work on a disposable copy while trying the recipe.

```python
footprint = library.footprint("R_0603_1608Metric")
footprint.set_attribute("Value", "R_0603")          # create if absent, update if different, no-op if equal
footprint.add_attribute("MPN", "RC0603FR-0710KL")   # create only; hidden, on F.Fab
footprint.delete_attribute("MPN")
assert footprint.is_modified and library.is_modified
preview = footprint.to_bytes()      # No disk write.
footprint.validate()                # Format, re-parse, encodability, destination. No KiCad.
footprint.save()                    # One file. Conflicts raise.
footprint.save(overwrite=True)      # The explicit way through a conflict.
footprint.save_as("/path/to/Other.pretty/R_0603.kicad_mod")
footprint.close()                   # Saves first only when modified.
```

Edits replace only the nodes they mean to. A changed value replaces its value atom; an inserted attribute follows the last attribute in the file's indent style with `(at 0 0 0)`, `(layer "F.Fab")`, `(hide yes)`, and a default font; a deleted attribute takes only its node and leading separator. Everything else round-trips byte for byte.
`is_modified` is a flag: a real change sets it, an equal-value set leaves it alone, a successful save clears it. The footprint keeps a content fingerprint of the file it read, not a copy of the bytes.

`validate()` raises `UnsupportedOperationError` for a format other than `20260206` or a destination that is a link or multiply linked file, `InvalidFootprintError` when the pending source does not parse back as one footprint, `UnicodeEncodeError` for unencodable content, `PermissionError` for a destination or directory without write permission, and other `OSError` subclasses for a missing or symlinked destination directory. Whatever `validate()` passes, `save()` refuses only on content conflict. It writes nothing, so a client dry run is validate without save.

`save()` runs `validate()` and then keeps the ADR 0009 write promises:
- **No silent overwrite.** The file on disk must be the file this footprint read or last wrote; otherwise `FootprintConflictError` names the file and the edits stay in memory. `save(overwrite=True)` writes anyway, and also recreates a deleted file.
- **No partial file.** The write is a same-directory temporary file renamed into place; a failed write leaves the original untouched.
- **No stray KiCad files.** The temporary name is a dotfile with a `.tmp` suffix.
- **No backup.** KiCad writes no backup when it saves a footprint, and neither does this.
Links and files without write permission are refused, not bypassed; fork them with `save_as`.

`save_as(path, overwrite=False)` writes one new `.kicad_mod` and rebinds the footprint only after success. As KiCad's Save As does, the written content carries the new stem as its internal name, and as its Value when the Value equalled the old stem; a failed save-as leaves the pending content, name, and path as they were. The destination must not exist unless `overwrite=True`; its parent must be an existing, writable, non-symlink directory. The original file is not changed. A destination inside an open library, this one or another, joins that library under the new stem (`footprint.library` changes accordingly); a destination that is not an open library detaches the footprint (`footprint.library` becomes `None`) and the client closes it. A destination that another open footprint already owns raises `FootprintLifecycleError` before anything is written, so one file never has two live handles.

### Directory operations

```python
library.create("New_Part")                   # minimal format-20260206 file, now
library.copy("R_0603_1608Metric", "R_0603_Custom")
other = FootprintLibrary.open("/path/to/Other.pretty")
library.copy_from(other, "C_0402_1005Metric", "C_0402")
library.rename("R_0603_Custom", "R_0603_Mine")
library.delete("New_Part")
```

These take effect at once; they are not content edits and set no edit mark.
`create` writes Reference `REF**`, Value equal to the name, no pads, and no graphics. KiCad 10.0.1 loads it and adds its own defaults on resave.
`copy` and `copy_from` read the source file from disk, not an open handle's pending edits, and rewrite the internal name and a Value that equalled the source name, as KiCad's duplicate does.
`rename` follows KiCad: write the new file with the internal name and a matching Value rewritten, then delete the old file. An open handle is rebound to the new path with the same rewrite applied to its pending content; its edit mark is unchanged. When an open handle exists and the file on disk is no longer the file it read, `rename` raises `FootprintConflictError` and writes nothing; the client reopens or saves with `overwrite=True` first. If deleting the old file fails after the new one was written, both files exist and `refresh()` lists both; nothing is lost.
`delete` removes the file; an open handle becomes stale.
Existing destinations raise `FileExistsError`; missing sources raise `KeyError`; names with path separators, `:`, NUL, or surrounding whitespace raise `ValueError`.

### Close, discard, and `with`

The library has nothing of its own to write. Its close is a decision about its open footprints, chosen once at open:

```python
with FootprintLibrary.open("/path/to/Lib.pretty", on_close="save") as library:
    library.footprint("A").set_attribute("Value", "A1")
# Normal exit: close() saved A. An exception inside the block: discard(), nothing written.
```

- `save` (default): save every modified open footprint, then close all. A failed save propagates and the library stays open.
- `discard`: drop open edits and close all.
- `raise`: refuse while any open footprint is modified, naming them, so the client decides per footprint.

`Footprint.close()` on a clean footprint writes nothing; on a modified one it runs `save()` and stays open if that fails.
`discard()` is terminal exit without writing. Close and discard invalidate the handle; a later close is idempotent.
Open then close never writes and never fails. Mutations, discard, and finalizers never write.

## Limits

- Pads, graphics, 3D models, and geometry are read-only values on this surface.
- Tags and description are read-only text; `(descr …)` and `(tags …)` are not attributes.
- The library caches summaries; it does not watch the directory. Call `refresh()` for a current view.
- Fuzzy search, lineage comparison, and nickname choice are client logic. Discovery and URI spelling are on [tables.md](tables.md).
- No public parser, span, node, or `cli` module types.

## Errors

Exported from `kicad_primitives.footprints`:
- `InvalidFootprintError`: invalid syntax or required structure.
- `UnsupportedOperationError`: read-only or future format, duplicate `add_attribute` identity, or an unsafe same-location target (link, multiply linked file).
- `AmbiguousFootprintAttributeError`: repeated attribute identity on an edit or lookup.
- `FootprintConflictError`: the file changed or disappeared since it was read or written, on `save()` or on `rename` of an open footprint.
- `FootprintLifecycleError`: closed, discarded, or deleted footprint or library; `on_close="raise"` with modified footprints; a `save_as` destination that another open footprint owns.
- `FootprintLibraryError`: shared base for the footprint errors.

Missing footprint or attribute lookup raises `KeyError`; existing destinations raise `FileExistsError`; a second `open()` with a different `on_close`, a bad name, or a direct constructor call raise `ValueError`/`TypeError`; other filesystem errors are ordinary `OSError` subclasses.

## Tests

The normal suite needs no KiCad install:

```bash
uv run python -m unittest discover -s tests -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict --follow-untyped-imports src/kicad_primitives
```

Fixtures are hand-written format-20260206 files in `tests/fixtures/footprints/Fixture.pretty` (NPTH, mechanical `MP`, ganged `A1_B12`, oval drill, paste-only pad, mismatched internal name, legacy format, future format, broken file). Read-model gates are in `tests/functional/test_footprint_libraries.py`; edit and persistence gates in `tests/functional/test_footprint_persistence.py`. The EagleLib2KiCad enumeration assertions (stem identity, sorted listing, raw pad count) are lifted there.

The opt-in native gate takes explicit `.pretty` paths, a new output directory, and an explicit `--kicad-cli`. It edits, creates, copies, and renames in a disposable copy and then renders the copy with `kicad-cli fp export svg`:

```bash
python tests/verify_footprint_libraries.py \
  --output /private/tmp/kp-fp-gate \
  --kicad-cli /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli \
  tests/fixtures/footprints/Fixture.pretty \
  /Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Resistor_SMD.pretty
```

The output directory must be a real path (macOS `/tmp` is a symlink and the writer refuses symlinked parents). Recorded KiCad 10.0.1 run: the fixture library (6 readable files plus created and renamed, 2 reported failures) and `Resistor_SMD.pretty` (67 plus created and renamed) rendered every footprint; every edit was an exact delta; originals were unchanged.
