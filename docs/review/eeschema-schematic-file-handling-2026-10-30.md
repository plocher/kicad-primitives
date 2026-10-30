# KiCad eeschema schematic file handling (research)

## Problem / question
How does KiCad model and implement schematic vs sheet open, save, close, create/rename/delete sheet, dirty tracking, locks, and backups — so `kicad-primitives` can mirror KiCad vocabulary and behavior under ADR 0009 / issue #75?

Owner locks to validate:
- Sheet = one `.kicad_sch` file
- Schematic = multi-sheet hierarchy document; save writes all dirty sheets
- `Sheet.save` is not a public product action
- Project is container navigator; `project.save` is umbrella over document saves
- Opening any sheet loads the whole schematic hierarchy

## Method
Primary sources only:
- Local tree: `/Users/jplocher/Dropbox/workspace/kicad` (kicad-source-mirror)
- Inspected commit: `d4f4523276fb94d1ff4eb341ef294e054c4f6e09` (`10.99.0-5580-gd4f4523276`, HEAD master as of research)
- Focus areas: `eeschema/` (especially `files-io.cpp`, `schematic.*`, `sch_screen.*`, `sch_sheet*`, `sheet.cpp`, `sch_edit_frame.*`, `sch_io/kicad_sexpr/`), `include/lockfile.h`, `common/eda_*_frame.*`, `common/settings/settings_manager.*`, `common/wildcards_and_files_ext.cpp`, `kicad/kicad_manager_frame.cpp`
- Official product docs not required for behavior; code wins

No kicad-primitives ADRs used as truth about KiCad.

## Findings by topic

### 1. Nouns (ownership: file vs memory)

| KiCad type | Role | File vs memory |
| --- | --- | --- |
| `SCH_EDIT_FRAME` | Schematic editor main window. Holds `m_schematic`. UI open/save/close and dirty presentation. | UI / session |
| `SCHEMATIC` | “Holds all the data relating to one schematic.” One or more sheets plus one virtual root. Comment: Eeschema can currently have only one schematic open at a time. | In-memory document graph |
| `SCH_SHEET` | Sheet **symbol** in a parent screen; entry into a child schematic. Points at a `SCH_SCREEN`. In complex hierarchies multiple sheets share one screen. | Hierarchy graph node; filename field is relative path text |
| `SCH_SHEET_PATH` | Stack of sheets from root to a sheet instance. Carries instance data (refs, page numbers, variants). | Purely in-memory path |
| `SCH_SCREEN` | Drawing content of one schematic **file**. Absolute filename. Items R-tree, title block, lib cache, refcount. | One unique screen per distinct `.kicad_sch` path when loaded |
| `SCH_SCREENS` | Walk unique screens under a sheet. Comment: “Individual `SCH_SCREEN` objects are unique and correspond to `.sch` files.” | Collection over files |
| Virtual root | `SCHEMATIC::m_rootSheet`: sheet with **no** file of its own; children are top-level sheets. | In-memory only |

Citations:
- `eeschema/schematic.h` — class `SCHEMATIC` doc (“one schematic… one or more sheets”), members `m_rootSheet`, `m_topLevelSheets`, `m_currentSheet`, `m_hierarchy`
- `eeschema/schematic.h` — `SCHEMATIC_CONTENT` notes screens/sheets “woven together”
- `eeschema/sch_sheet.h` — `SCH_SHEET` “Sheet symbol… entry point for a sub schematic”; `m_screen` “In complex hierarchies multiple sheets can share a common screen”
- `eeschema/sch_sheet_path.h` — hierarchy primer: sheet vs screen, simple vs complex hierarchy, `SCH_SHEET_PATH` / `SCH_SHEET_LIST`
- `eeschema/sch_screen.h` — `SCH_SCREEN::SetFileName` absolute paths; `SCH_SCREENS` “correspond to .sch files”
- `eeschema/schematic.cpp` — `RootScreen()` returns first top-level sheet’s screen (virtual root is not a file); `GetFileName()` same

