# Final hardening verification

Verified on 2026-10-03 on `integration3`, using Python 3.11.9 and the exact development model `deepseek/deepseek-v4.1-flash`.

## Frozen integrations

Person 2's `playground/models.py`, `playground/computation.py`, `playground/validation.py`, and `runtime/computation.js` are byte-identical in Git to `e2de90d6a61d84e9add864d1866891f4444e1ddb`. Person 3 checkpoint `8d0bbfdeeb7fc01a6eb3b132fee14c82fced610c` is already an ancestor of this branch. Frozen scientific fixtures were not changed.

## Changes

The model-facing schema derives from the authoritative scientific schema and bounds controls, nodes, visuals, evidence, grounding, symbols, optional tests/invariants, and exactly two explorations. Missing tests/invariants do not block success. Invalid JSON or catastrophic contract violations use fresh compact regeneration; valid candidates with local failures retain restricted targeted repair. Both share a maximum of two semantic calls. Candidate diagnostics retain separate initial, repair/regenerated, and final reports.

Generation uses the remaining official 30,000-token total completion budget. The user explicitly removed the proposed 8,000-token generation cap. Targeted repair retains its 4,000-token allowance. Low reasoning effort is requested through OpenRouter's portable parameter with an explicit unsupported-parameter fallback; live usage shows providers can still consume substantial reasoning tokens. Only numeric reasoning usage is logged, never reasoning text or prompts.

Generic prompt guidance specifies globally unique IDs, real references, authoritative operators, exact assertions, meaningful tolerances, source-supported evidence, exploration changes relative to defaults, and the renderer's numeric `value` and formula `options.display` fields. Source selection prioritizes explicitly requested sections and uses supplied excerpts without fetching papers.

Presentation changes contain wide matrices/tables in keyboard-accessible horizontal scrolling regions and expose both explorations through Guide me when optional experience data is absent. Canonical fallback retains the scientific artifact layout. No remote runtime assets or APIs are required.

## Deterministic and browser checks

- Pinned requirements installed successfully on Python 3.11.9.
- Current full Python suite: **332 tests and 334 subtests passed**.
- Historical Person 3 frontend Python suite with current presentation files: **24 passed**.
- Current Chromium suite: **10 passed**.
- Historical Person 3 Chromium suite with current presentation files: **27 passed**.
- Live pages: **54 offline browser checks passed** across Bayes, Attention, and Entropy.
- Independent NumPy/scalar comparisons: **39 checks passed** across the same live specifications.

Live browser checks exercised control edits, visual tabs containing evaluated data, What Changed, both explorations, keyboard guide access/focus restoration, reduced motion, and containment at 390px. They observed no browser errors or external HTTP requests. Wide synthetic matrices also scroll locally with keyboard access and remain contained at 200% text size.

## Live results after the final generic prompt fix

All calls used fresh output directories, supplied source text, the real agent CLI, and the exact requested model.

| Case | Status | Semantic / HTTP calls | Prompt / completion / total tokens | Pipeline seconds | Controls / visuals / explorations | Nodes |
| --- | --- | --- | --- | --- | --- | --- |
| Bayes | FULL_SUCCESS | 1 / 1 | 2440 / 7423 / 9863 | 26.125 | 2 / 3 / 2 | 6 |
| Attention | FULL_SUCCESS | 1 / 1 | 3017 / 8971 / 11988 | 32.469 | 4 / 3 / 2 | 8 |
| Entropy | FULL_SUCCESS | 1 / 1 | 3581 / 15423 / 19004 | 78.969 | 2 / 3 / 2 | 12 |

Bayes independently produces posterior 0.5625 for p=0.3, L=3. Attention independently matches scaled/unscaled dot products, softmax weights, row sums of one, and weights @ V in five states; Q/K/V edits and scaling update live values, and equal/dominant explorations work. Entropy independently matches normalized probabilities, individual contributions, certainty=0 bits, four equal outcomes=2 bits, two equal outcomes=1 bit, and finite zero-probability contributions. Its number-of-outcomes and probability controls update the offline page.

After both Attention and Entropy succeeded, core generation changes stopped.

## Repeatability and remaining risk

The required fresh Attention repeat **failed**: one semantic/HTTP call, 3017 prompt tokens, 30,000 completion tokens, 33,017 total tokens, 93.391 seconds, `finish_reason=length`, incomplete JSON, and no accepted HTML. The official completion budget was exhausted, so a second semantic call could not proceed. **Reliable success on repeated hidden cases is not established.** Earlier live attempts also encountered intermittent provider HTTP 400 responses. These are genuine failures, not passing fixture results, and they are not concealed by the three successful runs.

The successful Entropy candidate supplies its intended numeric bounds inside generic `options` rather than the control's `min/max/step` fields. Integer outcome edits 2/3/4 work, but the frontend does not infer those bounds; arbitrary learner input can be invalid or outside the teaching domain. Failed evaluations preserve the last valid state. This remains a live-generation quality limitation.

Assessment inputs must supply excerpts or readable local source text when only OpenRouter network access is available. Development PDF extraction remains outside the production ingestion path.

## Submission artifacts and reproduction

`out/index.html` and `out/trace.jsonl` are copies of the successful Attention CLI output. The HTML is byte-identical to the page checked offline. A committed live example pairs [supplied Bayesian input](../examples/cases/bayesian-odds-supplied.json) with [standalone output](../examples/outputs/bayesian-odds.html); it contains scientific data and trusted runtime code, with no credentials or model prompts.

```powershell
python -m pip install -r requirements.txt
python agent.py --input case.json --output out --model MODEL_ID
```

This exact argument contract was exercised using Python 3.11.9 for every live run. The successful CLI produces both required files without a separate renderer/build step. Credentials, traces, screenshots, development diagnostics, caches, and `.env` remain ignored; the intentional example output is the only newly committed generated HTML.

```powershell
.venv\Scripts\python.exe -m pytest -q
npm.cmd run test:browser
```

Local live evidence and additional offline check scripts remain under ignored `out/final-hardening/` and `out/`. No model-authored executable code or paper-specific production branch was introduced.

## Files changed in the final hardening commit

- `README.md`
- `agent.py`
- `docs/submission-verification.md`
- `examples/cases/bayesian-odds-supplied.json`
- `examples/outputs/bayesian-odds.html`
- `playground/budget.py`
- `playground/generation_contract.py`
- `playground/generator.py`
- `playground/orchestration.py`
- `playground/resolution.py`
- `playground/retrieval.py`
- `playground/trace.py`
- `prompts/generate.txt`
- `prompts/repair.txt`
- `pytest.ini`
- `runtime/experience-runtime.js`
- `runtime/playground-runtime.js`
- `runtime/visuals.js`
- `templates/notebook.css`
- `tests/browser/containment.spec.js`
- `tests/browser/final-pipeline.spec.js`
- `tests/test_compact_generation.py`
- `tests/test_generation.py`
- `tests/test_generation_hardening.py`
- `tests/test_repair_context.py`
- `tests/test_source_intelligence.py`
- `tests/test_track_integration.py`
