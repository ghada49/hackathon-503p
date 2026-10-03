"""Reproduce the committed Attention showcase with an offline fixture response."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from agent import run
from playground.artifact import validate_artifact
from playground.source import load_case, normalize_source, resolve_source


def generate_showcase(output=None, workdir=None):
    output = Path(output) if output is not None else ROOT / 'examples/output/attention/index.html'
    workdir = Path(workdir) if workdir is not None else ROOT / 'out/showcase-generation'
    case_path = ROOT / 'examples/cases/attention.json'
    calls = []
    with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'offline-showcase-placeholder'}), \
            patch.object(requests.Session, 'request', side_effect=AssertionError('Network forbidden in showcase generation')):
        case = load_case(case_path)
        blocks = normalize_source(resolve_source(case, base_dir=case_path.parent, allow_url=False))
        spec = json.loads((ROOT / 'tests/fixtures/attention_ir.json').read_text(encoding='utf-8'))
        # This example input is an attributed teaching paraphrase, not a live paper extraction.
        for item in spec['evidence'] + spec['mechanism_grounding']:
            item['blocks'] = [block.id for block in blocks]

        class FixtureResponse:
            def post(self, url, **kwargs):
                calls.append(url)
                if len(calls) != 1:
                    raise AssertionError('Showcase fixture should need no repair call')
                return SimpleNamespace(status_code=200, headers={}, json=lambda: {
                    'choices': [{'message': {'content': json.dumps(spec)}}],
                    'usage': {'prompt_tokens': 20, 'completion_tokens': 30, 'total_tokens': 50}})

        code = run(case_path, workdir, 'offline/attention-fixture', session=FixtureResponse())
        if code != 0:
            raise RuntimeError('Mocked showcase pipeline did not reach FULL_SUCCESS')
    validate_artifact(workdir / 'index.html')
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(workdir / 'index.html', output)
    return output


if __name__ == '__main__':
    print(generate_showcase())
