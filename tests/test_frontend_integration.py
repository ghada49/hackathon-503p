"""All three tracks: mocked model response -> validated derived data -> HTML."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import run
from playground.models import DerivedPlayground
from playground.renderer import render_to_file


@pytest.mark.parametrize('experience', ['shared', 'absent', 'invalid'])
def test_person1_output_passes_directly_to_person3(tmp_path, monkeypatch, experience):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-test-key')
    spec = json.loads((Path(__file__).parent / 'fixtures/generic_ir.json').read_text())
    for claim in spec['evidence'] + spec['mechanism_grounding']:
        claim['blocks'] = ['b0000']
    if experience != 'absent':
        spec['experience'] = {
            'story': 'cause_and_effect', 'layout': 'controls_left',
            'hero_visual': 'visual_2' if experience == 'shared' else 'missing',
            'guided_mode': [{'target': 'main_visual', 'instruction': 'Inspect the distribution.'}],
        }

    requests = []

    class ModelResponse:
        def post(self, url, **kwargs):
            requests.append(kwargs['json']['model'])
            return SimpleNamespace(status_code=200, headers={}, json=lambda: {
                'choices': [{'message': {'content': json.dumps(spec)}}],
                'usage': {'prompt_tokens': 20, 'completion_tokens': 30, 'total_tokens': 50},
            })

    case = tmp_path / 'case.json'
    case.write_text(json.dumps({
        'source_url': 'paper', 'focus': 'Bayesian odds update', 'audience': 'students',
        'excerpt': 'Posterior odds equal prior odds multiplied by the likelihood ratio.',
    }), encoding='utf-8')
    output = tmp_path / 'output'
    assert run(case, output, 'integration/test-model', session=ModelResponse()) == 0
    assert requests == ['integration/test-model']
    assert json.loads((output / 'validation.json').read_text())['ok']
    derived = DerivedPlayground.model_validate_json((output / 'derived_playground.json').read_text())
    assert derived.evaluated_defaults['posterior'] == pytest.approx(.5625)
    source = json.loads((output / 'source_blocks.json').read_text())
    path = render_to_file(derived, output / 'index.html', source=source)
    html = path.read_text(encoding='utf-8')
    mode = 'directed' if experience == 'shared' else 'canonical'
    assert f'"mode": "{mode}"' in html
    assert 'Posterior odds equal prior odds multiplied by the likelihood ratio.' in html
    assert 'PaperComputation' in html
    assert '<script src=' not in html
