# Educational experience integration contract

## Shared upstream contract

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

## Person-3-internal authoring/testing extension

Everything below describes the richer **internal** grammar accepted by explicit
`render(..., experience=local_plan)` / CLI `--experience`. Do not put these extra
fields inside shared `PaperMechanismIR.experience`. Development sidecars in the historical verified commit exercise this
implementation; they are not upstream schema examples and are not distributed. No new model call or scientific evaluator is introduced here. The supplied scientific fixtures were preserved byte-identically in that snapshot.

## Composition paths

- No experience: canonical standalone interactive explanation.
- Valid experience: compile its semantic choices into trusted components.
- Invalid structural fields, references, bounds, or composition: canonical artifact.
- Invalid internal decorative annotations: skip that annotation and retain the experience.
- Invalid shared ExperienceSpec records/references: canonical artifact.
- A visual fails at runtime: existing numeric/dependency fallback.
- Experience mounting/update fails: restore canonical controls and stage.

Compilation has no effect on science evaluation. The evaluator receives science
fields with the presentation extension removed. Diagnostics are available in the
embedded `experience.mode` and `experience.reason`; they are not added to learner
copy. Inputs are never interpreted as HTML, CSS, JS, event handlers, or expressions.

## Person-3-internal override fields

| Field | Accepted form |
| --- | --- |
| `story` | `equation_to_effect`, `input_to_output`, `build_it_step_by_step`, `compare_two_cases`, `cause_and_effect`, `before_and_after`, `iterate_and_observe`, `distribution_story`, `spatial_story` |
| `layout` | Flat alias for `interactive_stage.layout` |
| `hero_visual` | Primary teaching visual reference; missing/unknown hint resolves to the first non-formula visual |
| `calculation_order` | Ordered computation IDs; alias for `calculation_story`, with presentation inferred from existing visual/value kind |
| `emphasis_nodes` | Existing computation IDs given stronger visual emphasis |
| `hero` | `{visual, emphasis}`; emphasis is `visual`, `relationship`, or `metric` |
| `presentation` | `density`: `focused` / `comfortable` / `compact`; `hero_emphasis`; `interaction_style`: `freeform` / `stepwise`; boolean `comparison_mode` |
| `interactive_stage` | `{layout, primary_visual, secondary_visuals}` |
| `tree` | Explicit bounded component tree; overrides `interactive_stage` |
| `calculation_story` | Ordered `{node, presentation, annotation?, meaning?}` records |
| `guided_mode` | `{target, instruction, highlight_dependency_path?: boolean}`; `{focus, message}` aliases supported |
| `annotations` | `{target, kind?: "callout" / "hint" / "insight" / "warning", text, when?}` |

`build_step_by_step` and `compare_cases` are accepted story aliases. A flat example:

```json
{
  "story": "cause_and_effect",
  "layout": "controls_left",
  "hero_visual": "posterior_distribution",
  "calculation_order": ["prior_odds", "posterior_odds", "posterior"],
  "emphasis_nodes": ["posterior"],
  "guided_mode": [{"target": "prior", "instruction": "Change the prior.", "highlight_dependency_path": true}]
}
```

`hero_visual` emphasizes the bound scientific figure inside the mechanism, never
a landing-page hero. A metric focus retains a supporting meaningful figure when
one is available. An explicit `tree` controls placement; nominate a visual already
mounted in that tree to emphasize it. The older `hero.visual` reference is strict:
an invalid reference triggers canonical fallback.

The artifact shell always begins with a compact orientation and the mechanism.
There is no website navigation, sidebar, branding, offline badge, or landing-page
hero. Supplemental context, symbols, limitations, and grounding follow the hands-on
explanation. Additional complex editors collapse on narrow screens; all controls
remain accessible. The historic `hero` field is retained as a compatibility alias
for a compact supplemental result after the stage, never a title/landing hero.

`interaction_style` is descriptive metadata; a walkthrough is offered whenever
`guided_mode` is present. It never forces the learner to enter a guide. Summary
emphasis controls the trusted compact result treatment when `hero` is supplied. Density
changes spacing/reading width while maintaining control hit sizes.

Stage layouts: `controls_left_visual_right`, `controls_left`, `controls_right`,
`side_by_side`, `stacked`, `visual_first`, `equation_first`, `comparison`,
`pipeline`, `focus`, `dashboard`, `spatial`. They map to tested split, stack, grid,
or emphasis layouts. Spatial composition uses a grid; its visuals can contain
semantic scenes. A story supplies the default strategy when layout is omitted;
it does not synthesize scientific explanations or special-case paper titles.

