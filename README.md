# Paper to Playground

Turn a supplied scientific paper excerpt into a grounded, interactive explanation.
One agent command generates the scientific specification, validates its mechanism,
and writes a standalone HTML playground with live controls and visualizations.

**Team:** Ghada Al Danab, Aya El Hajj, Joud Senan.

`integration3` combines the Person 3 frontend on `integration2` with the hardened
Person 1/2 `integration` branch. See [merge and verification notes](docs/integration3.md).

**Development MODEL_ID:** `deepseek/deepseek-v4.1-flash`.
The agent always uses the exact model passed through `--model`, including during
repair; it never switches models silently. Live verification results are recorded
in [submission verification](docs/submission-verification.md).

## Setup and assessment command

Python 3.11 is required; Node/npm are needed only for development browser tests.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:OPENROUTER_API_KEY = "YOUR_LOCAL_KEY"
.venv\Scripts\python.exe agent.py --input examples/cases/attention.json --output out --model deepseek/deepseek-v4.1-flash
```

For assessment, the required interface is:

```powershell
python agent.py --input case.json --output out --model MODEL_ID
```

On success, open `out/index.html`. No second renderer command is required.
The exit code is zero only after scientific acceptance, successful derivation,
HTML writing, and static artifact checks. Failed runs return nonzero, retain
available diagnostics, and remove stale or partial `index.html`.

`OPENROUTER_API_KEY` must be in the process environment; the application does not
implicitly read `.env`. Never commit credentials or pass them through case JSON.

## Example input and output

[Attention case](examples/cases/attention.json) contains a short, attributed
teaching paraphrase of Section 3.2.1 of
[Attention Is All You Need](https://arxiv.org/html/1706.03762v7), rather than a
runtime dependency on downloading the paper. Running the setup command produces
`out/index.html` plus `spec.json`, `derived_playground.json`, `source_blocks.json`,
`source_document.json`, `validation.json`, `resolution.json`, and `trace.jsonl`.

[Bayesian odds](examples/cases/bayesian-odds.json) and
[entropy](examples/cases/entropy.json) use clearly labeled, project-authored local
teaching notes to exercise scientifically different mechanisms. They are not
claimed to be excerpts from research papers. The browser tests generate example
outputs in `out/browser/` using explicitly mocked model responses.

A committed live example pairs the [supplied Bayesian input](examples/cases/bayesian-odds-supplied.json) with its [standalone HTML output](examples/outputs/bayesian-odds.html). It used the development model and reached FULL_SUCCESS on one semantic call. The reusable generator uses the same scientific schema and runtime for all inputs; paper-specific expected answers exist only in tests.

The rendered page contains concept orientation, input controls, a primary figure,
intermediate computations, What Changed, explorations, limitations, and grounding.
The HTML embeds all code/data/styles, needs no API key or network, and recomputes
using the fixed scientific interpreter rather than generated executable code.

## Architecture and ownership

| Track | Responsibility |
| --- | --- |
| Person 1 | Source normalization/retrieval, exact-model OpenRouter generation, bounded repair, budgets and trace |
| Person 2 | Shared scientific schema, validation, Python/JavaScript evaluation, dependencies, tests and invariants |
| Person 3 | Safe experience compilation, controls/figures, guidance, source presentation, self-contained HTML |

The pipeline is `case -> source -> focused evidence -> generated IR -> scientific
validation/repair -> DerivedPlayground -> HTML -> artifact checks`. Default limits
include one generation plus at most one targeted repair or compact regeneration, 570 seconds, 30,000 total completion
tokens, and bounded HTTP attempts. Generation uses the remaining total token budget; there is no 8,000-token per-call cap. Token usage, model IDs, latency, validation,
rendering, artifact checks, and final status are written to the redacted JSONL trace.

Scientific computations are declarative data interpreted by trusted code. Models
cannot author HTML, CSS, JavaScript, or executable expressions. Optional shared
ExperienceSpec selects presentation; missing/invalid choices fall back canonically.
Keep `playground/`, `runtime/`, `templates/`, and `prompts/` together.

The cheap artifact check verifies required mounts, embedded JSON and resource
packaging. It does not execute JavaScript or establish paper fidelity. Chromium
tests check the final pipeline's visible content, controls, visual updates, guides,
source links, responsiveness, console errors, and absence of external requests.

## Source delivery

A case requires `source_url`, `focus`, and `audience`. It must also provide readable
source content: e.g. `excerpt`, `source_text`, `content`, `paper_excerpt`, structured
`source_blocks`, or a local text/HTML source. Genuine extra `paper_title`/`title`
metadata is preserved. The frontend receives the real source URL and referenced
blocks; missing metadata is not invented.

URL-only input cannot be retrieved under an assessment network restriction that
allows only OpenRouter. Development URL fetching is explicitly opt-in through
`PAPER_PLAYGROUND_ALLOW_URL=1`; direct PDF extraction is not implemented. Confirm
with the instructor: ?Will each assessment case include its focused excerpt or a
local readable source, given that outbound access is restricted to OpenRouter??

## Verification

```powershell
.venv\Scripts\python.exe -m pip install pytest
.venv\Scripts\python.exe -m pytest -q
npm.cmd ci
npx.cmd playwright install chromium
npm.cmd run test:browser
```

Browser tests generate pages by the actual agent CLI entry point with mocked HTTP
responses; they incur no model costs. Live API results are labeled separately in
the verification report. Person 3's older extensive frontend suite remains at
`8d0bbfdeeb7fc01a6eb3b132fee14c82fced610c` in Git history.

## Reuse and credits

- Scientific interpreter/schema are team-authored Person 2 code, pinned at
  `e2de90d6a61d84e9add864d1866891f4444e1ddb`; see
  [runtime provenance](docs/science-runtime-provenance.md).
- Runtime dependencies: [Requests](https://requests.readthedocs.io/),
  [Pydantic](https://docs.pydantic.dev/), [NumPy](https://numpy.org/), and
  [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/).
  Development tests use [pytest](https://docs.pytest.org/) and
  [Playwright](https://playwright.dev/).
- Design guidance: [Emil Kowalski Apple design](https://www.ui-skills.com/skills/emilkowalski/apple-design)
  and [Apple HIG design skill](https://github.com/dickwu/apple-design-skill).
  User-supplied reference images inspired the ivory/forest-green palette. Those
  images are not bundled assets; typography uses local/system fonts and diagrams
  use trusted inline SVG. AI coding assistance was used in development.

Integration details: [frontend handoff](docs/person3-handoff.md),
[experience contract](docs/experience-contract.md),
[combined branch notes](docs/integration2.md).

Restore ignored design skills for future design work:

```powershell
git clone --depth 1 https://github.com/dickwu/apple-design-skill.git .agents/skills/apple-hig
git clone --depth 1 https://github.com/emilkowalski/skills.git .agents/skills/emil-source
```
