# Combined integration branch

`integration2` combines Person 3's integration distribution at
`608a053668dae117b1d99a3b278dfa58d9d744d7` with the fetched Person 1/2 `integration`
branch at `d8f7725492f6a95e827a806330ee86c0289a4530`
(Integrate Person 1 orchestration with frozen scientific runtime).
Neither source branch nor main was merged into or modified by this work.

The only merge conflict was `.gitignore`. Resolution preserves frontend asset/tool
exclusions and upstream environment/cache rules, including the public `.env.example`.
The scientific runtime was identical in both branches and remains unchanged.

The agent outputs validated scientific data, source blocks, and DerivedPlayground.
Call Person 3's renderer after a successful agent run:

```powershell
python -m pip install -r requirements.txt
python agent.py --input case.json --output out --model YOUR_MODEL_ID
python -m playground.renderer --input out/derived_playground.json --source out/source_blocks.json --output out/index.html
```

Person 1 generation uses the configured OpenRouter key and exact model ID. Rendering
uses no model/API call. For source title/URL metadata, use the renderer's Python
`source` dictionary documented in [the frontend handoff](person3-handoff.md).
Keep `playground/`, `runtime/`, and `templates/` together.

Verification: the combined suite passed 238 tests and 334 subtests using Python
3.11 with the pinned requirements. New cross-track tests exercise the actual agent
with a mocked model response, scientific acceptance/derivation, and HTML rendering
for valid, missing, and invalid shared experience. These tests incur no API calls.
A live generated-paper run with paid model access was not performed.

```powershell
python -m pip install pytest
python -m pytest -q
```
