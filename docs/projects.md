# Projects: open, hierarchy, and text variables

`kicad_primitives.projects.Project` opens one KiCad project directory or an
explicit `.kicad_pro` path.
It establishes design context: root document paths, hierarchical schematic
files, and project `text_variables`.
It does not open schematic or PCB documents for inspection or edit, run
KiCad, or resolve library tables.
The package remains pre-alpha (`0.0.0` informational).

## Open a project

```python
from kicad_primitives.projects import Project

project = Project.open("/path/to/board")          # directory with *.kicad_pro
# or: Project.open("/path/to/board/board.kicad_pro")

print(project.directory)
print(project.project_file)
print(project.base_name)
print(project.schematic_file)  # optional
print(project.pcb_file)        # optional
```

Discovery requires a selected `*.kicad_pro`.
When several project files exist in a directory, the stem that matches the
directory name wins; otherwise the alphabetically first candidate is used.
Root schematic and PCB companions prefer the project file stem, then the
directory name, then non-autosave files, then autosave-only fallbacks.
Companions are optional.

## Hierarchical schematic files

```python
for path in project.schematic_files():
    print(path)
```

`schematic_files()` returns the root schematic plus reachable child sheets in
discovery order.
Each `(property "Sheetfile" "…")` value is resolved **relative to the parent
sheet directory**, matching KiCad's sheet path rule.
That corrects the jBOM donor habit of joining every child to the project root.
Missing children are skipped. Cycles stop after the first visit. Without a
root schematic the result is empty.

This list is path discovery only.
Sheet instance paths, multi-instance sheets, and schematic content models
remain later work.

## Text variables

```python
for name, value in project.text_variables.items():
    print(name, value)
```

`.kicad_pro` is JSON. The `text_variables` object is exposed as a read-only
`str`→`str` map.
Absence, `{}`, and `null` are normal and yield an empty map—not a diagnostic.
Non-string entries are skipped.
Malformed project JSON raises `InvalidProjectError` on open.

## Errors

- `InvalidProjectError`: missing project file, wrong open target, or unreadable
  project JSON.
- Ordinary `OSError` subclasses still apply to underlying filesystem failures.

## Tests

Donor gates from jBOM project discovery, context, and variables tests are
ported under `tests/functional/test_project_context.py`, plus a nested
parent-relative sheet case.
The normal suite still needs no KiCad install or donor checkout after package
installation:

```bash
python -m unittest discover -s tests -q
```