**Vocabulary nuance:** product language “sheet file” maps to **`SCH_SCREEN`**, not to every `SCH_SHEET` object. A sheet symbol is a graph edge/node; the file is the screen.

### 2. Open

Entry: `SCH_EDIT_FRAME::OpenProjectFiles(aFileSet, aCtl)` in `eeschema/files-io.cpp`.

Sequence (KiCad schematic path):
1. Require exactly one absolute path.
2. `LockFile(fullFileName)` on that path (see Locks). Optional override if project already granted lock override.
3. `AskToSaveChanges()` for any dirty screen in the **current** schematic.
4. If project path differs: save local/project settings, unload project, `LoadProject` for sibling `.kicad_pro`.
5. `CheckForAutosaveFiles` for `.kicad_sch` before load.
6. Build `new SCHEMATIC(&Prj())`.
7. Load:
   - If project file lists top-level sheets: load **each** top-level `.kicad_sch` via plugin `LoadSchematicFile`, then `SetTopLevelSheets`.
   - Else legacy single-root: one `LoadSchematicFile(fullFileName)` and `SetTopLevelSheets({ rootSheet })`.
8. `SetSchematic`, hierarchy repair, rescue/legacy conversion as needed.

Hierarchy load inside `SCH_IO_KICAD_SEXPR::LoadSchematicFile` → `loadHierarchy`:
- For each sheet without a screen: resolve absolute path; **`SearchHierarchy` for existing screen** (reuse shared screen); else `new SCH_SCREEN`, `loadFile`, then recurse into child `SCH_SHEET_T` items.
- Shared path ⇒ one screen, subtrees already loaded, not re-read.

**All sheets loaded?** Yes for reachable hierarchy under the opened root(s). Failures on child sheets collect into plugin error string; root failure aborts.

**Root selection:** multi-root from project top-level sheet list; else single loaded sheet as top-level. Virtual root never has a file. Current sheet set during schematic setup; UI navigates paths.

**Opening a non-root `.kicad_sch`:** still goes through `OpenProjectFiles` with that path as the file set entry. Project association uses same-stem `.kicad_pro`. Hierarchy load still walks **that** sheet’s subtree as a schematic root for the session (or project multi-root list when present). Product workflow usually opens via project / root schematic.

Citations:
- `eeschema/files-io.cpp` — `OpenProjectFiles` (lock, ask save, project switch, autosave check, top-level vs single root load)
- `eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr.cpp` — `LoadSchematicFile`, `loadHierarchy` (shared screen via `SearchHierarchy`)

### 3. Save

Public editor actions:
- `SCH_EDITOR_CONTROL::Save` → `SCH_EDIT_FRAME::SaveProject()`
- `SaveAs` → `SaveProject(true)`
- Separate: `SaveCurrSheetCopyAs` → private `saveSchematicFile` for **current sheet only**, with `isSaveAs=true` (does not clear dirty)

`SaveProject` (`files-io.cpp`):
1. Early exit if not Save As / null project / missing file / legacy upgrade path, **and** `!IsContentModified()` → return true without writing sheets.
2. Build `filenameMap` for every screen in `SCH_SCREENS(Schematic().Root())`.
3. Preflight: non-writable destinations → fail whole save; legacy→new extension overwrite warnings.
4. Loop **all** screens with valid filenames:
   - Normalize extension to `.kicad_sch`
   - `saveSchematicFile(sheet, path, saveCopy)` for each
   - `success &= savedThisSheet` (continues after failure; partial write possible)
5. On overall success: stop autosave timer; `LockFile(RootScreen()->GetFileName())` again.
6. Update project sheet name map; save/create project via `SETTINGS_MANAGER` (`SaveProjectAs` / `SaveProjectCopy` / `saveProjectSettings`).
7. Local history: `RunRegisteredSaversAndCommit(..., "SCH Save")`; `RemoveAutosaveFiles` for paths actually written.
8. If **not** single-app mode: `TriggerBackupIfNeeded` (timestamped project ZIP policy).

