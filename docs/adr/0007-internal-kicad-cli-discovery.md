# ADR 0007: Internal kicad-cli path discovery

Date: 2026-10-24

Status: Accepted by the owner on 2026-10-24.

Ticket: [Internal KiCad execution locator contract and precedence](https://github.com/plocher/kicad-primitives/issues/12)

## Problem

Several donors each locate `kicad-cli` with different env names, probe orders, and failure styles.

| Donor | Behavior |
| --- | --- |
| kproj | Public `find_kicad_cli`; env `KPROJ_KICAD_CLI`; hard fail; tested |
| jBOM | Private finder; no env; soft `None` for optional gerbers |
| Subdivision | Env `KICAD_CLI`; unchecked path; several hardcoded copies |
| This package | Opt-in verifier flag `--kicad-cli` only; no shared finder |

ADR 0002 keeps execution private. ADR 0006 allows `kicad-cli` as a backend and says to lock private locator policy when the first external engine is wired. Without one rule, the next export or netlist op will copy a donor footgun.

## Constraints and requirements

- No public `cli` module (ADR 0002).
- Pure file services must work with no KiCad install.
- Discovery failure must stay distinct from operation failure (bad args, non-zero exit, bad output).
- Do not invent a package-only env name when KiCad documents `KICAD_CLI`.
- In-process `pcbnew` / plugin Python is out of default package scope (ADR 0006).
- Reimplementation of capabilities without `pcbnew` remains allowed.
- Do not build a general execution framework in this decision.

## Definition of success

A maintainer can answer:

1. What resolves `kicad-cli`, and in what order?
2. When may discovery run?
3. What happens if nothing is found, or an override is wrong?
4. What stays out of this helper (version gate, plugins, subprocess policy)?

## Candidates and evaluation

### A: Copy kproj’s public locator and `KPROJ_KICAD_CLI`

Pros: tested donor code.

Cons: public-shaped API; wrong env name for a shared package; pulls plugins/Python concerns into the story.

Rejected as the package contract.

### B: Soft `Optional[Path]` like jBOM gerbers

Pros: easy optional exports.

Cons: every caller invents a second miss path; blurs discovery vs skip policy.

Rejected for the shared helper. Optional product behavior stays at the operation edge.

### C: Private lazy finder; `KICAD_CLI` only; hard discovery error

Pros: small blast radius; one env name; matches verifier explicit path; keeps file I/O free of KiCad.

Cons: callers that want “skip if missing” must catch the error (acceptable).

## Decision

Choose **C**.

### Precedence

1. Explicit path from the caller (API argument or CLI flag shaped like `--kicad-cli <executable>`).
2. Environment variable **`KICAD_CLI`**.
3. Platform well-known install locations (current majors as needed).
4. `PATH` lookup for `kicad-cli`.

`KPROJ_KICAD_CLI` is not package policy. kproj may map or retire that name at its boundary.

### Laziness and failure

- Call discovery only when an operation needs `kicad-cli`. Never at import or package-wide init.
- If nothing resolves, raise a dedicated **discovery** error.
- If `KICAD_CLI` or an explicit path is set but missing or not usable, raise the same discovery error family with a clear message. Do not fall through to later probes.
- Operations that treat a missing engine as skip/unsupported catch the discovery error and translate it. The locator does not return soft `None`.

### What the helper does not do

- Version gating (find is enough given a stable CLI surface; an op may probe version later if required).
- KiCad-bundled Python, PCM plugins, or iBOM paths.
- Subprocess running, stderr filters (including Fontconfig noise), or a general command facade.

Those stay with the calling operation or a later private helper if evidence demands it.

### Surface

Private implementation only. Public report/export APIs live on functional services (ADR 0002, ADR 0006). Backend choice remains an implementation detail.

## Consequences

- Implement one private discovery helper when the first engine-backed operation lands. Bring kproj unit tests as the net where they still match this contract.
- Opt-in tools may keep an explicit `--kicad-cli` path and feed precedence step 1.
- Donor cutovers call public functional services that need an engine. Those services invoke the private helper internally. Consumers do not import the private finder. A consumer may still pass an explicit path into a service API when the service exposes that argument. Fixing latent donor bugs in place is optional and does not gate the package.
- Map ticket #12 is satisfied by this ADR. No locator code is required in the same change set.
