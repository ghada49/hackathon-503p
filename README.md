# Interactive Explanation Renderer

Person 3 integration module for Paper to Playground. Takes Person 2's validated
IR / DerivedPlayground and Person 1's source metadata, and produces one offline,
interactive HTML artifact. The renderer uses Python 3.11's standard library. No npm, backend,
API key, CDN, or browser model call is required.

`integration2` combines this renderer with Person 1's orchestration and Person 2's
scientific runtime from `origin/integration`. Install `requirements.txt` for that
upstream pipeline; its model generation requires `OPENROUTER_API_KEY`.
The generated HTML remains independent of those Python dependencies and credentials.

```powershell
python -m pip install -r requirements.txt
python agent.py --input case.json --output out --model YOUR_MODEL_ID
python -m playground.renderer --input out/derived_playground.json --source out/source_blocks.json --output out/index.html
```

Render after the agent exits successfully. The source-block JSON supplies excerpts;
pass the `source` metadata dictionary shown below to also include paper title/URL.
The merge does not change the agent's generation behavior or add model calls.

```python
from playground.renderer import render_to_file

render_to_file(
    derived_playground,
    "output/explanation.html",
    source={
        "title": paper_title,
        "url": paper_url,
        "blocks": [block.model_dump(mode="json") for block in source_blocks],
    },
)
```

Keep `playground/`, `runtime/`, and `templates/` together at the same repository
root when integrating. Person 2 owns the shared models, validation, and scientific
interpreter. Person 1 owns source ingestion, model calls, and orchestration.

The adapter uses `resolved_experience`, `visual_ids`, `evaluated_defaults`, and
`dependency_graph` from DerivedPlayground. Raw IR dictionaries and Pydantic models
are also accepted. The official seven-field `IR.experience` is consumed directly;
missing/invalid presentation uses the canonical artifact. Explicit `experience=`
is an optional internal authoring override, not an upstream schema extension.

CLI for an upstream-produced JSON file:

```powershell
python -m playground.renderer --input path/to/validated-ir.json --output output/explanation.html
```

`--input` also accepts a JSON-mode DerivedPlayground dump. `--fixture` remains a
compatibility alias. Optional flags: `--source`, `--values`, `--dependencies`,
`--experience` (internal override), and `--evaluator` (trusted application JS only).

Read the [integration handoff](docs/person3-handoff.md),
[experience contract](docs/experience-contract.md), and
[runtime provenance](docs/science-runtime-provenance.md).

Fixtures, examples, test suites, browser tooling, and review/planning documents
from Person 3 were removed from its integration distribution. Their verified snapshot remains
at commit `8d0bbfdeeb7fc01a6eb3b132fee14c82fced610c`; restore it in a separate checkout
when running the historical acceptance suite. Generated output and local tool
caches are not distributed.

Person 1/2 tests and scientific fixtures are included through the `integration`
merge. Run the combined suite with `python -m pytest -q` after installing pytest.

## Maintenance design instructions

`AGENTS.md` records ownership and mandatory Apple design guidance. Restore the
ignored skills if needed for future design work:

```powershell
git clone --depth 1 https://github.com/dickwu/apple-design-skill.git .agents/skills/apple-hig
git clone --depth 1 https://github.com/emilkowalski/skills.git .agents/skills/emil-source
```
