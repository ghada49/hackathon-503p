# Scientific engine integration

Branch: `feature/science-runtime`. This subsystem follows Architecture/Specification
v1.0 and preserves the three supplied IR fixtures byte-for-byte. It owns no HTML,
source acquisition, OpenRouter calls, budgets, or frontend controls.

## Integration with Person 1

```python
from playground.models import PaperMechanismIR
from playground.validation import validate_spec, derive_playground

spec = PaperMechanismIR.model_validate_json(model_response_json)
report = validate_spec(spec, source_blocks=focused_evidence.blocks,
                       trace=trace_logger.event)
if report.ok:
    derived = derive_playground(spec, focused_evidence.blocks)
else:
    failures = [failure.model_dump() for failure in report.failures]
    # Orchestrator decides whether to request its one permitted repair.
```

The optional trace callback receives positional `(stage, action, result)` arguments.
Adapt it if the logger has a different signature. Every event records a performed
check. `ValidationFailure.allowed_paths` identifies affected IR subtrees; the
orchestrator's restricted patcher must still protect unrelated fields and apply
updates transactionally. This module never applies model patches.

Operand validation uses a callable discriminator over `ref` / `const` / `op`;
the serialized operand contract is unchanged. Schema failures use real IR paths,
for example `computation.nodes.0.inputs.0.inputs`, rather than union branch labels.
Allowed repair paths include the enclosing node/item and, for test/invariant/control
failures, related computation nodes. They do not open unrelated teaching or test
fields. The patcher must still enforce protected paths and revalidate.

`derive_playground()` now preserves candidates with executable default calculations
even when their validation report contains serious scientific/teaching failures.
It throws for invalid core schema or computations that cannot run. Inspect
`derived.validation.ok` before accepting success; available values are **not** a
claim that the candidate passed validation. This lets the orchestrator snapshot
a usable candidate while attempting repair. Bad visual references are recoverable
and set `visual.requires_fallback=true` rather than discarding numerical results.

Pass actual `SourceBlock`s to check evidence references. Omitting blocks leaves a
warning and `source_references_verified=false`; it does **not** verify grounding.
The fixture tests use explicitly synthetic metadata, not retrieved paper excerpts.
Scientific validation proves graph linkage, domains, test results, and invariant
behavior. It cannot prove that a prose relationship entails the computation, or
that model-authored targets are scientifically correct. Do not label the report
as a proof of formula/source correctness.

Use `PaperMechanismIR.model_json_schema()` as the generation schema. The exported
copy is `contracts/paper-mechanism-ir.schema.json`. This uses standard Pydantic
JSON Schema; providers with restrictive structured-output dialects may require
adaptation or the architecture's ordinary-JSON fallback.

`requirements-science.txt` contains tested exact dependency versions. Person 1
owns the assessed root `requirements.txt` and can include it with
`-r requirements-science.txt`. There are no runtime subprocesses, Node, GPU,
browser installation, or network requirements in this subsystem.

## Integration with Person 3

```python
from playground.computation import evaluate, derive_dependencies
from playground.validation import derive_playground

values = evaluate(spec)                    # dict of controls + all computed nodes
updated = evaluate(spec, {"prior": 0.5})   # partial control overrides
dependencies = derive_dependencies(spec)   # source ID -> transitive node IDs
derived = derive_playground(spec, blocks)  # executable defaults + validation report
```

Embed the **fixed** `runtime/computation.js` before your UI runtime. In the browser:

```javascript
const values = PaperComputation.evaluate(spec, inputState);
const dependencies = PaperComputation.deriveDependencies(spec);
```

This interpreter has no DOM access. `runtime/playground-runtime.js` remains Person
3's file. Bind UI elements to node/control IDs. Use `node.display` for intermediate
cards. All final numbers come from `values`; no model-generated code is executed.
`DerivedPlayground.resolved_visuals` starts empty for Person 3 to fill. Unknown
visuals produce recoverable warnings; the renderer must add a meaningful
dependency diagram plus supporting values. A science `report.ok` does not imply
the HTML, browser interactions, or fallback visuals have been validated.

`rubric_summary.visual.meaningful_non_table_visual` is retained as the shared
rubric key; `requested_non_table_visual` remains a compatibility alias. This is
a check of a bound visual request, not browser-render evidence.

## Optional declarative experience layer

`PaperMechanismIR.experience` is optional; existing fixtures still validate.
Generation may choose a story, layout, hero visual, calculation order, emphasis
nodes, guided steps, and annotations in the **same** semantic call. No extra
scientific interpretation call or required source-coverage field is introduced.

```json
{
  "experience": {
    "story": "equation_to_effect",
    "layout": "pipeline",
    "hero_visual": "attention_heatmap",
    "calculation_order": ["scores", "scaled_scores", "weights", "attention_output"],
    "emphasis_nodes": ["weights"],
    "guided_mode": [{"target": "Q", "instruction": "Change a query."}],
    "annotations": [{"target": "weights", "kind": "insight", "text": "Compare the weights."}]
  }
}
```

