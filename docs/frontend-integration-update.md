# Frontend integration update

For the frontend track, `runtime/computation.js` is the shared **fixed scientific
interpreter**. Embed it before `runtime/playground-runtime.js`; do not duplicate
its math or introduce generated JS. It exposes:

```javascript
const values = PaperComputation.evaluate(ir, controlState);
const affected = PaperComputation.deriveDependencies(ir);
```

The scientific models now support the optional `experience` layer approved for
the adaptive ExperienceCompiler. Old IR without this block still works. Use:

```python
derived = derive_playground(ir, source_blocks)
experience = derived.resolved_experience   # None -> canonical Learn & Explore
visual_ids = derived.visual_ids           # parallel with ir.visuals
values = derived.evaluated_defaults
report = derived.validation               # available values do not imply a pass
```

Visuals may provide explicit `id` strings for hero selection and guided targets;
otherwise science derives `visual_0`, `visual_1`, etc. Use these resolved IDs in
the rendered UI. Layout/story enums, annotation kinds, component IDs, and fallback
rules are documented in `docs/science-runtime.md` and the exported JSON schema.

Invalid experience targets or structure use canonical layout. Invalid visual
bindings require a dependency/computation diagram plus supporting values. They
are recoverable presentation failures and never erase executable defaults.

The rubric key `meaningful_non_table_visual` remains available. The frontend/artifact
validator must establish actual rendered visual presence, required sections, and
offline behavior; the science report alone cannot establish those properties.

This handoff is stored in the repository for the frontend track to use at integration.

The freeze fixes update this same interpreter: boolean `where` keeps boolean
values when an array branch is inactive, and `map` rejects oversized projected
outputs before assembling them. Include the updated `runtime/computation.js`.
The final 48-test suite passed on Python 3.11.9 with Node parity checks and no skips.

The final interpreter also rejects arrays mixing numeric, boolean, and string
elements and checks `scan`/`concat` projected output capacity before materialization.
Visual IDs must not collide with canonical component IDs such as `controls` or
`main_visual`; collisions generate recoverable diagnostics and canonical experience
fallback. Use `derived.resolved_experience` to honor this fallback.

The orchestrator may call `derive_playground(ir, source_blocks, validation=report)`
to reuse a report for the exact unchanged IR and source context. Revalidate after
either changes; this API provides no persistent/cross-candidate cache. Invalid
operand diagnostics now name the accepted forms, and control-influence repair
scopes include narrowly selected computation paths and relevant visual bindings.
