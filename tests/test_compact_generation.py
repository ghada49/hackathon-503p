import copy
import json
from pathlib import Path

import numpy as np
import pytest

from playground.generation_contract import compact_schema, compact_violations, LIMITS
from playground.models import PaperMechanismIR
from playground.computation import OPERATIONS, evaluate
from playground.orchestration import resolve_candidate
from playground.source import SourceBlock
from test_track_integration import make_client, ir, compile


def test_compact_schema_derives_from_frozen_contract_without_mutating_it():
    original = PaperMechanismIR.model_json_schema()
    before = copy.deepcopy(original)
    schema = compact_schema(original)
    assert original == before
    assert 'title' in schema['$defs']['TeachingSpec']['properties']
    assert 'default' in schema['$defs']['ControlSpec']['properties']
    for name, limit in LIMITS.items():
        assert schema['properties'][name]['maxItems'] == limit
    assert schema['properties']['explorations']['minItems'] == 2
    assert schema['$defs']['ComputationSpec']['properties']['nodes']['maxItems'] == 16
    assert set(schema['$defs']['Expression']['properties']['op']['enum']) == set(OPERATIONS)
    assert not {'tests', 'invariants', 'experience'} & set(schema['required'])
    assert not {'kind', 'shape'} & set(schema['$defs']['ComputationNode']['required'])


def test_structured_schema_not_duplicated_in_prompt(make_client, ir):
    client, http = make_client(json.dumps(ir))
    assert compile(client).accepted
    request = http.payloads[0]
    assert request['max_tokens'] == 30000
    assert request['provider'] == {'require_parameters': True}
    assert '"$defs"' not in request['messages'][0]['content']
    assert request['response_format']['json_schema']['schema']['properties']['controls']['maxItems'] == 5
    assert 'bindings alone do not supply' in request['messages'][0]['content']
    assert 'display=true' in request['messages'][0]['content']
    assert 'options.display' in request['messages'][0]['content']


@pytest.mark.parametrize('bad', ['{', '{}', '{"teaching":{}}'])
def test_catastrophic_generation_is_fresh_second_call(make_client, ir, bad):
    client, http = make_client(bad, json.dumps(ir))
    result = compile(client)
    assert result.accepted and client.budget.semantic_calls == 2 and client.budget.repairs == 1
    assert len(http.payloads) == 2
    second = http.payloads[1]
    assert second['max_tokens'] == 30000 - 30
    assert 'candidate_fields' not in second['messages'][1]['content']
    assert result.candidates['final']['validation'] == result.validation.model_dump(mode='json')
    client.trace.flush()
    events = [json.loads(x) for x in Path(client.trace._file.name).read_text().splitlines()]
    assert any(e['stage'] == 'regeneration' and e['action'] == 'compact_regeneration' for e in events)
    assert not any(e['action'] == 'repair_attempt' for e in events)


def test_second_catastrophe_never_triggers_third_call(make_client):
    client, http = make_client('{', '{')
    result = compile(client)
    assert not result.accepted and len(http.payloads) == 2
    assert result.candidates['regenerated']['disposition'] == 'UNUSABLE'


def test_excessive_node_count_regenerates_instead_of_giant_patch(make_client, ir):
    oversized = copy.deepcopy(ir)
    for i in range(17):
        oversized['computation']['nodes'].append({'id': f'extra_{i}', 'op': 'add', 'inputs': [{'const': 1}, {'const': 2}]})
    assert compact_violations(oversized) == ['computation.nodes']
    client, http = make_client(json.dumps(oversized), json.dumps(ir))
    assert compile(client).accepted
    assert 'fresh generation' in http.payloads[1]['messages'][0]['content']


def test_tests_and_invariants_are_supplementary(make_client, ir):
    ir.pop('tests'); ir.pop('invariants')
    client, http = make_client(json.dumps(ir))
    result = compile(client)
    assert result.status == 'FULL_SUCCESS' and len(http.payloads) == 1
    assert result.resolution['minima']['autonomous_checks_present']


