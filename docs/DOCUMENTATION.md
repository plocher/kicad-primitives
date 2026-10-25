# Package documentation contract

This file locks **how** we document public surfaces so slices do not invent
parallel styles. It is not a docs product factory and not a generated API site.

Governing context: ADR 0002 (public areas), ADR 0005/0006 (pre-1.0 and 1.0 bar),
root `AGENTS.md` (docs follow a real public surface).

## Layers (one job each)

| Layer | Job | When a map task ships public API |
| --- | --- | --- |
| **Usage page** | Human contract: how to call it, limits, errors | Update or add one STE-flavored page under `docs/` for that area |
| **Docstrings** | Signature-adjacent contract on public types and callables | Required on every new or changed public class, method, and exception |
| **CHANGELOG** | What landed | One Unreleased bullet; point at the surface and the usage page path |
| **ADRs / AGENTS / CONTEXT** | Decisions and terms | Only when policy or vocabulary changes |
| **Generated API reference** | Optional machine index of signatures | **Deferred** until closer to 1.0; if added, one tool only, driven by docstrings |

Do not create a second hand-written “API reference” narrative beside the usage
pages. Do not leave public behavior only in chatty module comments.

## Usage page rules

### Location and naming

- One primary usage page per shipped public area under `docs/`.
- Current pages:
  - `docs/symbol-libraries.md` — `kicad_primitives.symbols`
  - `docs/projects.md` — `kicad_primitives.projects`
  - `docs/schematics.md` — schematic content via `Project` / `kicad_primitives.schematics`
- New areas get `docs/<area>.md` (or a clear section on an existing page if the
  surface is a thin extension of that area).
- Link the page from `README.md` when the surface is first offered.

### Required section order

Use these headings (extra mid-page sections are allowed for large surfaces):

1. **Title** — area name and short scope (what the page covers).
2. **Scope** — what the surface does and does not do; pre-alpha / ADR limits as needed.
3. **Open** (or equivalent entry) — how the caller obtains the service.
4. **Use** — inspect / edit / other operations with short examples.
5. **Limits** — out of scope for this page or this slice; pointers to later work.
6. **Errors** — exported exception types and ordinary `KeyError` / `OSError` rules.
7. **Tests** — how to run gates; fixture provenance; opt-in checks if any.

### Writing style

- STE-flavored technical English (see project STE guidance): active voice, short
  sentences, one name per concept, no marketing adjectives.
- Examples are minimal and copy-pasteable. Prefer real public import paths.
- State failure behavior. Do not imply silent success for unsupported work.
- Do not document private modules (`_*`), parser nodes, or spans as public API.

## Docstring rules

- Public classes, methods, module-level functions, and exported exceptions need
  docstrings.
- State purpose, important parameters, and failure modes in plain language.
- Do not duplicate the full usage page. Point to `docs/…` for long recipes.
- Keep identifier spelling identical to the usage page (one name per concept).

## Map task and PR gate

A PR that adds or changes **public** surface is incomplete unless:

1. The matching usage page is updated (or added).
2. Public docstrings exist for the new or changed callables and types.
3. `docs/CHANGELOG.md` Unreleased lists the change with a doc path when useful.
4. `README.md` links stay accurate for newly offered surfaces.

Internal-only changes (private helpers, test-only fixtures) do not need a new
usage page.

## Validation commands (docs mention)

Prefer `uv` for package work:

```bash
uv pip install -e .
uv run python -m unittest discover -s tests -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict --follow-untyped-imports src/kicad_primitives
```

Usage pages may show the same commands. Do not invent a second install story.

## Deferred (not this contract)

- Sphinx / MkDocs / full generated API site
- Tutorial tracks and multi-agent docs factories
- Per-consumer migration cookbooks (those live on consumer trackers at offer time)
- Rewriting the founding survey as living API docs

Promote a single generated reference later under this contract. Do not add a
competing hand-written reference style before then.

## Related files

- `AGENTS.md` — operating model; docs follower rule; session charter
- `docs/adr/` — decisions
- `docs/CHANGELOG.md` — shipped deltas
- `README.md` — entry index to usage pages
