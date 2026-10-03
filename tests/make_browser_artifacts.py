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