`saveSchematicFile`:
- May call `saveProjectSettings()` if a `.kicad_pro` exists beside the destination.
- `SCH_IO::SaveSchematicFile` via sexpr plugin (atomic prettified write path).
- On success and **not** save-as-copy: `screen->SetContentModified(false)`.

**Which files written?** Every unique screen under the hierarchy with a valid filename map entry when the schematic is considered modified (or always on Save As / first save). **Not** “only dirty screens” in the write loop.

**Order:** `SCH_SCREENS` iteration order (build from root sheet walk), not page-number order.

**Project file:** ERC/settings and sheet UUID/name list updated; project JSON save is part of SaveProject, not a substitute for sheet writes.

Citations:
- `eeschema/tools/sch_editor_control.cpp` — `Save`, `SaveAs`, `SaveCurrSheetCopyAs`
- `eeschema/files-io.cpp` — `SaveProject`, `saveSchematicFile`, `PrepareSaveAsFiles`
- `eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr.cpp` — `SaveSchematicFile` / `Format`

### 4. Close / quit

`SCH_EDIT_FRAME::canCloseWindow`:
- If `IsContentModified()`, one prompt: “Save changes to '%s'…” using **root screen** basename; yes path calls **`SaveProject()`** (whole schematic).
- Discard path may commit local-history “Discard unsaved schematic changes”.
- Not per-sheet prompts.

`doCloseWindow`:
- Unregister history saver; remove autosave files for **screens still dirty** at close; `ClearModifyStatus` on hierarchy; clear view; `Schematic().Reset()`.

`AskToSaveChanges` (used when opening another schematic): walks screens; first dirty screen triggers one “current schematic has been modified” prompt → `SaveProject()`.

Citations:
- `eeschema/sch_edit_frame.cpp` — `canCloseWindow`, `doCloseWindow`
- `eeschema/files-io.cpp` — `AskToSaveChanges`

### 5. Create / rename / delete sheet

**Create / rebind file** — `EditSheetProperties` / `InitSheet` / `ChangeSheetFile` (`sheet.cpp`, frame API in `sch_edit_frame.h`):
- New empty sheet: `InitSheet` allocates `SCH_SCREEN`, sets absolute filename, **`SetContentModified()`** — memory only until schematic Save.
- Link to existing hierarchy screen: share screen; may clear annotation.
- Link/load existing disk file: `LoadSheetFromFile` / load path; recursion checks.
- Design-block copy: `wxCopyFile` source → destination immediately, then load.
- Rename sole user of a screen to new path: **immediate** `SCH_IO::SaveSchematicFile` to new path; may update screen filename; comment “cannot be undone”.
- Shared screen rename to new file: save new file then reload as separate screen.

**Delete sheet** — `SCH_EDIT_TOOL::DoDelete`:
- `commit.Remove` of `SCH_SHEET_T` from **parent screen** only.
- Updates hierarchy navigator.
- **No** `wxRemoveFile` / delete of `.kicad_sch` on disk.

So: hierarchy graph ops are primary; disk create happens on explicit rename-save or SaveProject; disk delete of orphaned sheet files is **not** automatic.

Citations:
- `eeschema/sheet.cpp` — `InitSheet`, `ChangeSheetFile`
- `eeschema/sch_edit_frame.h` — `EditSheetProperties` contract (new vs existing filename cases)
- `eeschema/tools/sch_edit_tool.cpp` — `DoDelete` (`updateHierarchy |= SCH_SHEET_T`)

### 6. Dirty / modified flags

- Flag lives on `BASE_SCREEN::m_flagModified` via `SetContentModified` / `IsContentModified` (`include/base_screen.h`).
- `SCH_EDIT_FRAME::OnModify` → `GetScreen()->SetContentModified()` for **current** screen + local history note.
- Frame-level dirty: `IsContentModified()` = `Schematic().Hierarchy().IsModified()` = any path’s `LastScreen()->IsContentModified()`.
- `SCH_SHEET_LIST::ClearModifyStatus` clears every screen.
- Save clears dirty **per written screen** in `saveSchematicFile` (unless save-as-copy).
- Title bar `*` uses whole-schematic dirty, not only current sheet.

