# Library tables and resolution

## Scope

[ADR 0008](adr/0008-artifact-objects-and-explicit-persistence.md) requires in-memory edits and explicit persistence.
The current `apply`-based mutations described here do not yet follow that lifecycle.
They are implementation gaps, not the pattern for new editing interfaces.

`kicad_primitives.tables.LibraryTables` discovers, reads, resolves, and edits
KiCad **symbol** and **footprint** library table files (`sym-lib-table`,
`fp-lib-table`) in global config and optional project directories.

It expands `${VAR}` using KiCad environment data and project overrides, follows
nested `type "Table"` rows, and maps nicknames to filesystem paths.

It does **not** open symbol or footprint definition content, edit
`design_block_lib_table` as a product API, or replace KiCad’s UI. The package
remains pre-alpha (`0.0.0` informational).

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

### Add, remove, rename

Mutations target the **primary** table file for a scope (global config home or
project directory). They do not rewrite nested child table files unless you open
that path as the project/global table.

```python
tables.add_library(
    library_type="symbol",
    scope="project",
    nickname="Local",
    uri="${KIPRJMOD}/Local.kicad_sym",
    apply=True,  # False = plan only, no disk write
)
tables.rename_library(
    library_type="symbol",
    scope="project",
    old_nickname="Local",
    new_nickname="BoardLocal",
    apply=True,
)
tables.remove_library(
    library_type="symbol",
    scope="project",
    nickname="BoardLocal",
    apply=True,
)
```

- `apply=False` validates and returns a `LibraryMutationResult` without writing.
- Add creates a minimal table file when missing.
- Add refuses duplicate **direct** nicknames in that file (nested leaves are not
  collision-checked).
- Rename changes only the name token span of the matching direct row.
- Remove deletes only that direct `lib` node (and its leading separator).
- Untouched rows keep their source bytes; version headers and other fields stay
  in place for localized edits.

## Limits

- `design_block_lib_table` stays thin/optional and is not a first-class surface.
- Mutations edit one primary scope file; they are not a multi-file transaction
  with KiCad’s UI.
- Remote / plugin library types beyond ordinary path URIs are stored and
  returned, but path resolution still treats `uri` as a filesystem path after
  expansion.
- Cross-library symbol copy remains a separate symbols-surface concern once
  callers can resolve nicknames here.

## Errors

- `InvalidLibraryTableError`: unreadable or malformed table structure.
- `MissingLibraryError`: nickname not found for resolve/remove/rename.
- `AmbiguousLibraryError`: reserved for future same-scope conflicts (resolve
  currently takes the last leaf in the winning scope).
- `LibraryTablesError`: shared base.
- Ordinary `ValueError` for empty nicknames/URIs and duplicate add/rename targets.
- Ordinary `OSError` subclasses for filesystem failures.

## Tests

Donor gates from EagleLib2KiCad environment tests plus nested-table and
project-shadow cases live in
`tests/functional/test_library_tables.py`.

```bash
uv run python -m unittest discover -s tests -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict --follow-untyped-imports src/kicad_primitives
```

The normal suite needs no KiCad install or donor checkout after package
installation.
