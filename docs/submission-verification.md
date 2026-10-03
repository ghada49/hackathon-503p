# Submission verification

Verified on 2026-10-03 on `integration2`.

- Python: 247 tests and 334 subtests passed with the pinned requirements.
- Chromium: nine final-pipeline tests passed for Attention, entropy, and Bayesian
  odds in canonical, shared, and invalid-experience modes.
- The agent entry point now writes `index.html` in the same run after scientific
  acceptance and derivation. Static packaging checks are traced before success.
- Regression coverage includes renderer/check failures, absent derivation,
  stale/partial-page removal, source title/URL mapping, required artifact mounts,
  and external-resource rejection. The static checks do not execute JavaScript.
- Chromium checks exercise visible sections, source citations/excerpts, live
  numerical and figure updates, What Changed, guides, mobile overflow, no external
  requests, and no browser console errors. Model responses are mocked explicitly.

Example inputs are in `examples/cases/`. Browser tests generate example output at
`out/browser/attention-shared/index.html` and corresponding entropy/Bayesian paths.
These are fixture-based examples, not successful live model generations.

## Live model status

The user-selected development model is `deepseek/deepseek-v4.1-flash`.
Live attempts were made but did not produce a scientifically accepted page:
Attention encountered an exploration failure followed by a repair timeout;
Bayesian odds encountered invalid invariant references; entropy encountered
validation failures and a repair context-budget limit. Other attempts received
provider HTTP 400 responses. Live reliability remains unresolved.

At the user's request, experimental schema transport/provider routing changes,
generation/repair prompt changes, and their associated test changes were reverted
before this commit. The committed OpenRouter client and prompts retain the prior
`integration2` behavior. No further live calls were made for this commit.

Credentials, local diagnostic scripts, live traces, generated pages, screenshots,
virtual environments, and browser caches remain ignored and are not committed.
This report does not claim paper fidelity or a passing live-model run.

## Reproduce offline checks

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.venv\Scripts\python.exe -m pytest -q
npm.cmd ci
npx.cmd playwright install chromium
npm.cmd run test:browser
```