No separate dirty bit on `SCH_SHEET_PATH`. Instance edits still mark the owning screen through normal modify paths.

Citations:
- `include/base_screen.h`
- `eeschema/sch_edit_frame.cpp` — `OnModify`, `IsContentModified`
- `eeschema/sch_sheet_path.cpp` — `SCH_SHEET_LIST::IsModified`, `ClearModifyStatus`
- `eeschema/files-io.cpp` — clear dirty in `saveSchematicFile`

### 7. Locks

Native lock path construction (`include/lockfile.h` + `FILEEXT`):
- Prefix `~`, extension `lck` appended after original extension  
- Example: `foo.kicad_sch` → `~foo.kicad_sch.lck`  
- `foo.kicad_pro` → `~foo.kicad_pro.lck`
- JSON body: username, hostname, token; exclusive OS lock; crash releases OS lock so peers can reclaim.

**Schematic editor:**
- `EDA_DRAW_FRAME::LockFile` holds one `unique_ptr<LOCKFILE>` (`m_file_checker`).
- Open locks the **opened file path** only (typically root / entry schematic), not every child sheet.
- After successful `SaveProject`, re-locks `RootScreen()->GetFileName()`.
- `ReleaseFile` unlocks on revert/reload paths.

**Project manager:**
- `KICAD_MANAGER_FRAME::LoadProject` inspects lock on `.kicad_pro`; may override.
- `ProjectChanged` takes project lock via `Prj().SetProjectLock` if none yet; may mark project read-only if lock not held.

Child `.kicad_sch` files are not individually locked by the open hierarchy walk.

Citations:
- `include/lockfile.h` — `LOCKFILE`, `LockPathFor`
- `common/wildcards_and_files_ext.cpp` — `LockFilePrefix` `"~"`, `LockFileExtension` `"lck"`
- `common/eda_draw_frame.cpp` — `LockFile`, `ReleaseFile`
- `eeschema/files-io.cpp` — open lock; save re-lock root
- `kicad/kicad_manager_frame.cpp` — `LoadProject` inspect; `ProjectChanged` project lock

### 8. Backup / autosave / history

Three related systems:

**A. Timestamped project ZIP backups**
- `SETTINGS_MANAGER::TriggerBackupIfNeeded` after schematic save (when not `Kiface().IsSingle()`).
- Directory: default `projectPath + projectName + "-backups"` (`PROJECT_BACKUPS_DIR_SUFFIX`), or user settings `backups/` tree.
- Name: `{projectName}-{YYYY-MM-DD_HHMMSS}.zip` via `BackupProject` / `PROJECT_ARCHIVER::Archive`.
- Gated by common backup settings (enabled, ZIP format vs incremental-only, min interval).

**B. Local history / autosave**
- Editor timer → `EDA_BASE_FRAME::doAutoSave` → `LOCAL_HISTORY::RunRegisteredSaversAndCommit`.
- Schematic saver: `SCHEMATIC::SaveToHistory` serializes sheets (ZIP autosave mode can skip clean screens).
- Open path: `CheckForAutosaveFiles` recovery dialog before load.
- Save removes autosaves for sheets just written; close removes autosaves for still-dirty sheets.

**C. `-bak` suffix**
- `FILEEXT::BackupFileSuffix` is `"-bak"`.
- Used in project tree filters (skip `* -bak` and lock names from git commit UI).
- Not the main schematic Save path observed here (Save uses plugin formatter, not a mandatory sibling `.kicad_sch-bak` write in `saveSchematicFile`). Symbol-library and other editors may still use `-bak`; do not assume schematic Save always creates `.kicad_sch-bak`.

Citations:
- `include/settings/settings_manager.h` — `PROJECT_BACKUPS_DIR_SUFFIX`
- `common/settings/settings_manager.cpp` — `GetBackupRootForProject`, `BackupProject`, `TriggerBackupIfNeeded`
- `eeschema/files-io.cpp` — post-save history + `TriggerBackupIfNeeded`
- `eeschema/schematic.cpp` — `SaveToHistory`
- `common/eda_base_frame.cpp` — autosave timer, `CheckForAutosaveFiles`, `doAutoSave`
- `common/wildcards_and_files_ext.cpp` — `BackupFileSuffix`
- `kicad/project_tree_pane.cpp` — skip locks, `-bak`, `-backups` in git commit

