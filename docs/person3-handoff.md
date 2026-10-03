# Person 3 handoff to Persons 1 and 2

Prepared 2026-10-03 for `feature/frontend-visuals`.

This handoff describes the implementation shared on `feature/frontend-visuals`.
This branch now contains the integration distribution: renderer, runtimes, templates,
and integration documentation. Development fixtures, examples, tests, generated
output, and browser tooling are retained in Git history at
`8d0bbfdeeb7fc01a6eb3b132fee14c82fced610c`, rather than shipped here.
Pull this branch to obtain the implementation. It has not been merged to main.

The combined branch `integration2` merges this distribution with Person 1/2's
`integration` branch. Their scientific fixtures, tests, requirements, and pipeline
are present there. The removal descriptions below refer to Person 3's original
distribution. See the [combined integration notes](integration2.md) for usage.

## 1. Deliverable and ownership

Person 3 implemented a deterministic educational experience compiler that turns
validated scientific/teaching data into one interactive, self-contained HTML file.
The page works offline and recomputes values using Person 2's trusted JavaScript
runtime. It is a scientific artifact with controls, calculations, visualizations,
explorations, limitations, and source grounding.

The renderer does not inspect paper titles to choose behavior. Compositions are
selected through generic story/layout directives and references to IR values.
The current Attention page is one demonstration of the shared compiler.

| Owner | Responsibility |
| --- | --- |
| Person 1 | Source retrieval/normalization, OpenRouter/LLM calls, semantic scientific and teaching generation, upstream orchestration/trace |
| Person 2 | Scientific schema, validation, Python/JS evaluator semantics, dependencies, tests, invariants, exploration expectations |
| Person 3 | Safe presentation compilation, control widgets, figures, guidance, change explanations, responsive design, HTML packaging |

No OpenRouter integration or runtime model call was added. The LLM's structured
output is consumed by the frontend after upstream validation. The full Person 1
generation pipeline is not yet connected; end-to-end generated-paper integration remains upstream work.

## 2. Exact renderer interface

```python
from playground.renderer import render, render_to_file

html = render(
    ir,
    evaluated_values=None,
    experience=None,
    dependency_graph=None,
    source=None,
    evaluator_js=None,
)

path = render_to_file(
    ir,
    "out/index.html",
    evaluated_values=evaluated_values,
    dependency_graph=dependency_graph,
    experience=experience_dict,
    source=source_metadata_dict,
)
```

`render` returns a string. `render_to_file` creates the parent directory, writes
UTF-8 HTML, and returns a `Path`.

Accepted scientific inputs are dictionaries, Pydantic models with
`model_dump(mode="json")`, and Person 2's `DerivedPlayground` shape. For a derived
object the renderer extracts `spec`, `evaluated_defaults`, `dependency_graph`,
`visual_ids`, and `resolved_experience`. An upstream `resolved_experience=None`
is authoritative canonical fallback even if the raw spec retains an invalid block.
Explicit keyword arguments take precedence over derived values/graph.

`visible_nodes`, `resolved_visuals`, and `rubric_summary` are not consumed as
separate rendering directives in the current adapter. Displayed calculations
come from the IR's `display` flags plus calculation-story selections, and browser
components resolve visuals from `spec.visuals`.

`evaluated_values` is a flat mapping from control/node IDs to evaluated values;
Pydantic evaluated inputs are dumped to JSON mode. A dictionary containing
`evaluated_defaults` is unwrapped. The embedded runtime evaluates defaults on
opening the page, so runtime values supersede development snapshots.

`PaperMechanismIR.experience` is now official and consumed directly, including
Pydantic JSON-mode dumps. Prefer passing the complete `DerivedPlayground` so the
renderer honors resolved references and fallback. Explicit `experience=` remains
an optional Person-3-local authoring/testing override; it can intentionally override
upstream fallback. `source` should be a JSON-compatible dictionary. Convert
SourceBlock models to dictionaries before placing them in `source.blocks`.

## 3. Person 2 runtime integration

`runtime/computation.js` is copied unchanged from `origin/feature/science-runtime`:

- Commit: `e2de90d6a61d84e9add864d1866891f4444e1ddb`
- SHA-256: `5d35dbdb02236f026da382b1833ee47b83a83e58172f8f1ee0d99019029e12a4`

The frontend calls:

```javascript
PaperComputation.evaluate(spec, inputState) // flat evaluated-values object
PaperComputation.deriveDependencies(spec) // source -> transitive descendants
```

This remains Person 2-owned code. No second interpreter or Python scientific
implementation was written. Arithmetic, matrices, clipping, softmax,
normalization, iteration, scan, and other operations follow that upstream file.
Runtime updates are not automatic: synchronize the science team's file and repeat
its conformance checks whenever its semantics or schema change.