Visual references use an existing visual's explicit `id`, if supplied; otherwise
its `value`; otherwise `type_index` (zero-based index in `ir.visuals`). Duplicate
keys receive an index suffix. Example: Bayes has `formula_0`, `pipeline_1`,
`posterior_distribution`, `posterior`. No fixture ID fields need to change.

## Component tree

```json
{
  "type": "split",
  "ratio": "40/60",
  "children": [
    {"type": "control_group", "controls": ["prior", "likelihood_ratio"]},
    {"type": "stack", "children": [
      {"type": "visual", "visual": "posterior_distribution"},
      {"type": "metric", "value": "posterior", "title": "Updated belief"}
    ]}
  ]
}
```

| Component | Data |
| --- | --- |
| `split` | Exactly two children; ratio `40/60`, `50/50`, or `60/40` |
| `stack`, `visual_first`, `equation_first`, `pipeline`, `focus` | Children in authored reading order |
| `grid` | Children, columns 1–3 |
| `control_group` | Existing control IDs; live widgets are moved, not cloned |
| `visual` | Existing visual reference |
| `comparison` | Existing visual reference; original/current snapshots |
| `formula`, `scene` | Reference to a matching existing visual |
| `metric`, `number`, `matrix`, `heatmap`, `table`, `vector`, `bar_chart`, `line_chart`, `scatter` | Existing value ID and optional title |
| `dependency_graph` | Actual computation references and current values |
| `calculation_steps` | Current calculation sequence plus a generic dependency diagram |
| `symbol_legend` | Existing symbols |
| `callout` | Plain text and optional numeric condition |

Each control must appear exactly once. Every directed stage must retain a meaningful
visualization; a metric-only/control-only layout falls back. All mandatory semantic
sections stay outside the component tree, so a composition cannot remove evidence,
limitations, explorations, or the teaching overview. Calculation stories can reorder
nodes but undisplaced `display=true` nodes remain visible. Stage arrows require
an actual downstream dependency; independent neighboring stages get no causal
arrow. Changed stages show their actual previous/current delta.

Bounds: 64 components, maximum depth 6, 12 children per container, 32 entries per
ordinary list, 256 calculation/emphasis entries, 100 guide steps or annotations,
8 secondary visuals, 2,000 characters
per authored text field. Unknown fields/components, invalid references, duplicate
story nodes, duplicate/missing controls, and invalid choices fall back as a unit.

## Walkthroughs, changes, and conditions

Guide me opens a nonmodal floating toolbar. It highlights a control, calculation,
or visual and scrolls it into view. Inputs stay usable. Back/Next reverse the
journey; End guide or Escape closes it and returns focus to Guide me. References
to visuals not mounted in the composition appear in the guide toolbar. No guide
step automatically changes inputs or claims an experiment succeeded.

What Changed derives actual deltas and dependency highlights from the evaluator
results. It shows control edits, displayed-node changes, numeric deltas, and array
entry changes. The experience supplies optional human meanings, never arithmetic.
Before/after compares the previous valid snapshot with the current one. Stage
comparisons use the original valid setup and common chart axes; no historical
values are recomputed by the UI.

Conditions are scalar display predicates only:

```json
{"value": "entropy", "op": "less_than", "threshold": 0.2}
```

Supported operators: `less_than`, `greater_than`, `equal` (exact equality).
Thresholds must be finite numbers. Missing, nonnumeric, and nonfinite runtime
values hide the annotation. Predicate display does not validate scientific claims
or fixture expectations. The interpreter remains Person 2's responsibility.

## Semantic scenes

Use an existing VisualSpec with the following `options`:

```json
{
  "layout": "horizontal_flow",
  "objects": [
    {"id": "input", "shape": "circle", "label": "Input"},
    {"id": "transform", "shape": "process", "label": "Transformation"},
    {"id": "output", "shape": "circle", "label": "Output"}
  ],
  "links": [{"from": "input", "to": "transform"}, {"from": "transform", "to": "output"}]
}
```

Layouts: horizontal/vertical flow, radial, grid. Shapes: circle, process, rect,
point. An object may use `value` for an existing evaluated value label. Coordinates
are generated by trusted code. Limits: 24 unique objects and 48 links. Missing
endpoints or unsupported choices fall back to the dependency view. The existing
restricted primitive scene grammar remains supported.
