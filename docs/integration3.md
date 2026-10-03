# integration3 merge

Prepared 2026-10-03. This branch combines:

- Person 3's `integration2`: `a857222feb1bdc6fc171d6035b0646f3a370098b`.
- Hardened Person 1/2 `integration`: `42c1275958bf2ee3ff032871e1668ed10f416c8f`.

The source branches and `main` are unchanged. The merge retains the integrated
agent-to-HTML path and all upstream generation, orchestration, resolution, and
prompt hardening. Those upstream files match the incoming commit.

## Resolutions

The `agent.py` output-list conflict was resolved by retaining both `resolution.json`
and `index.html`, together with the existing scientific/source/trace outputs.
Recovery diagnostics remain available, and stale HTML cleanup remains effective.

Upstream recovery resolves visual IDs and ExperienceSpec against a presentation
visual list that can differ from the original science specification. The renderer
now consumes a nonempty `DerivedPlayground.resolved_visuals` list with its parallel
visual IDs and resolved experience. It copies the specification for presentation;
the original scientific specification and derived object are not mutated. Frozen
derivations with the default empty resolved-visual list retain their original figures.

This fixes directed experience falling back because recovered visual IDs were
previously paired with the original visual list. Recovery fallback figures keep
their IDs, so experience references stay valid.

## Preserved boundaries

Person 2 remains pinned to `e2de90d6a61d84e9add864d1866891f4444e1ddb`.
Models, schema, validation, Python computation, and embedded JavaScript computation
were checked against that revision; the JavaScript runtime matches byte-for-byte.
Dependency semantics remain source ID to transitive downstream computation IDs.

The incoming recovery rules, protected repair references, fresh validation,
strict scientific diagnostics, exact model selection, budgets, and tracing are
preserved. Tests/invariants are not weakened to obtain success. Resolution retains
FULL_SUCCESS, USABLE_PARTIAL, and UNUSABLE distinctions. Partial recovery retains
diagnostics and derived data, returns nonzero, and does not claim agent success or
leave stale HTML. Accepted full results continue through HTML packaging and checks.

## Verification

- 317 Python tests and 334 subtests passed using the pinned requirements.
- Nine Chromium pipeline tests passed: Attention, entropy, and Bayesian odds,
  each in canonical, directed shared-experience, and invalid-experience modes.
- Browser checks cover controls, changing values/figures, What Changed, guidance,
  source grounding, mobile overflow, no external requests, and no console errors.
- Added regressions cover recovery visual IDs without scientific mutation,
  direct frozen derivation, and partial recovery retaining non-success diagnostics.

Browser model responses are explicitly mocked. No live OpenRouter call was made
for this merge. The supplied upstream notes report a Bayesian FULL_SUCCESS on
the first call, without repair or pruning, in 32.468 seconds; this was not
independently repeated here. Earlier integration2 live failures are historical,
as documented in [submission verification](submission-verification.md).

Use the commands in the [README](../README.md) to run the combined pipeline or
repeat offline checks. Credentials and generated artifacts remain ignored.