### 9. Project manager vs eeschema

- Project manager **does not** implement a single menu action that saves schematic + PCB + project as one atomic document save.
- `ACTIONS::save` / `saveAs` in manager control bind to **Save Project As** (directory copy of project tree), not schematic Save.
- Closing project: `CloseProject` → `Kiway().PlayersClose` (each editor’s own unsaved prompts) then may `SETTINGS_MANAGER::SaveProject` for project file/settings and backup/history housekeeping.
- Eeschema `SaveProject` is the schematic hierarchy save (+ project settings side effects). Name is historical: it saves schematic screens and updates project metadata.

**“Save project” as umbrella:** only in the weak sense that closing the project asks each open editor. There is no manager-level “save all open documents” implementation found in `kicad_manager_control` transitions (no `ACTIONS::saveAll` handler there). `ACTIONS::saveAll` exists as a common action string (“Save All”) for editors that bind it.

Citations:
- `kicad/tools/kicad_manager_control.cpp` — `SaveProjectAs` on `ACTIONS::saveAs`; no schematic save
- `kicad/kicad_manager_frame.cpp` — `CloseProject`
- `common/tool/actions.cpp` — `save`, `saveAs`, `saveAll`
- `eeschema/sch_edit_frame.h` — `SaveProject` doc: “Save the currently-open schematic (including its hierarchy) and associated project.”

### 10. API surface implication (for package mapping)

Recommended public verbs aligned with KiCad **product** behavior (confidence in parentheses):

| Package concept | Mirror of | Public verbs | Confidence |
| --- | --- | --- | --- |
| **Schematic** | `SCHEMATIC` + editor `SaveProject` / open hierarchy | `open`, `save`, `save_as`, `close`/`discard`, `is_modified` | **High** — this is the document boundary |
| **Sheet** (file) | `SCH_SCREEN` path | read/inspect; hierarchy attach; **no** standalone user `save` as primary | **High** that product Save is schematic-wide; **Medium** that exposing optional write-one-screen is still useful for advanced tools (KiCad has copy-as only) |
| **Sheet** (symbol) | `SCH_SHEET` | create/edit properties, delete from parent (graph only) | **High** |
| **Project** | manager + `.kicad_pro` | navigate, open context, save **project settings** / save-as tree; **not** silent multi-document schematic+PCB save | **High** |
| Locks | `LOCKFILE` | query `~…lck` on known paths; do not acquire (package policy) | **High** match to native naming |
| Backups | ZIP `-backups` + history | recipes, not forced inside every primitive save | **High** for ZIP layout; history is separate product feature |

## Disagreements with owner locks

| Lock | Verdict | Notes |
| --- | --- | --- |
| Sheet = one `.kicad_sch` file | **Amend (nuance)** | Product “sheet file” ≈ **`SCH_SCREEN`**. `SCH_SHEET` is the hierarchy symbol; many sheets can share one screen (complex hierarchy). |
| Schematic = multi-sheet hierarchy; save writes all dirty sheets | **Amend (write set)** | Schematic = hierarchy: **confirmed**. Save gate is schematic-level dirty; write loop writes **all** screens with valid paths, **not only dirty** screens. |
| `Sheet.save` is not a public product action | **Confirmed** | Product Save/Save As call `SaveProject`. Only special case: save **copy** of current sheet. |
| Project is container; `project.save` umbrella over document saves | **Amend** | Project is navigator/container: **confirmed**. Umbrella save of all documents is **not** a single manager operation; each editor saves itself; manager Save As copies the project tree; close asks each player. |
| Opening any sheet loads whole schematic hierarchy | **Confirmed** (with scope) | Open loads full reachable hierarchy under the loaded root(s), with shared screens for reused files. Multi-root projects load all project-listed top-level sheets. |

