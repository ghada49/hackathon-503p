"""Minimized regressions from the first live run; no provider calls or live prompts."""
import copy
import json
from pathlib import Path

import pytest

from playground.computation import OPERATIONS
from playground.generator import (GenerationFailure, apply_restricted_patch,
                                  build_generation_messages, build_repair_context)
from playground.models import PaperMechanismIR
from playground.orchestration import assess_candidate
from playground.source import Case, FocusedEvidence, SourceBlock
from playground.trace import TraceLogger


@pytest.fixture
def candidate():
    return json.loads((Path(__file__).parent / 'fixtures/generic_ir.json').read_text())


def source(candidate):
    ids = {b for e in candidate['evidence'] for b in e['blocks']}
    ids.update(b for g in candidate['mechanism_grounding'] for b in g['blocks'])
    return [SourceBlock(id=id, type='paragraph', text='Posterior odds equal prior odds times the likelihood ratio.', order=i)
            for i, id in enumerate(sorted(ids))]


def prompt(candidate):
    evidence = FocusedEvidence(blocks=source(candidate), focus='Bayesian odds', audience='students')
    return build_generation_messages(Case(source_url='supplied:bayes', focus=evidence.focus,
        audience=evidence.audience), evidence, PaperMechanismIR.model_json_schema())[0]['content']


def test_prompt_explicit_operand_grammar_and_authoritative_registry(candidate):
    system = prompt(candidate)
    assert 'Reference operand: {"ref":"existing_id"}' in system
    assert 'Constant operand: {"const":<value>}' in system
    assert 'Nested operation: {"op":"<allowed_operation>","inputs":[...]}' in system
    assert '"ref" and "const" are NEVER operation names' in system
    contract = json.loads(system.split('CONTRACT\n')[1])
    assert set(contract['ALLOWED_OPERATIONS']) == set(OPERATIONS)
    assert not {'ref', 'const'} & set(contract['ALLOWED_OPERATIONS'])


def test_prompt_smallest_rubric_complete_artifact_and_visible_control_influence(candidate):
    system = prompt(candidate)
    for instruction in ['smallest artifact', '2–3 meaningful controls', '2–3 meaningful visuals',
                        'exactly 2 guided explorations', '2–3 focused tests', '1–3 meaningful invariants',
                        'not hard maximums', 'Every control must influence',
                        'displayed value or meaningful visual', 'unnecessary controls']:
        assert instruction in system


def test_prompt_prioritizes_teaching_quality_beyond_counts(candidate):
    system = prompt(candidate)
    for instruction in ('coherent teaching sequence', 'distinct/relevant aspects',
                        'primary visual materially clarifies', 'useful intermediate values'):
        assert instruction in system


@pytest.mark.parametrize('op', ['ref', 'const'])
@pytest.mark.parametrize('nested', [False, True])
def test_forbidden_operation_rejected_with_precise_trace_location(candidate, tmp_path, op, nested):
    path = 'computation.nodes.0'
    node = candidate['computation']['nodes'][0]
    if nested:
        node['inputs'][0] = {'op': op, 'inputs': [{'const': 1}]}
        path += '.inputs.0'
    else:
        node['op'] = op
    trace = TraceLogger(tmp_path / 'trace.jsonl')
    try:
        assessment = assess_candidate(candidate, source(candidate), trace=trace)
    finally:
        trace.close()
    assert not assessment.accepted
    # Keep Person 2's frozen diagnostic and authoritative scope unchanged.
    assert assessment.validation.failures[0].path == 'computation'
    assert assessment.validation.failures[0].message == 'Unknown operation: ' + op
    events = [json.loads(line) for line in (tmp_path / 'trace.jsonl').read_text().splitlines()]
    grammar = next(event['result'] for event in events if event['action'] == 'operand_grammar')
    assert grammar['locations'] == [{'path': path + '.op', 'operation': op}]


def test_computation_repair_prompt_includes_protected_external_interface(candidate):
    messages = build_repair_context(candidate, [], ['computation'], ir_model=PaperMechanismIR)
    payload = json.loads(messages[1]['content'])
    refs = payload['protected_external_references']
    assert 'posterior' in refs
    assert any(path.startswith('mechanism_grounding.') for path in refs['posterior'])
    assert any(path.startswith('visuals.') for path in refs['posterior'])
    assert any(path.startswith('tests.') for path in refs['posterior'])
    assert 'do not rename or remove' in messages[0]['content']


def minimal_candidate(field):
    return {'computation': {'nodes': [{'id': 'keep', 'op': 'add', 'inputs': [{'const': 1}, {'const': 2}]},
                                     {'id': 'free', 'op': 'add', 'inputs': [{'const': 1}, {'const': 2}]}],
                            'outputs': ['free']}, **field}


REFERENCING_FIELDS = [
    {'mechanism_grounding': [{'nodes': ['keep'], 'blocks': ['b0'], 'relationship': 'Rule'}]},
    {'visuals': [{'type': 'number', 'value': 'keep'}]},
    {'visuals': [{'type': 'bar_chart', 'bindings': {'values': 'keep'}}]},
    {'explorations': [{'expectation': {'type': 'approx', 'value': 'keep'}}]},
    {'tests': [{'assertions': [{'op': 'approx', 'value': 'keep', 'expected': 3}]}]},
    {'invariants': [{'value': 'keep', 'assertion': {'op': 'all_finite'}}]},
    {'invariants': [{'value': 'free', 'assertion': {'op': 'all_finite', 'value': 'keep'}}]},
    {'experience': {'calculation_order': ['keep']}},
    {'experience': {'emphasis_nodes': ['keep']}},
    {'experience': {'guided_mode': [{'target': 'keep', 'instruction': 'Inspect'}]}},
    {'experience': {'annotations': [{'target': 'keep', 'kind': 'hint', 'text': 'Inspect'}]}},
]


