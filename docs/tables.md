# Library tables and resolution

## Scope

[ADR 0008](adr/0008-artifact-objects-and-explicit-persistence.md) requires in-memory edits and explicit persistence.
Physical `LibraryTable` artifacts now own buffered source and editable `TableEntry` objects.
Edits do not write files. Clients choose save, save as, close (saves pending changes), or terminal discard.

`kicad_primitives.tables.LibraryTables` discovers, reads, resolves, and edits
KiCad **symbol** and **footprint** library table files (`sym-lib-table`,
`fp-lib-table`) in global config and optional project directories.

It expands `${VAR}` using KiCad environment data and project overrides, follows
nested `type "Table"` rows, and maps nicknames to filesystem paths.

It does **not** open symbol or footprint definition content, edit
`design_block_lib_table` as a product API, or replace KiCad’s UI. The package
remains pre-alpha (`0.0.0` informational).

## Surface (ADR 0006 A)

- **Supported:** config-home discovery; read and resolve global and project symbol and footprint tables; `${VAR}` expansion; nested `Table` rows; project shadowing; `find_libraries` under explicit roots; `portable_uri` spelling; `add_entry`, `rename`, `set_uri`, and `delete` on physical tables; `validate()`, `save()` with `overwrite`, `save_as()`, `discard()`, and `close()`.
- **Defined, explicit failure:** ambiguous direct nicknames on an editing target; duplicate add or rename targets; external changes since open or save, including the save that a dirty close runs.
- **Stored, not interpreted:** remote and plugin library types keep their rows, but resolution treats `uri` as a filesystem path.
- **Deferred past 1.0:** `design_block_lib_table` as a product API; remote and plugin resolution; multi-file table transactions.

## Open

```python
from kicad_primitives.tables import LibraryTables

tables = LibraryTables.open(config_home="/path/to/kicad/10.0")
# optional project tables + KIPRJMOD + project text_variables:
tables = LibraryTables.open(
    config_home="/path/to/kicad/10.0",
    project_directory="/path/to/board",
)

print(tables.config_home)
print(tables.project_directory)
print(dict(tables.path_variables))
print(tables.table_path("symbol", "global"))
```

When `config_home` is omitted, discovery order is:

1. `KICAD_CONFIG_HOME`
2. First platform candidate that already contains a table file
3. Preferred versioned default path (may be empty)

Platform candidates cover macOS Preferences, Linux `~/.config/kicad`, and
Windows `%APPDATA%\\kicad`, including versioned `10.0` / `9.0` / `8.0` folders.
There is no Mac-only hard-coded `${KICAD10_*}` contract.

## Use

### List and resolve

```python
for entry in tables.libraries("symbol"):
    print(entry.scope, entry.nickname, entry.uri, entry.resolved_path)

entry = tables.resolve("Device", library_type="symbol")
print(entry.resolved_path)
```

`libraries(library_type)` returns **leaf** libraries after nested `Table`
expansion, global rows then project rows. Nested table nicknames themselves are
not leaves.
Repeated includes expand again in row order. Only a table already on the active
include branch stops a cycle. A completed include does not suppress later includes.

`resolve(nickname, library_type=...)` selects one leaf path:

- Project-scope nicknames shadow global nicknames.
- Within the winning scope, the **last** expanded leaf with that nickname wins
  (later nested rows can override earlier ones).
- Missing nicknames raise `MissingLibraryError`.

### Path variables

Effective `${VAR}` values (later wins on the same key):

1. `kicad_common.json` → `environment.vars`
2. Project `.kicad_pro` → `text_variables`
3. Synthetic `KIPRJMOD` (project directory) and `KICAD_CONFIG_HOME`
4. Versioned directory aliases derived from `KICADn_MODEL_DIR` share roots
5. Process environment keys starting with `KICAD`, plus `KIPRJMOD`
6. Aliases again so env-provided roots still fill companion symbol/footprint dirs

URI expansion substitutes `${NAME}` up to 32 times.
Relative include and leaf URIs use one context base, not the containing table directory.
With `project_directory`, that base is the opened project directory.
Standalone resolution captures process CWD at `open()`, or accepts an explicit
`base_directory` argument. Later CWD changes do not change this captured base.
The `base_directory` property shows the effective base.
Do not supply both `project_directory` and `base_directory`.
Absolute URIs stay absolute. A missing winning path remains the winner.

KiCad 10.0.1 uses process CWD for both relative includes and leaf URIs.
Project-native checks run from the opened project directory.
The native control in `tests/verify_schematic_erc.py` checks this behavior and repeated
lookup without changing original designs.

### Find unregistered libraries and spell a portable URI

```python
found = LibraryTables.find_libraries("footprint", ["/path/to/libs", "/other/root"], "SPCoast_*")
registered = {entry.resolved_path for entry in tables.libraries("footprint")}
for path in found:
    if path not in registered:
        tables.table("footprint", "project").add_entry(path.stem, tables.portable_uri(path))
```

`find_libraries(library_type, roots, pattern="*")` lists candidate `*.kicad_sym` files or `*.pretty` directories under the roots you give. It reads nothing, descends every subdirectory except a `.pretty` directory itself, and filters the name without its suffix with a case-sensitive glob. Results are absolute and sorted and may include libraries that are already registered. A root that is not an existing directory raises `NotADirectoryError`. There are no default roots ([ADR 0009](adr/0009-primitives-not-an-executive.md)).

`portable_uri(path)` returns the spelling a table row would use: `${KIPRJMOD}/…` when the path is under the project directory, otherwise the longest matching absolute path variable from `path_variables` (equal values prefer a versioned `KICADn_*` name, then the alphabetically first), otherwise the absolute path. URIs use `/`. It chooses a spelling, not a nickname; registration stays `add_entry(nickname, uri)` and there is no `add_library` helper.

