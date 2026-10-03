# Person 2 runtime integration

`runtime/computation.js` is an unchanged copy from:

- Branch: `origin/feature/science-runtime`
- Commit: `e2de90d6a61d84e9add864d1866891f4444e1ddb`
- SHA-256: `5d35dbdb02236f026da382b1833ee47b83a83e58172f8f1ee0d99019029e12a4`

Person 2 owns this file and all operator semantics. Person 3 embeds it before the
UI runtime and calls `PaperComputation.evaluate(spec, controls)` and
`PaperComputation.deriveDependencies(spec)`. No Python evaluator, scientific model,
or validator was merged or independently implemented on this frontend branch.

The graph maps each source ID to its transitive computation descendants. The
renderer accepts this graph explicitly or through `DerivedPlayground`; otherwise
the trusted runtime derives it. UI highlighting intersects descendants with values
that actually changed. Guide dependency outlines are a separate presentation state.

Historical verification on 2026-10-03 (development snapshot
`8d0bbfdeeb7fc01a6eb3b132fee14c82fced610c`):

- Exported the upstream branch to ignored `out/science-final` for testing.
- All 48 upstream runtime tests passed, including known answers, failure cases,
  type/shape checks, fixture validation, and Python/JavaScript conformance.
- All eight frontend IR fixtures passed the upstream validator using explicitly
  synthetic SourceBlock metadata for structural checks.
- All 35 default/test/exploration states across those fixtures matched upstream
  Python and JavaScript values within 1e-10.
- Generated all eight mechanisms through final `derive_playground`, including
  valid, missing, and invalid shared ExperienceSpec; checked resolved fallback and
  dependency graph agreement. Reproduce from that snapshot with
  `python tests/verify_science_integration.py --reference out/science-final`.
- Installed test environment: CPython 3.11.9, Node 24.11.1, Pydantic 2.12.5,
  NumPy 2.4.2. Upstream pinned
  requirements are 2.13.5 and 2.3.5; the frontend adds no production dependency.

These checks establish runtime integration and structural compatibility. Synthetic
metadata does not establish fidelity to a paper. Scientific verification of real
sources remains with Persons 1 and 2.

Updates must copy the science team's file intact and repeat its conformance tests;
do not repair scientific behavior in the frontend.

The integration distribution omits development tests, fixtures, and temporary
checkouts. They remain available in the verified historical commit.
