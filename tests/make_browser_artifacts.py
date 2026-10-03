"""Generate assessment-command artifacts with offline model responses for Chromium."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import main
import requests

os.environ['OPENROUTER_API_KEY'] = 'offline-browser-test-key'
for name in ('attention', 'entropy', 'generic'):
    spec = json.loads((ROOT / f'tests/fixtures/{name}_ir.json').read_text())
    for claim in spec['evidence'] + spec['mechanism_grounding']:
        claim['blocks'] = ['b0000']
    directory = ROOT / 'out/browser'
    directory.mkdir(parents=True, exist_ok=True)
    case = directory / f'{name}-case.json'
    case_data = {'source_url': f'https://example.org/{name}',
        'paper_title': f'Browser test source: {name}', 'focus': spec['teaching']['title'],
        'audience': 'students', 'excerpt': spec['teaching']['idea']}
    for mode in ('canonical', 'shared', 'invalid'):
        metadata = dict(case_data)
        if name == 'generic' and mode == 'invalid':
            metadata.pop('paper_title')
        case.write_text(json.dumps(metadata), encoding='utf-8')
        spec.pop('experience', None)
        if mode != 'canonical':
            spec['experience'] = {'story': 'cause_and_effect', 'layout': 'controls_left',
                'hero_visual': next(f'visual_{i}' for i, v in enumerate(spec['visuals']) if v['type'] != 'formula'),
                'guided_mode': [{'target': target, 'instruction': f'Inspect {target}.'}
                    for target in (spec['controls'][0]['id'], 'main_visual', 'what_changed', 'source_grounding')]}
            if mode == 'invalid':
                spec['experience']['hero_visual'] = 'missing'
        response = SimpleNamespace(status_code=200, headers={}, json=lambda: {
            'choices': [{'message': {'content': json.dumps(spec)}}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 30, 'total_tokens': 50}})
        with patch.object(requests.Session, 'post', return_value=response):
            assert main(['--input', str(case), '--output', str(directory / f'{name}-{mode}'),
                         '--model', 'deepseek/deepseek-v4.1-flash']) == 0
print('Nine assessment-command artifacts generated using mocked HTTP only.')

# Integration hardening cases still go through the real entry point; only HTTP is mocked.
for variant in ('grounding-union', 'safe-partial', 'fallback-shared', 'fallback-invalid'):
    spec = json.loads((ROOT / 'tests/fixtures/generic_ir.json').read_text())
    for claim in spec['evidence']:
        claim['blocks'] = ['b0001']  # Source normalization assigns IDs in supplied order.
    for grounding in spec['mechanism_grounding']:
        grounding['blocks'] = ['b0000', 'b0001']  # Equation plus shared paragraph.
    metadata = {'source_url': 'https://example.org/hardening', 'focus': 'Bayesian odds',
        'audience': 'students', 'source_blocks': [
            {'id': 'b2', 'type': 'equation', 'text': 'Posterior odds = prior odds times likelihood ratio.', 'order': 0},
            {'id': 'b1', 'type': 'paragraph', 'text': 'Evidence updates belief through the likelihood ratio.', 'order': 1},
            {'id': 'b3', 'type': 'paragraph', 'text': 'Unreferenced source context.', 'order': 2}]}
    if variant == 'safe-partial':
        spec['explorations'] = spec['explorations'][:1]
    if variant.startswith('fallback-'):
        spec['visuals'] = [{'id': 'mechanism', 'type': 'unsupported', 'value': 'posterior'}]
        spec['computation']['outputs'] = ['posterior']
        spec['experience'] = {'hero_visual': 'mechanism' if variant == 'fallback-shared' else 'missing',
            'layout': 'controls_left', 'guided_mode': [{'target': 'mechanism', 'instruction': 'Follow the calculation.'}]}
    directory = ROOT / 'out/browser'
    case = directory / f'{variant}-case.json'
    case.write_text(json.dumps(metadata), encoding='utf-8')
    contents = [json.dumps(spec)] + ([json.dumps({'updates': []})] if variant == 'safe-partial' else [])

    def offline_post(*args, **kwargs):
        if not contents:
            raise AssertionError('Unexpected extra model call')
        content = contents.pop(0)
        return SimpleNamespace(status_code=200, headers={}, json=lambda: {
            'choices': [{'message': {'content': content}}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 30, 'total_tokens': 50}})

    with patch.object(requests.Session, 'post', side_effect=offline_post):
        code = main(['--input', str(case), '--output', str(directory / variant), '--model', 'offline/hardening'])
    assert code == (1 if variant == 'safe-partial' else 0)
    assert not contents
print('Four hardening artifacts generated using mocked HTTP only.')