@pytest.mark.parametrize('field', REFERENCING_FIELDS)
@pytest.mark.parametrize('change', ['delete', 'rename'])
def test_repair_cannot_remove_or_rename_node_referenced_outside_scope(field, change):
    original = minimal_candidate(field)
    before = copy.deepcopy(original)
    value = copy.deepcopy(original['computation'])
    if change == 'delete':
        value['nodes'] = value['nodes'][1:]
    else:
        value['nodes'][0]['id'] = 'renamed'
    with pytest.raises(GenerationFailure, match='protected externally referenced computation IDs') as error:
        apply_restricted_patch(original, {'updates': [{'path': 'computation', 'value': value}]}, ['computation'])
    assert error.value.failures[0]['check'] == 'repair_interface'
    assert original == before


def test_scoped_nodes_repair_preserves_outputs_and_internal_refs():
    original = minimal_candidate({})
    original['computation']['outputs'] = ['keep']
    original['computation']['nodes'][1]['inputs'][0] = {'ref': 'keep'}
    value = copy.deepcopy(original['computation']['nodes'][0])
    value['id'] = 'renamed'
    messages = build_repair_context(original, [], ['computation.nodes.0'], ir_model=PaperMechanismIR)
    refs = json.loads(messages[1]['content'])['protected_external_references']['keep']
    assert 'computation.outputs.0' in refs
    assert 'computation.nodes.1.inputs.0.ref' in refs
    with pytest.raises(GenerationFailure):
        apply_restricted_patch(original, {'updates': [{'path': 'computation.nodes.0', 'value': value}]},
                               ['computation.nodes.0'])


@pytest.mark.parametrize('consumer', [
    {'op': 'map', 'inputs': [{'const': [1, 2]}], 'params': {'body': {'op': 'add', 'inputs': [{'ref': 'item'}, {'ref': 'keep'}]}}},
    {'op': 'slice', 'inputs': [{'const': [1, 2]}], 'params': {'end_ref': 'keep'}},
])
def test_operation_parameter_references_protect_external_interface(consumer):
    original = minimal_candidate({})
    original['computation']['nodes'][1] = dict(id='free', **consumer)
    value = copy.deepcopy(original['computation']['nodes'][0])
    value['id'] = 'renamed'
    with pytest.raises(GenerationFailure, match='protected externally referenced'):
        apply_restricted_patch(original, {'updates': [{'path': 'computation.nodes.0', 'value': value}]},
                               ['computation.nodes.0'])


def test_body_operand_diagnostic_has_precise_location(candidate, tmp_path):
    candidate['computation']['nodes'][0].update(op='map', inputs=[{'const': [1]}],
        params={'body': {'op': 'ref', 'inputs': [{'ref': 'item'}]}})
    trace = TraceLogger(tmp_path / 'body.jsonl')
    try:
        result = assess_candidate(candidate, source(candidate), trace=trace)
    finally:
        trace.close()
    assert not result.accepted
    events = [json.loads(line) for line in (tmp_path / 'body.jsonl').read_text().splitlines()]
    grammar = next(event['result'] for event in events if event['action'] == 'operand_grammar')
    assert grammar['locations'] == [{'path': 'computation.nodes.0.params.body.op', 'operation': 'ref'}]


def test_unreferenced_node_may_be_removed_without_protecting_prose():
    original = minimal_candidate({'teaching': {'title': 'keep'}, 'evidence': [{'claim': 'keep', 'blocks': ['keep']}]})
    value = copy.deepcopy(original['computation'])
    value['nodes'] = value['nodes'][1:]
    repaired = apply_restricted_patch(original, {'updates': [{'path': 'computation', 'value': value}]}, ['computation'])
    assert repaired['teaching'] == original['teaching']
    assert repaired['evidence'] == original['evidence']


def test_authorized_reference_update_permits_interface_change():
    original = minimal_candidate({'visuals': [{'value': 'keep'}]})
    value = copy.deepcopy(original['computation'])
    value['nodes'][0]['id'] = 'renamed'
    repaired = apply_restricted_patch(original, {'updates': [{'path': 'computation', 'value': value},
        {'path': 'visuals.0.value', 'value': 'renamed'}]}, ['computation', 'visuals.0.value'])
    assert repaired['visuals'][0]['value'] == 'renamed'


def test_interface_preserving_computation_repair_is_revalidated(candidate):
    broken = copy.deepcopy(candidate)
    broken['computation']['nodes'][0]['op'] = 'ref'
    repaired = apply_restricted_patch(broken, {'updates': [{'path': 'computation', 'value': candidate['computation']}]},
                                      ['computation'])
    assert repaired['teaching'] == broken['teaching']
    assert repaired['evidence'] == broken['evidence']
    assert assess_candidate(repaired, source(candidate)).accepted


def test_protected_interface_is_required_within_context_budget(candidate):
    with pytest.raises(GenerationFailure, match='context budget'):
        build_repair_context(candidate, [], ['computation'], ir_model=PaperMechanismIR, max_prompt_chars=50)