Allowed stories: `equation_to_effect`, `input_to_output`, `build_step_by_step`,
`cause_and_effect`, `compare_cases`, `iterate_and_observe`, `distribution_story`,
`spatial_story`. Allowed layouts: `visual_first`, `equation_first`, `controls_left`,
`controls_right`, `comparison`, `pipeline`, `focus`, `dashboard`. Annotation kinds:
`callout`, `hint`, `warning`, `insight`. These are choices for Person 3's trusted
ExperienceCompiler; no CSS, coordinates, HTML, executable callbacks, or arbitrary
DOM instructions are accepted as experience fields. Render all narrative strings
as text, as with the rest of the IR.

Visuals now accept an optional `id`. A hero must reference the visual's ID, not its
computation binding. With no explicit ID, `derive_visual_ids(spec)` generates
`visual_0`, `visual_1`, etc. Explicit IDs take precedence; collisions get deterministic
suffixes. `derived.visual_ids` is the parallel ID list for Person 3 to use on the
actual rendered components. Duplicate explicit IDs trigger canonical experience
fallback because their intended targets are ambiguous.

Calculation order/emphasis refer to computation nodes. Guided-step and annotation
targets refer to controls, nodes, visual IDs, or canonical component IDs:
`teaching`, `idea`, `why`, `mental_model`, `symbols`, `controls`, `main_visual`,
`equation`, `intermediates`, `what_changed`, `explorations`, `limitation`,
`source_grounding`. These IDs are a shared semantic namespace, not CSS selectors.

The science validator checks only structural references, not aesthetics. Invalid
experience enums, structure, or targets produce recoverable diagnostics and
`derived.resolved_experience=None`. Malformed optional input is discarded by the
model parser with diagnostics held privately until traced; it is never silently
interpreted as executable content. The compiler must use **resolved_experience**,
rather than blindly following `spec.experience`, and select the canonical Learn &
Explore layout when it is None. Failed visual bindings also require the renderer
to supply its dependency-diagram fallback, independently of experience layout.

Dependency keys include both controls and nodes. Values contain sorted transitive
downstream node IDs. They include references in nested bodies and dynamic slice
endpoints. Controls themselves are excluded from changed computed values, so a
decorative echo of an unused input does not pass influence validation.

## IR clarifications from the supplied fixtures

- Assertions serialize with `op`; `type` is accepted as an input alias.
- A null assertion tolerance means the default absolute tolerance `1e-6`.
- Exploration expectations use `type`, as in the specification.
- Numeric select options may have `value_kind=categorical` and are evaluated as
  numbers when the selected value is numeric. No numeric string coercion.
- `slice.params.end_ref` names a scalar stop index (exclusive). It cannot coexist
  with literal `stop`, and participates in dependencies.
- Slice bounds accept integer-valued floats such as `2.0`, which are converted to
  Python integers before slicing. Fractional bounds remain errors in both engines.
- `concat.params.promote_scalars=true` promotes scalar operands to length-one
  vectors before concatenation. Otherwise concat requires arrays.
- Unknown IR fields are rejected (except `Case`, which preserves extra fields).
  Invalid optional experience data is the presentation-only recoverable exception.

## Operator semantics

All expression operands are `{ref: id}`, `{const: value}`, or a nested operation.
Top-level nodes add `id` and optional kind/shape/display metadata. Nested `params`
accept only the keys registered for that operation. Unknown references, cycles,
duplicate IDs, and executable expression strings are rejected. Constants support
finite JSON numbers, booleans, strings, and rectangular rank-one/two arrays.