Supply the dependency graph in this direction:

```json
{
  "control_a": ["intermediate_a", "output"],
  "intermediate_a": ["output"],
  "output": []
}
```

The lists are transitive downstream computation IDs, not reverse dependencies or
only immediate children. If the graph is omitted, the trusted runtime derives it.

A trusted adapter can override evaluation through `evaluator_js` or the browser
API; adapters may return a values object or a Promise resolving to that object:

```javascript
window.PlaygroundEvaluator = {
  evaluate(spec, controls) {
    return PaperComputation.evaluate(spec, controls);
  }
};

await PlaygroundUI.setEvaluator(adapter);
PlaygroundUI.getState();
PlaygroundUI.getValues();
PlaygroundUI.dependencyPath(["control_a"]);
```

An adapter is trusted application code. Never put model-generated JavaScript in
`evaluator_js`. The normal integration needs no custom adapter.

## 4. What Person 1 needs to generate/pass

Supply validated v1.0 IR with teaching, symbols, structured controls, computation
nodes/outputs, visuals, explorations, limitation, evidence, provenance, and
mechanism grounding. Scientific tests/invariants remain upstream validation data.
The browser does not execute those assertions as an assessment engine.

For presentation:

- Use control/node labels for readable UI; IDs are stable references.
- Mark important calculations `display: true`, or include them in a calculation
  order/story. Non-story displayed nodes remain visible.
- Bind scientific figures to evaluated IDs, rather than embedding canned numeric
  results in prose.
- Supply two meaningful explorations with Change/Observe/Why and structured
  `suggested_values`. The frontend renders the provided list; it does not invent
  missing explorations or validate their scientific claims.
- Supply limitation and provenance simplifications/toy examples explicitly.
- Pass source metadata and referenced excerpts when available.
- Optionally provide an experience dictionary alongside the validated science.

The final shared scientific model supports `experience` directly. Person 1 should
emit only the seven fields below inside that block. Rich trees and compatibility
fields are Person-3-internal and are accepted only through the explicit
`experience=` override (including CLI `--experience`), not from upstream IR.
The compiler removes the presentation block before scientific browser evaluation.
The three supplied science fixtures were preserved byte-for-byte in the verified
development snapshot; this distribution does not bundle them.

## 5. Final shared ExperienceSpec

Person 2 finalized this contract at `e2de90d6a61d84e9add864d1866891f4444e1ddb`.

```json
{
  "story": "cause_and_effect",
  "layout": "controls_left",
  "hero_visual": "visual_2",
  "calculation_order": ["prior_odds", "posterior_odds", "posterior"],
  "emphasis_nodes": ["posterior"],
  "guided_mode": [{"target": "prior", "instruction": "Change the prior."}],
  "annotations": [{"target": "main_visual", "kind": "insight", "text": "Inspect the distribution."}]
}
```

This example uses the Bayesian fixture. The seven fields are the entire upstream
contract; no HTML, CSS, JavaScript, expressions, tree, condition, or dependency
highlight flag belongs in shared ExperienceSpec.

- `story`: optional/null; `equation_to_effect`, `input_to_output`,
  `build_step_by_step`, `cause_and_effect`, `compare_cases`, `iterate_and_observe`,
  `distribution_story`, `spatial_story`.
- `layout`: optional/null; `visual_first`, `equation_first`, `controls_left`,
  `controls_right`, `comparison`, `pipeline`, `focus`, `dashboard`.
- `hero_visual`: optional/null, an existing resolved visual ID.
- `calculation_order`, `emphasis_nodes`: node-ID lists, default empty, at most
  256 entries each; duplicate or missing node references fall back canonically.
- `guided_mode`: at most 100 `{target, instruction}` records, default empty.
- `annotations`: at most 100 `{target, kind, text}` records, default empty;
  kinds `callout`, `hint`, `warning`, `insight`.

Guide/annotation targets may be control IDs, computation IDs, resolved visual IDs,
or these canonical component IDs: `teaching`, `idea`, `why`, `mental_model`,
`symbols`, `controls`, `main_visual`, `equation`, `intermediates`, `what_changed`,
`explorations`, `limitation`, `source_grounding`. Instructions/text and targets
must be nonempty. Unknown/ambiguous targets or malformed shared data cause canonical
fallback; shared annotation errors are not silently treated as internal decoration.

Visual IDs come from `derived.visual_ids`, parallel to `spec.visuals`. Explicit
`VisualSpec.id` wins; otherwise the base is `visual_<zero-based-index>`.
Generated names avoid reserved explicit IDs and duplicates using `_1`, `_2`, etc.
Visual IDs must not collide with canonical components; ambiguous references use
upstream recovery. A raw IR adapter derives the same namespace. DOM visual hosts
expose it through `data-visual-id`. A bound value ID is not a shared visual ID.