`SymbolLibrary.open` and `FootprintLibrary.open` accept a registered nickname with an optional `tables=` context; see [symbol-libraries.md](symbol-libraries.md) and [footprint-libraries.md](footprint-libraries.md).

### Select and edit physical tables
`table(library_type, scope)` returns a stable physical primary artifact.
`entries` includes all direct registrations, including nested table links and repeated names.
`entry(nickname)` selects one direct registration and rejects missing or ambiguous names.
Resolved `LibraryEntry` values from `libraries()` and `resolve()` remain immutable inspection values.

```python
table = tables.table("symbol", "project")
entry = table.add_entry("Local", "${KIPRJMOD}/Local.kicad_sym")
entry.rename("BoardLocal")
entry.set_uri("${KIPRJMOD}/BoardLocal.kicad_sym")
assert table.entry("BoardLocal") is entry
assert table.is_modified and tables.is_modified
preview = table.to_bytes()  # Full pending source. No disk write.
table.save()              # Persist this physical file only.
entry.delete()            # Pending removal. This handle becomes stale.
table.discard()           # Terminal exit. Pending removal is not written.
table.close()             # Idempotent after discard.
```

`add_entry` buffers a new direct row and returns its live handle.
It accepts `entry_type`, `options`, and `descr`. It rejects duplicate direct names.
`rename` and `set_uri` replace only their target atoms. Equal values preserve exact bytes.
`delete` removes only the selected row and its leading separator.
Raw rows retain disabled/hidden flags, opaque structured metadata, and original newline spelling.
A deleted handle never rebinds to a new row with the same nickname.
There are no context mutation commands, `apply` switches, or dry-run aliases.

A missing primary file has an empty buffered table. Neither access nor edits create that file.
An explicit `save()` creates the file without overwriting a racing destination.
For a nested `Table` row, `entry.included_table` returns its physical artifact through the same context.
For a leaf, it returns `None`.
Pending changes in a nested physical table affect this context's `libraries()` and `resolve()` results.
Each nested artifact saves or discards independently. Saving a root does not save its includes.
The context retains opened table snapshots. Open a new context to read external changes.

### Persistence and terminal exit
Each physical table has `path`, `to_bytes()`, `is_modified`, `validate()`, `save()`, `save_as(path)`, `discard()`, and `close()`.
`is_modified` is a flag that edits set (ADR 0009). An edit back to the original content leaves it set.
The table keeps a fingerprint (size and content hash) of what it read, not a copy of the bytes.
`table_path(type, scope)` reports the discovered primary location. `table.path` reports that artifact's current destination.
`tables.is_modified` aggregates pending state from open physical artifacts, not files that the context has never opened.

`close()` on a clean table writes nothing. A missing table that was never edited is not created.
`close()` on a dirty table runs `save()`, then exits.
If that save fails, `close()` raises and the table stays open with its pending changes.
`discard()` is terminal exit without writing, not rollback or reload.
Close and discard invalidate the artifact's editable entries. A later `close()` is harmless.
A `with` block closes on normal exit and discards on an exception.
Mutations, discard, and finalizers never write.

An existing clean table's `save()` writes nothing and checks nothing.
A changed `save()` runs `validate()`, then compares the disk file with the fingerprint.
A conflict raises `LibraryTableConflictError` and writes nothing, unless `save(overwrite=True)`.
Changed saves keep the single-file link and permission safeguards.
Table saves do not create an invented backup.
`save_as(path)` writes one new file, then rebinds this artifact only after success.
It refuses existing destinations, symlinks, missing parent directories, and symlink or unwritable destination parents.
Use an existing canonical destination directory. The operation does not create parents.
It leaves the original bytes and permissions unchanged and preserves the source permission mode on the new file.
Read-only sources and readable linked sources can be copied because save-as does not overwrite them.
Save-as still rejects an external change or deletion of the source since it was read.
Failures retain the prior path, pending source, and fingerprint for inspection or retry.
Table `revert()` is pending an owner decision (ADR 0011 D6 assigns library revert to #78).
Global and project tables can have the same basename. There is no combined context save-as layout.

## Limits

- `design_block_lib_table` stays thin/optional and is not a first-class surface.
- Each physical artifact writes one file. Includes and global/project tables do not form a multi-file transaction.
- Remote / plugin library types beyond ordinary path URIs are stored and
  returned, but path resolution still treats `uri` as a filesystem path after
  expansion.
- Cross-library symbol copy remains a separate symbols-surface concern once
  callers can resolve nicknames here.

## Errors

- `InvalidLibraryTableError`: unreadable or malformed table structure.
- `MissingLibraryError`: nickname not found for direct selection or resolution.
- `AmbiguousLibraryError`: repeated direct nickname on an editing target. Effective resolution still takes the last winning leaf.
- `LibraryTableConflictError`: physical source changed or disappeared since open/save.
- `LibraryTableLifecycleError`: closed or discarded artifact, or stale entry.
- `LibraryTablesError`: shared base.
- Ordinary `ValueError` for empty nicknames/URIs and duplicate add/rename targets.
- Ordinary `OSError` subclasses for filesystem failures.

## Tests

Donor gates from EagleLib2KiCad environment tests plus nested-table and
project-shadow cases live in
`tests/functional/test_library_tables.py`. Discovery and portable-URI gates
are in `tests/functional/test_library_discovery.py`.

```bash
uv run python -m unittest discover -s tests -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict --follow-untyped-imports src/kicad_primitives
```

The normal suite needs no KiCad install or donor checkout after package
installation.
