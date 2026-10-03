# Interactive Explanation Renderer

Person 3 implementation on `feature/frontend-visuals`: a standalone scientific
artifact renderer, optional educational experience compiler, controls, visual renderers,
and browser UI. Uses the three shared
v1.0 fixtures supplied by the team, unchanged. No independent science evaluator, source
retrieval, LLM generation, scientific validation, or agent orchestration is implemented here.

Persons 1 and 2: read the [complete frontend handoff](docs/person3-handoff.md)
for exact input interfaces, runtime ownership, presentation capabilities,
verification, and remaining integration work.

Generate an offline preview using Python 3.11 (no production dependencies):

```powershell
python -m playground.renderer --fixture tests/fixtures/attention_ir.json --experience examples/experiences/attention.json --output out/index.html
```

Open `out/index.html` in a browser. Replace `attention` with `entropy` or `generic`
to preview the other mechanisms. Person 2's unchanged JavaScript evaluator is
embedded automatically and computes every displayed result from defaults and edits.
The old `_values.json` snapshots are optional development data and are superseded
by runtime evaluation. Controls, tabs, data disclosures, and responsive layout work
offline. The compact
concept orientation leads directly into the mechanism: no branding, global
navigation, sidebar, offline badge, or landing-page hero.

Preview the new directed experience:

```powershell
python -m playground.renderer --fixture tests/fixtures/entropy_ir.json --experience examples/experiences/entropy.json --output out/entropy-directed.html
```

The Person-3-internal experience sidecars select distinct compositions without editing the
science fixtures. The optional extension supports trusted component trees, layout
strategies, calculation annotations, guided walkthroughs, conditional callouts,
and comparisons. Missing or invalid experience data uses the canonical artifact layout.
See [the experience contract](docs/experience-contract.md) for the exact vocabulary.

## Person 2 integration

```python
from playground.renderer import render_to_file

render_to_file(ir, "out/index.html", evaluated_values=values,
               dependency_graph=dependencies,
               experience=optional_experience,
               source={"title": paper_title, "url": paper_url, "section": section})
```

Pydantic IR models, dictionaries, and Person 2's `DerivedPlayground` are supported.
The default `PaperComputation` implementation is vendored byte-for-byte from
`feature/science-runtime`; see [runtime provenance](docs/science-runtime-provenance.md).
An optional trusted custom JS adapter can set:

```javascript
window.PlaygroundEvaluator = {
  evaluate(ir, controls) {
    // Delegate to the science team's interpreter.
    return values; // { node_id: evaluated_value }; a Promise is also supported.
  }
};
```

You can attach an adapter after initialization using
`window.PlaygroundUI.setEvaluator(adapter)`, or pass its file with `--evaluator`.
The UI evaluates from defaults on attachment, then evaluates on each input event,
updates all displays, and marks downstream nodes whose evaluated values actually
changed. Supplied dependency graphs are the source-to-transitive-descendants map
returned by Person 2. Without one, that runtime derives the graph. Computation errors keep
the previous valid state. Stale async results are discarded. Guided setups start
from defaults so the fixture's machine-checkable expectations retain their baseline.
Scientific tests, invariants, and expectations remain Person 2's responsibility.
The official shared ExperienceSpec is read directly from `ir["experience"]` or
`DerivedPlayground.resolved_experience` (None means canonical fallback). Resolved
visual IDs use `DerivedPlayground.visual_ids`. The optional `experience=` override
is for Person-3-local authoring/testing and accepts richer internal composition;
those extensions are not part of the shared upstream contract.
It is compiled into a separate presentation payload, so the evaluator receives
the original science fields. This branch does not change Person 2's Pydantic
models or Person 1's generation prompt/call budget.

What Changed shows control and displayed-node deltas from actual evaluated
snapshots, including changed array entry counts and the largest absolute delta.
It does not invent causal interpretations. Optional node meanings come from the
experience's teaching text. The before/after disclosure compares the last change;
composition comparisons use the original setup, with shared chart scales.

`source` is optional metadata supplied by Person 1: `{title?, authors?, url?,
section?, equation?, blocks?: SourceBlock[]}`. Referenced excerpts render as plain
text, with section/equation/page metadata only when provided. Heading, paragraph,
equation, algorithm, table, list, and caption blocks need no special scientific code.
The frontend never fabricates authors, source text, or citations.

## Frontend coverage

- Slider, number, checkbox, select, matrix, vector, and sequence controls.
- Heatmap, matrix/table, vector, number, formula, bar, line, scatter, pipeline,
  nodes/edges, and a restricted scene renderer.
- Unsupported or malformed visuals try a compatible chart/heatmap/metric, then
  fall back to a computation path with supporting values.
- Scene development convention: `options.elements`, with allowlisted element
  types and numeric coordinates; numeric bindings use `{ "ref": "node_id" }`.
  Graph convention: `options.nodes` and `options.edges` (`source` / `target`).
  These option conventions are adapter points pending the shared detailed grammar.
- Semantic scenes can use `options.layout`, `objects`, and `links`; the renderer
  places objects using horizontal/vertical flow, radial, or grid layouts.
- Offline HTML with embedded fixed CSS/JS and safely serialized IR.
- First-viewport controls/results, compact-screen disclosures for additional matrix
  editors, semantic data tables, keyboard visualization tabs, focus indicators,
  dark appearance, reduced motion/transparency, and increased contrast.

Run packaging/security tests:

```powershell
python -m unittest discover -s tests -p "test_*.py"
node --check runtime/playground-runtime.js
node --check runtime/experience-runtime.js
node --check runtime/visuals.js
```

Browser checks use development-only Playwright:

```powershell
npm.cmd install
npx.cmd playwright install chromium
npm.cmd run test:browser
```

## Required design skills

Every future design task must apply both resources, as recorded in `AGENTS.md`:

- [Emil Kowalski Apple design](https://www.ui-skills.com/skills/emilkowalski/apple-design)
- [Apple HIG design reviewer](https://github.com/dickwu/apple-design-skill)

Restore their local, ignored copies if needed:

```powershell
git clone --depth 1 https://github.com/dickwu/apple-design-skill.git .agents/skills/apple-hig
git clone --depth 1 https://github.com/emilkowalski/skills.git .agents/skills/emil-source
```

They are available locally for subsequent design work. See `docs/artifact-design.md` for
the reference palette and applied principles.

Browser acceptance checks all three fixtures with and without experience data at
1280×800, 390×844, and 320×800. The concept title, orientation, first control, and
primary visual must fit in the first viewport, and website chrome must be absent.

Eight mechanisms exercise the same compiler/runtime: the three shared fixtures
plus synthetic iteration, clipping, state transition, graph aggregation, and
recurrence cases. The synthetic cases are frontend acceptance data and explicitly
do not claim paper provenance. See [architecture review](docs/frontend-review.md)
for verification, ownership boundaries, and unsupported presentation combinations.
