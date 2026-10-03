# integration4 submission hardening

Base: `integration3` at `89e3e0d26ea87b3961cdb97a1dcd5279dfbdedd6`.
Work was performed on a new `integration4` branch from that exact clean snapshot.
No live OpenRouter calls were made.

## Changes

- `agent.py`: render safe `USABLE_PARTIAL` results without changing acceptance,
  resolution status, nonzero exit code, or final trace `success=false`. The existing
  resolution must explicitly report `executable`, `grounded`,
  `scientific_checks_pass`, `meaningful_visual`, and `explanation_present` as true,
  and a derivation must exist. Missing minima fail closed. Record the render policy
  in the trace; run the same static artifact checks for full and partial results.
  Render/validation exceptions remove HTML while retaining diagnostics. No new
  scoring system, validator, or cross-candidate cache was added.
- `runtime/playground-runtime.js`: select supplied source cards using the union
  of evidence and mechanism-grounding block IDs. Keep input order, display each ID
  once, omit unavailable/unreferenced blocks, and retain the evidence-claims UI.
- `playground/resolution.py`: the dependency fallback now directly declares a
  supported `pipeline` visual with core control/node bindings. Visual IDs and
  resolved experience behavior are preserved. Exploration distinctness includes
  setup plus validated expectation type, target, and expected result. Title/prose
  changes and tolerance-only changes do not create distinct explorations. Both
  quality checks and repair scopes use the same identity.
- `scripts/generate_showcase.py`: reproduce the committed Attention output via
  the real agent pipeline with a single offline fixture response, with network
  access explicitly rejected. The original example input and scientific fixtures
  are unchanged. The output is 115,186 bytes, self-contained, and clearly labeled
  as a mock/fixture showcase in README.
- `.gitignore`: allow the intentional committed `examples/output/` directory while
  retaining ignored generated output directories.

## Verification

Environment: actual CPython 3.11.9, pinned project requirements (NumPy 2.3.5,
Pydantic 2.13.5), pytest 9.1.1, Node 24.21.0, Playwright 1.63.0, Chromium 153.

| Suite | Baseline | Final |
| --- | --- | --- |
| Full Python | 317 passed; 334 subtests passed | 346 passed; 334 subtests passed |
| Chromium final pipeline | 9 passed | 14 passed |

Baseline setup initially encountered a sandbox restriction on pytest's default
temporary directory and Playwright worker creation, plus a missing pinned browser.
Using an ignored workspace basetemp, permitting browser worker execution, and
installing the pinned browser resolved these environment issues before editing.

Verification commands on this workstation:

```powershell
& .venv/python311/python.exe -m pytest -q --basetemp=out/pytest-final
$env:PYTHON = (Resolve-Path .venv/python311/python.exe).Path
npm.cmd run test:browser
```

The portable local Python path is test environment setup, not a production
dependency. Standard Python 3.11 environments can use `python -m pytest -q`.

New coverage:

- 29 Python test cases in `tests/test_integration4.py`: full/safe-partial packaging,
  unsafe test/invariant/grounding/computation/explanation rejection, every missing
  safety minimum, missing derivation, partial packaging cleanup, supported fallback
  contracts and experience modes, distinct validated exploration consequences,
  duplicate rejection, and byte-reproducible showcase generation.
- Updated the previous partial-retention regression to require safe HTML plus
  honest non-success diagnostics.
- Five new Chromium cases: union grounding, safe partial, directed pipeline
  recovery, invalid-experience pipeline recovery, and the committed showcase.
  The source regression follows input blocks b2 (equation), b1 (paragraph) through
  normalization to b0000/b0001 and verifies exactly one card for each in source
  order, including repeated references and excluding unrelated context.
- All original nine Attention/Entropy/Bayesian canonical/shared/invalid-experience
  browser cases remain passing. All 14 run offline, report no external requests
  or console/page errors, and check working controls. Recovered visuals render
  pipeline nodes directly without the exception-driven fallback message.
- Static offline packaging checks run for both full and safe partial outputs.

The negative partial browser fixture intentionally prints a generation-failed
message: its nonzero result and final trace failure are asserted, while its page
remains inspectable. This is expected behavior, not a failed test.

## Frozen boundaries and remaining scope

Compared against `e2de90d6a61d84e9add864d1866891f4444e1ddb`, these remain unchanged:
`playground/models.py`, `playground/validation.py`, `playground/computation.py`,
`runtime/computation.js`, `contracts/paper-mechanism-ir.schema.json`, and the
Attention/Entropy/generic scientific fixtures. No operations, tests/invariants,
semantic-call budgets, or shared ExperienceSpec fields were changed.

No known outstanding P0/P1 issue from this requested hardening scope remains.
Source-to-formula semantic fidelity is still the generation layer's responsibility;
mocked checks do not establish live model performance. Assessment source delivery
limitations remain documented in README. Live testing was explicitly outside scope.