def test_rejected_repair_keeps_matching_final_candidate_and_report(make_client, ir):
    ir['computation']['nodes'][0]['op'] = 'unknown'
    patch = {'updates': [{'path': 'computation.nodes.0.op', 'value': 'also_unknown'}]}
    client, http = make_client(json.dumps(ir), json.dumps(patch))
    result = compile(client)
    assert not result.accepted and http.payloads[1]['max_tokens'] == 4000
    assert result.candidates['initial']['candidate']['computation']['nodes'][0]['op'] == 'unknown'
    assert result.candidates['repair']['candidate']['computation']['nodes'][0]['op'] == 'also_unknown'
    assert result.candidates['final']['candidate'] == result.spec.model_dump(mode='json')
    assert result.candidates['final']['validation'] == result.validation.model_dump(mode='json')


def test_explicit_section_beats_unrelated_repeated_lexical_matches():
    from playground.source import SourceDocument, normalize_source
    from playground.retrieval import select_source_context
    document = SourceDocument(source_url='supplied', origin='supplied', blocks=[
        SourceBlock(id='h1', type='heading', text='1. Applications', section_number='1', order=0),
        SourceBlock(id='b1', type='paragraph', text='Entropy probabilities outcomes. '*1000, section_number='1', order=1),
        SourceBlock(id='h6', type='heading', text='6. Uncertainty', section_number='6', order=2),
        SourceBlock(id='b6', type='paragraph', text='The measure H is a sum of the individual contributions.', section_number='6', order=3),
    ])
    normalize_source(document)
    context = select_source_context(document, 'Section 6. Explain entropy probabilities outcomes.', 'students', max_chars=2400)
    assert any(b.text == 'The measure H is a sum of the individual contributions.' for b in context.blocks)


def test_trace_keeps_only_numeric_reasoning_usage(tmp_path, monkeypatch):
    from playground.trace import TraceLogger
    monkeypatch.setenv('OPENROUTER_API_KEY', 'private-fixture-key')
    trace = TraceLogger(tmp_path/'trace.jsonl')
    trace.log('generation','usage',{'reasoning_tokens':120,'reasoning':'hidden text','api_key':'private-fixture-key'})
    trace.close()
    result=json.loads((tmp_path/'trace.jsonl').read_text())['result']
    assert result['reasoning_tokens']==120
    assert result['reasoning']==result['api_key']=='[REDACTED]'


@pytest.mark.parametrize('name', ['attention', 'entropy', 'generic'])
def test_public_fixture_independent_scientific_acceptance(name):
    spec = json.loads((Path(__file__).parent / f'fixtures/{name}_ir.json').read_text())
    ids = {b for item in spec['evidence'] + spec['mechanism_grounding'] for b in item['blocks']}
    source = [SourceBlock(id=b, type='paragraph', text='Synthetic fixture grounding.', order=i) for i, b in enumerate(sorted(ids))]
    assert resolve_candidate(spec, source).accepted
    if name == 'attention':
        for overrides in ({}, {'use_scaling': False}, {'Q': [[1, 1], [1, 1]], 'K': [[1, 1], [1, 1]]}, {'Q': [[8, 0], [0, 1]]}):
            v = evaluate(spec, overrides)
            scores = np.asarray(v['Q']) @ np.asarray(v['K']).T
            logits = scores / np.sqrt(len(v['Q'][0])) if v['use_scaling'] else scores
            w = np.exp(logits - logits.max(axis=1, keepdims=True)); w /= w.sum(axis=1, keepdims=True)
            assert np.allclose(v['weights'], w)
            assert np.allclose(np.sum(v['weights'], axis=1), 1)
            assert np.allclose(v['attention_output'], w @ np.asarray(v['V']))
    elif name == 'entropy':
        for probabilities, count, expected in [([1, 0, 0, 0], 4, 0), ([.25]*4, 4, 2), ([.25]*4, 2, 1)]:
            v = evaluate(spec, {'probabilities': probabilities, 'num_outcomes': count})
            assert v['entropy'] == pytest.approx(expected)
            assert len(v['p']) == count and np.isfinite(v['contributions']).all()
            assert all(c == 0 for p, c in zip(v['p'], v['contributions']) if p == 0)
    else:
        assert evaluate(spec, {'prior': .3, 'likelihood_ratio': 3})['posterior'] == pytest.approx(.5625)
