# ADR 0005: Distribution and versioning for consumers

Date: 2026-10-24

Status: Accepted by the owner on 2026-10-24.

Ticket: [Distribution and versioning for consumers](https://github.com/plocher/kicad-primitives/issues/7)

## Problem

The package has a first functional slice (ADR 0004) and an installable tree, but no locked rule for how donor projects depend on it.

Without that rule, maintainers face bad defaults: pin a pre-1.0 wheel, add another `sys.path` checkout hack, couple jBOM majors to this package, or freeze WIP APIs through early production cutovers.

The owner maintains the donor projects. The open question is not third-party packaging theater. It is how this package and those donors stay decoupled until the package is mature enough to depend on.

## Constraints and requirements

- ADR 0001 names the distribution `kicad-primitives` and the import `kicad_primitives`.
- Migration is decoupled: package progress does not wait on donor cutovers, and donors do not wait on this package.
- Pre-1.0 work must stay free to break. Backwards-compatibility cost before 1.0 slows the path to a dependable release.
- Early production migration into donor `main` destabilizes donors and freezes the wrong surface.
- Validation still needs a way to exercise WIP against real donors (blast radius, migration recipes) without a released dependency contract.
- Owner tooling is moving to `uv`. Recipes must not require raw `pip` as the documented path.
- This decision must not start a CI or release-engineering epic.
- The runtime parser dependency `circuitdk-lossless-sexpr` is already on public PyPI. That does not force a public pre-1.0 release of this package.

## Definition of success

A maintainer can answer:

1. When may a donor declare a released dependency on `kicad-primitives`?
2. What compatibility promise does that dependency carry?
3. How does the owner install WIP for package work and disposable probes without `sys.path`?
4. Does any jBOM (or other donor) version line couple to this package before cutover?

## Candidates and evaluation

### A: Public PyPI `0.x` as the consumer channel

Donors could pin `kicad-primitives>=0.x,<1` early.

Pros: ordinary install path; easy multi-env probes.

Cons: creates a de facto compatibility surface before maturity; invites production pins of unstable APIs; turns every breaking change into donor churn.

Rejected for production consumer use before 1.0.

### B: Path-only or editable forever until some large TOC milestone, with no 1.0 bar

Keeps installs local only.

Pros: no public pre-1.0 promise.

Cons: without an explicit first dependable release, “when may donors pin?” stays vague; path-only habits invite `sys.path` relapse.

Rejected as the whole policy. Local editable installs remain the pre-1.0 *development* path, not a substitute for a 1.0 dependency bar.

### C: No released consumer dependency before 1.0; WIP via editable/`uv` and optional Test PyPI probes

Production donors stay on their local KiCad I/O until `1.0.0` on public PyPI.

Pre-1.0 labels carry no compatibility promise. The owner uses venv-scoped `uv` editable installs for package work and disposable probes. Test PyPI may host experimental wheels for install checks. Donor `main` must not pin Test PyPI or any `0.x` release.

Pros: protects donors; keeps WIP free to break; still allows blast-radius learning; matches decoupled migration.

Cons: no early external consumer ecosystem (acceptable: the owner is the consumer set).

### D: Vendor or couple jBOM majors to this package

Copy the tree into jBOM, or require “jBOM 8+ means kicad-primitives”.

Pros: none that survive ADR 0001’s single-home rule.

Cons: second home, version tangle, false maturity signal.

Rejected.

## Decision

Choose **C**, with explicit hygiene and version rules.

### Released dependency bar

- Donor **released** packaging (`main`, published artifacts, lockfiles meant for normal use) must **not** depend on `kicad-primitives` before **`1.0.0`**.
- **`1.0.0` on public PyPI** is the first version a donor may depend on for production use.
- The owner locks what capability set `1.0.0` contains. This ADR does not define that completeness bar.
- After `1.0.0`, use normal SemVer: breaking change → major; feature → minor; fix → patch.

### Pre-1.0 labels and channels

- Versions on the development line are **`0.x.y` (or `0.x.y.devN`)** and are **informational only**.
- Pre-1.0 carries **no** backwards-compatibility promise. Semantic-release automation is not required before 1.0.
- Manual version bumps are allowed when the owner wants a clearer changelog anchor or a distinguishable Test PyPI artifact.
- Leaving `0.0.0` until the first deliberate bump or upload is allowed.
- **Public PyPI production uploads start at `1.0.0`.**
- **Test PyPI** may hold pre-1.0 wheels for disposable install probes only. Test PyPI is not a production channel. Donor `main` must not pin it.

### How the owner consumes WIP (not migration)

| Purpose | Environment | Install |
| --- | --- | --- |
| Package development | Venv for this repo | `uv venv`, then `uv pip install -e .` |
| Disposable donor probe | Separate probe venv or throwaway branch env | `uv pip install -e /path/to/kicad-primitives` |
| Optional wheel probe | Clean probe venv | Install from Test PyPI; use public PyPI as extra index for transitive deps such as `circuitdk-lossless-sexpr` |
| Day-to-day donor work (no probe) | Donor env | Do **not** install `kicad-primitives` |

Probe outcomes are blast-radius notes and migration recipes. They are not merged production cutovers.

### Forbidden

- `sys.path` (or equivalent path hacks) into this repository for new work.
- Ambient or global editable installs “for convenience” that make every shell import WIP.
- Released donor dependency on any pre-1.0 artifact (public or Test PyPI).
- Vendoring this tree into jBOM or any other donor.
- Coupling jBOM (or other donor) major/minor lines to this package’s pre-1.0 life.

### Donor cutover (after 1.0 only)

When a donor migrates, that donor’s release adds an ordinary dependency, for example:

```toml
dependencies = ["kicad-primitives>=1.0.0,<2"]
```

Exact ranges are chosen in the donor migration PR. That PR removes the local duplicate modules. No standing couple exists before that cutover.

### Tooling scope for this decision

- Document **`uv venv` + `uv pip install -e .`** as the install recipe.
- Do **not** require `uv.lock`, full uv-project layout, or CI release automation in this ADR.
- Full uv lock/sync and release pipeline work may land later near 1.0 or when multi-dev/CI needs appear. That is separate work, not a distribution-policy change.

## Consequences

- README, `PACKAGE_IDENTITY`, and agent docs state the dependency bar and install recipes.
- `pyproject.toml` may keep a pre-1.0 version label; that label is not a consumer contract.
- Optional validation probes remain allowed under AGENTS.md, but they must follow the probe rules above. They do not license production pins before 1.0.
- Map ticket #7 is satisfied when these rules are accepted and reflected in packaging docs. No consumer repository is migrated by this ADR.
- First public production publish remains a later release action at `1.0.0`.