| Operations | Inputs and result |
| --- | --- |
| `add subtract multiply divide pow` | Two numeric values. Scalar broadcast or identical array shapes. Elementwise output. Divide by zero and nonfinite results fail. |
| `negate sqrt exp log log2 abs sin cos` | One numeric value; preserve shape. Logs require positive values, sqrt nonnegative values. |
| `clip` | Three numeric operands: value, lower, upper. Scalar broadcast or matching shapes; reversed bounds fail. |
| `sum product mean min max argmin argmax` | One nonempty numeric value. Default reduces all entries; optional integer `axis` reduces that dimension. Ties choose the first index; flattened indices when axis omitted. |
| `dot` | Equal-length numeric vectors -> scalar. |
| `matmul` | Numeric matrices `[m,k]` and `[k,n]` -> `[m,n]`. |
| `transpose` | Numeric matrix -> transposed matrix. |
| `index` | Array and integer scalar -> first-axis element/row. Negative indices count from end; invalid indices fail. |
| `slice` | Array; optional integer `start`, exclusive `stop`, `step`, or dynamic `end_ref`. Python-style negative indices and steps. Zero step fails. |
| `reshape` | Value + `params.shape` (positive rank-one/two dimensions); exact element count required. |
| `flatten` | Value -> row-major vector. |
| `concat` | 1–100 arrays, optional `axis` (default 0); nonconcatenated dimensions must match. Optional scalar promotion. |
| `softmax` | Stable exponentials after subtracting max. By default normalize all entries together; optional `axis` normalizes that dimension. Preserves shape. |
| `softmax_rows` | Matrix; stable softmax on each row, regardless of the generic axis parameter. |
| `normalize` | Divide by sum, globally or along optional axis; zero totals fail. This is algebraic normalization, not a claim that negative weights are probabilities. |
| `range` | 1–3 integer scalar inputs (stop / start,stop / start,stop,step), stop exclusive. Zero step fails. |
| `cumsum difference` | Numeric array. Default flattens row-major; optional axis operates along that dimension. Difference means adjacent `next-current`. |
| `equal not_equal` | Two matching types; scalar broadcast or identical shapes -> booleans. |
| `less less_equal greater greater_equal` | Two numeric values -> elementwise booleans. |
| `and or not` | Boolean operands only; shape-preserving/broadcast logical operations. |
| `where` | Boolean condition, true branch, false branch. Scalars select lazily. Array conditions mask domain-sensitive branch operations, allowing guarded zero-probability entropy. Branch shapes/types must still be compatible. |
| `map` | Array + `params.body` AST. Locals: `item` (first-axis element/row), `index`. Global references allowed; output stacks body results. |
| `elementwise` | Array + body AST. Locals `item` (scalar), flattened `index`; scalar body results preserve input shape. |
| `iterate` | Initial state and integer count; body AST uses `state`, `index`. Returns final state; zero iterations returns initial state. |
| `scan` | Initial state and vector; body AST uses `state`, `item`, `index`. Returns updated-state history, excluding initial state. Empty vector returns `[]`. |

Bounded body constructs are ASTs, not callbacks or expression strings. Iterative
state must preserve its type and shape. Rank is at most 2, each value has at most
10,000 elements, AST depth is at most 32, evaluation is at most 20,000 expression
steps, and iteration/scan is at most 100 updates. IDs `state`, `item`, `index` are
reserved for scoped body locals. Models allow at most 256 nodes and 32 controls.

`map` checks projected output rank and element count before assembling results.
Known body shapes are checked before any body executes. Dynamic shapes use one
bounded body result to check the projection before retaining it or continuing;
subsequent results must have the same shape. Outputs of exactly 10,000 elements
are allowed. `elementwise` checks that its body returns a scalar.

`where` masks elementwise log/sqrt/exp/divide/pow domains in unselected elements;
it is not a general per-element short-circuit engine for reductions or matrix
operations. Guard their scalar domains upstream or use bounded map bodies.
Boolean branches preserve boolean result types even when an entire array branch
is inactive, including nested masked conditions and downstream logical operators.

Python and JavaScript use matching row-major Neumaier compensated sums for `sum`,
`mean`, `dot`, `matmul`, normalization, softmax denominators, and cumulative sums.
For example, `sum([0.1]*10)` is `1.0` in both, and cancellation in `[1e16,1,-1e16]`
preserves `1.0`. Transcendental functions can still differ by floating-point rounding,
so conformance checks use a numerical tolerance instead of exact equality everywhere.

`validate_types_shapes()` propagates abstract types before execution and checks
both branches. `None` in a derived shape denotes a dynamic dimension (for example
after a slice controlled by outcome count). Concrete execution then checks each
actual state and any declared shapes. For array booleans, kind remains vector or
matrix, while abstract dtype is boolean. `infer_types_shapes()` returns concrete
kind/shape information at defaults or the provided input state.

## Validation and test commands

```bash
python -m pip install -r requirements-science.txt
python -m unittest discover -s tests -v
```

The suite uses standard-library unittest, so no pytest installation is required.
Node is development-only for the JS parity harness; those checks are skipped if
Node is absent. All operators have independently authored normal-case targets;
parity is also checked across domain failures, boundaries, conditional guards,
iterations, and the three supplied fixtures/scenarios. Neither interpreter
contains branches for attention, entropy, or Bayes.

Controls are tested at scalar min/default/max and nearby perturbations, checkbox
states, select options (first 32), and editor-element perturbations (first 16
elements). Each vector/matrix perturbation changes one element at a time; no
invented simultaneous all-min state. Every execution checks finite results and
declared kinds/shapes. Invariants run at defaults and all tested scenarios.
Coverage is bounded sampling, not an exhaustive proof over continuous domains.
Explorations must change visible computed values and satisfy optional structured
expectations. Expectations about increases/decreases require all entries to
strictly increase/decrease; use scalar nodes to describe aggregate changes.

The freeze regression run passed all 37 tests with no skips on actual CPython
3.11.9, NumPy 2.3.5, Pydantic 2.13.5, and Node 24.21.0. This includes boolean
`where` type parity and pre-materialization `map` allocation checks in both
interpreters. Full CLI, real-paper semantic generation, HTML compilation, browser
rendering, and offline artifact acceptance belong to the other integration tracks.
