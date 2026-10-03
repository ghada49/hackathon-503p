# Combined integration branch

`integration2` combines Person 3's integration distribution at
`608a053668dae117b1d99a3b278dfa58d9d744d7` with the fetched Person 1/2 `integration`
branch at `d8f7725492f6a95e827a806330ee86c0289a4530`
(Integrate Person 1 orchestration with frozen scientific runtime).
Neither source branch nor main was merged into or modified by this work.

The only merge conflict was `.gitignore`. Resolution preserves frontend asset/tool
exclusions and upstream environment/cache rules, including the public `.env.example`.
The scientific runtime was identical in both branches and remains unchanged.

The agent now performs source normalization, generation, scientific validation,
derivation, rendering, and static artifact checking in one command:

```powershell
python -m pip install -r requirements.txt
python agent.py --input case.json --output out --model deepseek/deepseek-v4.1-flash
```

Successful runs create `out/index.html`. Source metadata is translated into
`source.title`, `source.url`, and `source.blocks`. Existing `source_url` dictionaries
are also supported by the standalone renderer adapter. Rendering uses no model/API
call. Read the [submission verification report](submission-verification.md) for
current tests and live-run results. The agent's process must have
`OPENROUTER_API_KEY` configured for generation.

Keep `playground/`, `runtime/`, and `templates/` together.

Current offline verification and live-run limitations are recorded in
[submission verification](submission-verification.md). Cross-track regression
and Chromium tests use mocked HTTP, with no paid model calls. The original merged
suite passed 238 tests and 334 subtests before the one-command artifact checks.

```powershell
python -m pip install pytest
python -m pytest -q
```
