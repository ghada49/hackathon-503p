# Person 3 architecture review

Reviewed against `Architecture_v1.0_and_Specification_v1.0.md`, especially Persons
1–3 ownership, the shared interfaces, SourceBlock, and DerivedPlayground.

| Boundary | Implementation |
| --- | --- |
| Frozen scientific IR | Three shared fixtures remain byte-identical; no model/schema changes |
| Evaluated input | Dictionaries/Pydantic IR and DerivedPlayground adapters |
| Scientific calculations | Unchanged Person 2 JS runtime; no second evaluator |
| DependencyGraph | Supplied transitive graph or Person 2 derivation; changed-value intersection |
| ExperienceSpec | Official seven-field shared contract; richer grammar stays frontend-internal |
| Safety | Plain text DOM, safe JSON, trusted SVG primitives, no raw model code/styles |
| Offline output | One HTML file embeds IR, CSS, visual components, and trusted runtime |
| Recovery | Canonical absent/invalid experience; annotation skip; visual fallback; error state retention |
| Teaching rubric | Idea, why, symbols, controls, visuals, intermediates, explorations, limitation, grounding |
| Provenance | Provided source metadata only; paper-supported claims separate from teaching simplifications |

Person 2's final schema includes optional ExperienceSpec. The renderer consumes
`spec.experience` directly and honors `derived.resolved_experience`/`visual_ids`.
Rich trees and compatibility fields remain internal `experience=` overrides.
No generation calls, source retrieval, backend, trace orchestration, or API keys
were introduced. SourceBlocks are passed as `source.blocks`; they are not fetched.

The compiler, UI, and visuals contain no conditions on paper titles or fixture
names. Fixtures choose compositions through declarative references and generic
story/layout names. Additional fixtures are synthetic data, not new operator code.

Verification covers packaging, injection, recoverable composition, all eight live
mechanisms offline, both inputs, real dependency differences, zero-probability
handling, error recovery, guide progression, and source blocks of seven types.
All three shared fixtures have desktop/mobile first-viewport checks in canonical
and directed modes. Dark appearance, 200% text, reduced motion, and keyboard tabs
are checked separately. See runtime provenance for upstream scientific checks.

Final check results: 24 frontend Python tests and 27 Playwright tests pass;
JavaScript syntax checks pass. The trusted runtime is byte-identical to its pinned
upstream version, and all three supplied fixtures are byte-identical to the zip.

Files added/updated on `feature/frontend-visuals`:

- Compiler: `playground/renderer.py`, `playground/experience.py`, `playground/visuals.py`.
- Browser: `runtime/playground-runtime.js`, `runtime/experience-runtime.js`,
  `runtime/visuals.js`; unchanged upstream `runtime/computation.js` is embedded.
- Design: `templates/learn_explore.html`, `templates/artifact.css`, `templates/experience.css`.
- Acceptance: `tests/test_renderer.py`, `tests/test_experience.py`,
  `tests/browser/frontend.spec.js`, shared/synthetic fixtures, and the synthetic
  fixture authoring script. Eight experience sidecars live in `examples/experiences`.
- Documentation/configuration: `README.md`, `AGENTS.md`, `.gitignore`, `docs/`,
  `package.json`, `package-lock.json`, and `playwright.config.js`.
- Generated, ignored previews and screenshots: `out/`.

The implementation is shared on `feature/frontend-visuals`. No merge to main or
external publication was performed.

Presentation limits and unsupported combinations:

- Unknown layouts, components, executable fields, structural references, repeated
  controls, excessive trees, or both calculation ordering directives use canonical
  fallback. Invalid internal annotation objects are skipped; invalid shared records fall back.
- An unknown internal `hero_visual` hint selects the first non-formula visual;
  invalid shared `hero_visual` IDs use canonical fallback;
  invalid explicit `hero.visual` or tree visual references use canonical fallback.
- Explicit trees determine placement; `hero_visual` emphasizes an existing mount.
- Spatial layout uses trusted grid/scene placement, not arbitrary positioning.
- `interaction_style: stepwise` is descriptive; the guide remains optional.
- Predictions before edits and animated step-by-step reveals are not implemented.
- Source equations/tables/algorithms are safely readable plain text, not a LaTeX
  renderer or a source-table parser.
- Custom evaluator adapters are trusted application code; their parity is the
  integrator's responsibility. The shipped evaluator is the pinned Person 2 file.
- Scientific input is assumed validated upstream. Frontend presentation validation
  does not replace scientific or paper-fidelity validation.

Previews: `out/attention.html` is canonical; `out/index.html` is the directed
matrix/pipeline example. `out/entropy-directed.html`, `out/generic-directed.html`,
`out/iterative-directed.html`, `out/piecewise-directed.html`, and
`out/graph-directed.html` show different figure/story compositions.
