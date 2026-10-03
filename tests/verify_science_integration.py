"""Read-only integration checks against an exported, unchanged Person 2 checkout.

Run: python tests/verify_science_integration.py --reference out/science-final
Scientific evaluation/validation is imported exclusively from that checkout.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--reference', required=True)
args = parser.parse_args()
reference = Path(args.reference).resolve()
frontend = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(reference))
import numpy as np
from playground.computation import evaluate, derive_dependencies
from playground.models import SourceBlock
from playground.validation import validate_spec, derive_playground

tasks = []
for name in ('attention', 'entropy', 'generic', 'iterative', 'piecewise', 'markov', 'graph', 'recurrence'):
    spec = json.loads((frontend / f'tests/fixtures/{name}_ir.json').read_text(encoding='utf-8'))
    ids = {b for e in spec['evidence'] + spec['mechanism_grounding'] for b in e['blocks']}
    blocks = [SourceBlock(id=b, type='paragraph', text='Synthetic structural metadata; paper fidelity is not tested.', order=i)
              for i, b in enumerate(sorted(ids))]
    report = validate_spec(spec, blocks)
    assert report.ok, (name, report.model_dump())
    states = [{}, *[t['inputs'] for t in spec['tests']], *[e['change']['suggested_values'] for e in spec['explorations']]]
    tasks.extend({'spec': spec, 'inputs': state} for state in states)
    spec['experience'] = {'story': 'cause_and_effect', 'layout': 'controls_left',
        'hero_visual': next(f'visual_{i}' for i, v in enumerate(spec['visuals']) if v['type'] != 'formula'),
        'calculation_order': [n['id'] for n in spec['computation']['nodes']],
        'emphasis_nodes': [], 'guided_mode': [{'target': target, 'instruction': f'Inspect {target}.'}
            for target in (spec['controls'][0]['id'], 'main_visual', 'what_changed', 'source_grounding')],
        'annotations': [{'target': 'main_visual', 'kind': 'insight', 'text': 'Follow the evaluated values.'}]}
    derived = derive_playground(spec, blocks)
    assert derived.resolved_experience is not None, name
    assert derived.dependency_graph == derive_dependencies(derived.spec)
    for variant in ('shared', 'shared-invalid', 'shared-absent'):
        if variant == 'shared-invalid':
            spec['experience']['hero_visual'] = 'missing'
        elif variant == 'shared-absent':
            spec.pop('experience')
        result = derive_playground(spec, blocks)
        assert (result.resolved_experience is not None) == (variant == 'shared')
        payload = frontend / f'out/{name}-{variant}.json'
        payload.write_text(json.dumps(result.model_dump(mode='json')), encoding='utf-8')
        subprocess.run([sys.executable, '-m', 'playground.renderer', '--fixture', str(payload),
                        '--output', str(payload.with_suffix('.html'))], cwd=frontend, check=True, capture_output=True)

answers = json.loads(subprocess.run(['node', 'tests/js_conformance.cjs'], cwd=reference,
                    input=json.dumps(tasks), text=True, capture_output=True, check=True).stdout)
assert len(answers) == len(tasks)
for task, answer in zip(tasks, answers):
    assert answer['ok'], answer
    expected = evaluate(task['spec'], task['inputs'])
    assert set(expected) == set(answer['value'])
    for key in expected:
        if isinstance(expected[key], str):
            assert expected[key] == answer['value'][key]
        else:
            np.testing.assert_allclose(expected[key], answer['value'][key], rtol=1e-10, atol=1e-10)
print(f'8 IRs validated; {len(tasks)} states match Python/JS within 1e-10; 24 derived shared/fallback artifacts generated.')