Missing ExperienceSpec or upstream `resolved_experience=None` renders the canonical
artifact. Invalid shared references also fall back. All mandatory semantic sections
remain in either mode. Stories and layouts compile to trusted components.

Person-3-local `experience=` overrides retain bounded trees, `interactive_stage`,
`calculation_story`, `presentation`, legacy hero/story/layout names, optional
`highlight_dependency_path`, and scalar annotation display predicates. Those
options are documented separately in the [experience contract](experience-contract.md).
They do not extend Person 2's schema and should not be generated upstream unless
the team formally changes that schema. Internal legacy visual references still
use explicit ID, then bound value, then `type_index`; shared references always use
the final resolved visual namespace.

## 6. Controls and updates

Supported types: slider, number, checkbox, select, matrix editor, vector editor,
and sequence editor. Select values preserve their numeric/string types. Array
editors use the shape of the defaults; they are not general resizeable spreadsheets.
Matrix editors show row/column indices and the actual numeric dimensions.

Inputs use native bounds and step validation. Successful edits evaluate through
Person 2 and update bound figures, calculations, comparisons, and annotations.
Failed evaluations preserve the last valid scientific state and show a recoverable
error. Async edits retain the latest desired controls and discard stale responses.

Reset restores defaults. Exploration presets combine defaults with their
`suggested_values`, so a prior learner edit cannot silently change their baseline.
Applying a preset does not constitute frontend verification of its expectation.

## 7. Calculation story, What Changed, comparisons, and guidance

Calculation stories order bound computation stages. Each stage displays its
label, current evaluated data, optional teaching annotation, and a value delta
after changes. Arrows require a real dependency; adjacent independent calculations
do not receive an invented causal arrow.

What Changed compares the last successful snapshot with the new evaluated state:

1. Find changed controls.
2. Find their downstream IDs using the dependency graph.
3. Intersect those IDs with values that actually changed.
4. Highlight changed stages and show readable labels/deltas.
5. Show causal links where dependencies support them.

Scalar deltas show previous/current values and the difference. Array deltas show
changed-entry counts and the largest absolute difference. This is presentation
comparison, not a second scientific evaluator or an inferred scientific explanation.

The before/after disclosure compares the last successful edit. Composition
comparison panels compare the original setup with the current setup. Bar/line/
scatter comparisons share axes, and heatmaps share their numerical color domain.

Guide me is optional and nonmodal. It focuses/highlights generic control, node,
or visual IDs, opens relevant disclosures, and shows instruction text. Back/Next,
End guide, and Escape are supported. Closing returns focus to Guide me. Controls
remain editable. Optional dependency outlines are distinct from changed-value
highlights. An unmounted referenced visual can be displayed in the guide toolbar.

## 8. Visuals, safe scenes, and recovery

Supported visual types: formula, number, table, matrix, heatmap, vector,
bar chart, line chart, scatter, pipeline, nodes/edges, and scene.

Charts use trusted inline SVG with accessible titles/descriptions and inspectable
data tables. Heatmaps retain numeric labels and choose readable cell text colors.
Pipelines show readable control/node labels and actual computation references.

Graphs use `options.nodes` and `options.edges` with `source`/`target` endpoints.
The current graph component draws declarative connectivity; it does not invent
dynamic node-color/edge-weight encodings from scientific values.

Semantic scenes use trusted horizontal/vertical flow, radial, or grid placement,
up to 24 objects and 48 links. Objects support circle/process/rect/point shapes and
optional evaluated-value labels. A legacy primitive scene grammar supports line,
arrow, circle, rect, point, polyline, text, axis, and group with allowlisted numeric
attributes. Neither grammar accepts raw SVG markup or model-authored executable code.

Visual recovery tries a compatible numeric chart/heatmap/metric first, then a
generic computation diagram with supporting values. Advanced experience mounting
or updates can fall back to canonical rendering and restore the live controls.

## 9. Source grounding interface

```python
source = {
    "title": paper_title,
    "authors": authors_display_text,
    "url": paper_url,
    "section": section_display_text,
    "equation": equation_display_text,
    "blocks": [block.model_dump(mode="json") for block in source_blocks],
}
```

All fields are optional. Referenced blocks are selected using `ir.evidence[*].blocks`.
They display plain text and supplied `section`, `section_number`, `equation_number`,
and `page` metadata. Missing metadata uses an excerpt label. Heading, paragraph,
equation, algorithm, table, list, and caption text is handled safely.

