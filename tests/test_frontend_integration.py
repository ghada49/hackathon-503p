"""All three tracks: mocked model response -> validated derived data -> HTML."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import run
from playground.models import DerivedPlayground
from playground.artifact import validate_artifact


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
        'source_url': 'https://example.org/paper', 'paper_title': 'Supplied paper title',
        'focus': 'Bayesian odds update', 'audience': 'students',
        'excerpt': 'Posterior odds equal prior odds multiplied by the likelihood ratio.',
    }), encoding='utf-8')
    output = tmp_path / 'output'
    assert run(case, output, 'integration/test-model', session=ModelResponse()) == 0
    assert requests == ['integration/test-model']
    assert json.loads((output / 'validation.json').read_text())['ok']
    derived = DerivedPlayground.model_validate_json((output / 'derived_playground.json').read_text())
    assert derived.evaluated_defaults['posterior'] == pytest.approx(.5625)
    source = json.loads((output / 'source_blocks.json').read_text())
    assert source['url'] == 'https://example.org/paper'
    assert source['title'] == 'Supplied paper title'
    path = output / 'index.html'
    assert path.is_file()  # The assessment's agent command must create the page.
    assert validate_artifact(path)['required_sections']
    html = path.read_text(encoding='utf-8')
    mode = 'directed' if experience == 'shared' else 'canonical'
    assert f'"mode": "{mode}"' in html
    assert 'Posterior odds equal prior odds multiplied by the likelihood ratio.' in html
    assert 'PaperComputation' in html
    assert '<script src=' not in html
    events = [json.loads(line) for line in (output / 'trace.jsonl').read_text().splitlines()]
    assert any(event['action'] == 'render_html' and event['result']['success'] for event in events)
    assert any(event['action'] == 'validate_html' and event['result']['success'] for event in events)
    assert events[-1]['result']['success'] is True


@pytest.mark.parametrize('failure', ['render', 'validate', 'missing_derived'])
def test_artifact_failure_cannot_report_success_or_keep_stale_html(tmp_path, monkeypatch, failure):
    from playground.validation import derive_playground
    from playground.models import SourceBlock
    import agent
    spec = json.loads((Path(__file__).parent / 'fixtures/generic_ir.json').read_text())
    ids = {block for item in spec['evidence'] + spec['mechanism_grounding'] for block in item['blocks']}
    source = [SourceBlock(id=b, type='paragraph', text='Structural test context.', order=i)
              for i, b in enumerate(sorted(ids))]
    derived = derive_playground(spec, source)
    monkeypatch.setattr('playground.orchestration.compile_scientific_spec', lambda *args, **kwargs:
        SimpleNamespace(spec=derived.spec, accepted=True, reason=None, validation=derived.validation,
                        derived=None if failure == 'missing_derived' else derived))

    def fail(*args, **kwargs):
        # Exercise cleanup even if rendering produced a partial file.
        (tmp_path / 'output/index.html').write_text('partial output')
        raise ValueError('Simulated artifact failure')

    if failure == 'render':
        monkeypatch.setattr(agent, 'render_to_file', fail)
    elif failure == 'validate':
        monkeypatch.setattr(agent, 'validate_artifact', fail)
    case = tmp_path / 'case.json'
    case.write_text(json.dumps({'source_url': 'paper', 'focus': 'odds', 'audience': 'students',
                               'excerpt': 'Posterior odds combine prior odds and evidence.'}))
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'index.html').write_text('stale success')
    assert run(case, output, 'integration/test-model') == 1
    assert not (output / 'index.html').exists()
    assert (output / 'validation.json').exists()
    events = [json.loads(line) for line in (output / 'trace.jsonl').read_text().splitlines()]
    assert events[-1]['result']['success'] is False