## Recommended package mapping (Schematic / Sheet / Project)

1. **`Schematic`** — primary editable artifact for hierarchy I/O.  
   - `open(path)` loads entire hierarchy (shared screens for reused files).  
   - `save()` writes every loaded sheet file that belongs to the schematic file set (match KiCad’s all-screens write once dirty, or document a deliberate dirty-only optimization as a **deviation**).  
   - `is_modified` = any screen dirty.  
   - `close`/`discard` at schematic scope with one decision.

2. **`Sheet`** — either:  
   - **file handle** (`SCH_SCREEN`-like) for path, bytes, read; or  
   - **symbol handle** (`SCH_SHEET`-like) for hierarchy place/remove/rename fields.  
   Do not advertise `Sheet.save()` as the normal user save. Optional internal write for rename-to-new-file can mirror `ChangeSheetFile`’s immediate save.

3. **`Project`** — discovery, variables, top-level sheet list in `.kicad_pro`, library tables.  
   - `save()` = project settings / file set policy already chosen in package ADRs.  
   - Do not imply one call always flushes schematic+PCB unless a named recipe does so explicitly (ADR 0009).

4. **Locks / backups** — honor query of `~<name>.<ext>.lck`; ZIP under `<projectName>-backups` as native peer behavior when recipes request backups; do not treat local `.history` as required for 1.0 schematic parity unless separately scheduled.

## Open questions needing owner decision

1. **Write set:** Match KiCad (on schematic dirty, rewrite **all** sheet files) or optimize to dirty-only screens (deviation; fewer writes, different mtimes/history noise)?
2. **Sheet type naming:** One type or two (`SheetSymbol` vs `SheetFile`/`Screen`) to avoid conflating shared-screen complex hierarchy?
3. **Delete sheet:** Keep KiCad behavior (leave orphan `.kicad_sch` on disk) or add an explicit recipe to delete unreferenced files?
4. **Rename sheet file:** Mirror immediate disk write on rename, or only mutate memory until `Schematic.save()`?
5. **Multi-root projects:** First-class `Project` top-level sheet list vs single-root-only until a ticket demands multi-root?
6. **Lock scope:** Query lock only on root / opened path (KiCad editor) vs every sheet path in the hierarchy (stricter than KiCad)?
7. **Save All:** Is a package recipe that saves schematic + PCB + project desired, or forever client-composed only?

## Source index

| Area | Paths |
| --- | --- |
| Open / save / ask-save | `eeschema/files-io.cpp` |
| Editor frame dirty/close | `eeschema/sch_edit_frame.cpp`, `eeschema/sch_edit_frame.h` |
| Save actions | `eeschema/tools/sch_editor_control.cpp` |
| Sheet create/rename | `eeschema/sheet.cpp` |
| Sheet delete | `eeschema/tools/sch_edit_tool.cpp` (`DoDelete`) |
| Document model | `eeschema/schematic.h`, `eeschema/schematic.cpp` |
| Screen / file | `eeschema/sch_screen.h` |
| Sheet / path primer | `eeschema/sch_sheet.h`, `eeschema/sch_sheet_path.h`, `eeschema/sch_sheet_path.cpp` |
| Sexpr load/save hierarchy | `eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr.cpp` |
| Dirty base flag | `include/base_screen.h` |
| Locks | `include/lockfile.h`, `common/eda_draw_frame.cpp` |
| Extensions | `common/wildcards_and_files_ext.cpp`, `include/wildcards_and_files_ext.h` |
| ZIP backups | `common/settings/settings_manager.cpp`, `include/settings/settings_manager.h` |
| Autosave / recovery | `common/eda_base_frame.cpp`, `eeschema/schematic.cpp` (`SaveToHistory`) |
| Project manager | `kicad/kicad_manager_frame.cpp`, `kicad/tools/kicad_manager_control.cpp` |
| Common actions | `common/tool/actions.cpp` |

Inspected KiCad revision: `d4f4523276fb94d1ff4eb341ef294e054c4f6e09` (`10.99.0-5580-gd4f4523276`).