Evidence claims/block IDs are visibly separate from provenance simplifications
and toy examples. Source links permit HTTP/HTTPS and are user-initiated; the page
does not fetch the source. No author, citation, excerpt, or experiment fidelity is
fabricated when metadata is absent. Source tables/equations are not parsed into
interactive tables or rendered with a LaTeX dependency.

## 10. Design and offline packaging

The latest reference-inspired design uses warm ivory cards, forest-green accents,
local serif headings, numbered sections, and an Idea/Why/Symbols summary. Wide
compositions can group matrix controls horizontally; compact layouts disclose
additional editors and keep a first control and primary figure visible.

Both requested Apple design skills were applied. Accessibility includes native
inputs, visible focus, keyboard tabs, guide dismissal/focus restoration, semantic
tables, dark appearance, reduced motion, increased contrast, and 200% text checks.
No branding, global navigation, sidebar, landing hero, or offline badge was added.

The HTML embeds the IR, presentation plan, source metadata, fixed CSS, visual
components, experience runtime, and scientific runtime. It needs no backend,
API key, CDN, remote font/image, browser model call, or runtime build step.

Titles are HTML-escaped and DOM text is assigned with `textContent`. Embedded JSON
escapes script-terminating characters and rejects nonfinite numbers. User strings
containing template markers are not interpreted as additional template instructions.

## 11. Integration files and verification history

| Files | Purpose |
| --- | --- |
| `playground/renderer.py` | Adapter and standalone HTML packaging |
| `playground/experience.py` | Shared presentation contract and internal compilation |
| `runtime/computation.js` | Exact pinned Person 2 scientific interpreter |
| `runtime/playground-runtime.js` | Controls, evaluation lifecycle, grounding, changes |
| `runtime/experience-runtime.js` | Compositions, comparisons, annotations, guide |
| `runtime/visuals.js` | Trusted figures, charts, graphs, scenes, visual recovery |
| `templates/learn_explore.html` | Mandatory artifact shell |
| `templates/artifact.css`, `experience.css`, `notebook.css` | Required shared/responsive styling |
| `README.md`, `docs/` | Integration interfaces and runtime provenance |
| `AGENTS.md`, `.gitignore`, `.gitattributes` | Ownership/maintenance guidance and repository settings |

Keep `playground/`, `runtime/`, and `templates/` together at the same root. Python
loads the template/style/runtime files from that root; these are required assets,
not generated output. No production dependencies are installed by this module.
The unused Python visual selection helper was removed; actual visual selection
and recovery run in the retained trusted browser components.

The verified development snapshot is commit
`8d0bbfdeeb7fc01a6eb3b132fee14c82fced610c`. Before cleanup it passed 24 frontend
Python tests, 27 browser tests, and all 48 final Person 2 tests. Eight mechanisms
passed upstream validation with explicitly synthetic structural source metadata;
35 default/test/exploration states matched Python/JS within `1e-10`.

Those checks covered Attention, entropy, Bayesian odds updating, repeated
contraction, piecewise clipping, two-state transition, neighbor aggregation, and
system recurrence. They included official shared ExperienceSpec, canonical
missing/invalid fallback, controls updating values/figures, What Changed,
Guide Me, offline behavior with no external requests/console errors, and
responsive accessibility. This does not establish real-paper fidelity.
Development fixtures/tests/tooling were intentionally removed from the integration
distribution; use that historical commit in a separate checkout to repeat the
full suite. The production cleanup was smoke-checked separately with generated
artifacts and the pinned runtime.

## 12. Integration commands and remaining work

```powershell
python -m playground.renderer --input path/to/validated-ir.json --output output/explanation.html
```

The JSON input may be a validated IR or a JSON-mode DerivedPlayground dump.
`--fixture` remains an alias for `--input`; there is no bundled/default fixture.
Optional flags: `--values`, `--source`, `--dependencies`, trusted `--evaluator`,
and internal `--experience`. Without the override, official IR ExperienceSpec is
consumed; absent/invalid experience uses the canonical artifact.

Person 1 should call `render_to_file(derived_playground, output, source=metadata)`
after Person 2 validation, including source-block dictionaries. Runtime revision
and dependency direction are pinned above. A real generated-paper end-to-end case
remains to be run by the integrated pipeline. The shared ExperienceSpec is adopted;
rich local presentation options remain internal rather than additional schema fields.

Current limits: existing v1.0 types/operators, mostly scalar/vector/matrix numeric
figures, fixed editor shapes, plain-text source equations/tables, and trusted
layout/scene options. Unknown scientific contracts/new controls/operators need
coordinated support; canonical fallback is not scientific repair. Stepwise mode
is descriptive and guides are optional; prediction prompts and animated staged
reveals are not implemented. Custom adapters require their own parity assurance.
