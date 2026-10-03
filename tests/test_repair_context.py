import copy
import json

import pytest

from playground.budget import BudgetManager
from playground.generator import (BestSoFar, GenerationFailure, build_generation_messages,
    build_repair_context, repair_spec)
from playground.source import Case, SourceBlock, FocusedEvidence
from playground.trace import TraceLogger


class StubClient:
    def __init__(self, tmp_path):
        self.trace = TraceLogger(tmp_path / 'trace.jsonl')
        self.budget = BudgetManager()
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append(copy.deepcopy(messages))
        if not self.budget.semantic_calls:
            self.budget.start_semantic('generation')
        self.budget.start_semantic(kwargs['purpose'])
        return '{"updates":[]}'


@pytest.fixture
def client(tmp_path):
    client = StubClient(tmp_path)
    yield client
    client.trace.close()


def evidence():
    return FocusedEvidence(focus='Bayesian odds', audience='students', blocks=[
        SourceBlock(id='b_bayes_odds', type='equation', text='Posterior odds = prior odds * likelihood ratio.', section='Rule', order=0),
        SourceBlock(id='b_unrelated', type='paragraph', text='Unrelated experiment. ' * 80, section='Appendix', order=1),
    ])


def failure(path, check='schema'):
    return dict(check=check, severity='serious', path=path, message='Required value is invalid', repairable=True, allowed_paths=[path])


def test_generation_fits_naive_repair_overflows_compact_repair_fits(client, authoritative_model, authoritative_candidate):
    case = Case(source_url='paper', focus='Bayesian odds', audience='students')
    source = evidence()
    generation = build_generation_messages(case, source, authoritative_model.model_json_schema(), structured_output=True)
    limit = sum(len(m['content']) for m in generation)
    candidate = authoritative_candidate
    candidate['teaching']['title'] = ''
    failures = [failure('teaching.title')]
    naive = json.dumps(dict(existing_ir=candidate, failures=failures,
        SOURCE_BLOCKS=[b.model_dump() for b in source.blocks], OUTPUT_SCHEMA=authoritative_model.model_json_schema()),
        ensure_ascii=False, separators=(',', ':'))
    assert len(naive) > limit
    before = copy.deepcopy(candidate)
    repair_spec(client, candidate, failures, ['teaching.title'], evidence=source, case=case,
        ir_model=authoritative_model, max_prompt_chars=limit)
    assert sum(len(m['content']) for m in client.calls[0]) <= limit
    assert candidate == before
    payload = json.loads(client.calls[0][1]['content'])
    assert payload['failures'] == failures
    assert 'SOURCE_BLOCKS' not in payload
    assert 'OUTPUT_SCHEMA' not in payload


def test_true_budget_denial_no_semantic_call_and_keeps_best(client, authoritative_model, authoritative_candidate):
    best = BestSoFar(authoritative_candidate, {'ok': True}, 'accepted html')
    before = copy.deepcopy(authoritative_candidate)
    with pytest.raises(GenerationFailure, match='context budget'):
        repair_spec(client, authoritative_candidate, [failure('teaching.title')], ['teaching.title'],
            ir_model=authoritative_model, max_prompt_chars=100)
    assert not client.calls
    assert client.budget.semantic_calls == 0
    assert best.spec == before and best.html == 'accepted html'
    assert authoritative_candidate == before
    client.trace.flush()
    trace = open(client.trace._file.name, encoding='utf-8').read()
    assert 'repair_skipped' in trace
    assert 'context_budget' in trace


@pytest.mark.parametrize('path', ['evidence.0.claim', 'mechanism_grounding.0.relationship', 'computation.nodes.0.op'])
def test_grounding_repair_preserves_relevant_source_and_omits_unrelated(client, authoritative_model, authoritative_candidate, path):
    repair_spec(client, authoritative_candidate, [failure(path, 'grounding')], [path],
        evidence=evidence(), ir_model=authoritative_model, max_prompt_chars=6500)
    payload = json.loads(client.calls[0][1]['content'])
    assert [b['id'] for b in payload['SOURCE_BLOCKS']] == ['b_bayes_odds']
    assert payload['SOURCE_BLOCKS'][0]['text'] == evidence().blocks[0].text
    assert 'Unrelated experiment' not in client.calls[0][1]['content']


def test_missing_version_schema_fragment_is_exact_and_original_immutable(authoritative_model, authoritative_candidate):
    del authoritative_candidate['schema_version']
    before = copy.deepcopy(authoritative_candidate)
    messages = build_repair_context(authoritative_candidate, [failure('schema_version')], ['schema_version'],
        ir_model=authoritative_model, max_prompt_chars=3000)
    payload = json.loads(messages[1]['content'])
    assert payload['REPAIR_SCHEMA']['fields']['schema_version']['const'] == '1.0'
    assert authoritative_candidate == before


def test_huge_required_candidate_field_denied_before_call(client, authoritative_model, authoritative_candidate):
    authoritative_candidate['evidence'][0]['claim'] = 'x' * 20000
    with pytest.raises(GenerationFailure, match='context budget'):
        repair_spec(client, authoritative_candidate, [failure('evidence.0.claim')], ['evidence.0.claim'],
            evidence=evidence(), ir_model=authoritative_model, max_prompt_chars=3000)
    assert not client.calls


def test_budget_is_enforced_after_unicode_and_quote_serialization(authoritative_model, authoritative_candidate):
    authoritative_candidate['teaching']['title'] = 'quoted " \\ ☃' * 20
    failures = [failure('teaching.title')]
    messages = build_repair_context(authoritative_candidate, failures, ['teaching.title'],
        ir_model=authoritative_model, max_prompt_chars=4000)
    actual = sum(len(m['content']) for m in messages)
    assert actual <= 4000
    with pytest.raises(GenerationFailure):
        build_repair_context(authoritative_candidate, failures, ['teaching.title'],
            ir_model=authoritative_model, max_prompt_chars=100)


def test_synthetic_allowed_scope_rejected(authoritative_model, authoritative_candidate):
    with pytest.raises(GenerationFailure):
        build_repair_context(authoritative_candidate, [], ['computation.nodes.0.inputs.0.Ref.ref'],
            ir_model=authoritative_model)


@pytest.mark.parametrize('path,property_name', [('teaching', 'title'), ('controls.0', 'default')])
def test_compact_schema_preserves_real_property_names(authoritative_model, authoritative_candidate, path, property_name):
    messages = build_repair_context(authoritative_candidate, [failure(path)], [path],
        ir_model=authoritative_model, max_prompt_chars=10000)
    fragment = json.loads(messages[1]['content'])['REPAIR_SCHEMA']['fields'][path]
    assert property_name in fragment['properties']


def test_optional_surroundings_cannot_starve_required_grounding_evidence(authoritative_model, authoritative_candidate):
    path = 'evidence.0.claim'
    source = evidence()
    source.blocks[0].text *= 10
    messages = build_repair_context(authoritative_candidate, [failure(path, 'grounding')], [path], source,
        ir_model=authoritative_model, max_prompt_chars=6500)
    payload = json.loads(messages[1]['content'])
    payload.pop('surrounding_fields')
    minimal_size = len(messages[0]['content']) + len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    tight = build_repair_context(authoritative_candidate, [failure(path, 'grounding')], [path], source,
        ir_model=authoritative_model, max_prompt_chars=minimal_size)
    assert sum(len(m['content']) for m in tight) <= minimal_size
    assert json.loads(tight[1]['content'])['SOURCE_BLOCKS'][0]['id'] == 'b_bayes_odds'


def test_reference_repair_receives_valid_identifier_vocabulary(authoritative_model, authoritative_candidate):
    authoritative_candidate['computation']['nodes'][0]['inputs'][0] = {'ref': 123}
    path = 'computation.nodes.0.inputs.0.ref'
    messages = build_repair_context(authoritative_candidate, [failure(path)], [path],
        ir_model=authoritative_model, max_prompt_chars=6500)
    vocabulary = json.loads(messages[1]['content'])['reference_ids']
    assert vocabulary['controls'] == ['prior', 'likelihood_ratio']
    assert vocabulary['nodes'] == [node['id'] for node in authoritative_candidate['computation']['nodes']]


def test_reference_repair_tolerates_malformed_sibling_controls(authoritative_model, authoritative_candidate):
    authoritative_candidate['controls'] = None
    authoritative_candidate['computation']['nodes'][0]['inputs'][0] = {'ref': 123}
    paths = ['controls', 'computation.nodes.0.inputs.0.ref']
    messages = build_repair_context(authoritative_candidate, [failure(path) for path in paths], paths,
        ir_model=authoritative_model, max_prompt_chars=10000)
    payload = json.loads(messages[1]['content'])
    assert payload['reference_ids']['controls'] == []
    assert payload['allowed_paths'] == paths


@pytest.mark.parametrize('malformed', [None, [{'nodes': None, 'blocks': None, 'relationship': ''}]])
def test_grounding_context_tolerates_invalid_sibling_rows(authoritative_model, authoritative_candidate, malformed):
    authoritative_candidate['mechanism_grounding'] = malformed
    path = 'computation.nodes.0.op'
    messages = build_repair_context(authoritative_candidate, [failure(path, 'grounding')], [path], evidence(),
        ir_model=authoritative_model, max_prompt_chars=6500)
    assert json.loads(messages[1]['content'])['SOURCE_BLOCKS']


def test_fallback_evidence_yields_optional_surroundings_at_exact_budget(authoritative_model, authoritative_candidate):
    authoritative_candidate['evidence'][0]['blocks'] = ['missing']
    source = evidence()
    source.blocks = source.blocks[:1]
    source.blocks[0].text *= 10
    path = 'evidence.0.claim'
    messages = build_repair_context(authoritative_candidate, [failure(path, 'grounding')], [path], source,
        ir_model=authoritative_model, max_prompt_chars=5000)
    payload = json.loads(messages[1]['content'])
    payload.pop('surrounding_fields')
    minimal = len(messages[0]['content']) + len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    messages = build_repair_context(authoritative_candidate, [failure(path, 'grounding')], [path], source,
        ir_model=authoritative_model, max_prompt_chars=minimal)
    assert sum(len(m['content']) for m in messages) == minimal
    assert json.loads(messages[1]['content'])['SOURCE_BLOCKS'][0]['id'] == 'b_bayes_odds'


def test_fallback_missing_ids_uses_coherent_focus_region_not_unrelated_source(authoritative_model, authoritative_candidate):
    authoritative_candidate['evidence'][0]['blocks'] = ['missing']
    path = 'evidence.0.claim'
    messages = build_repair_context(authoritative_candidate, [failure(path, 'grounding')], [path], evidence(),
        ir_model=authoritative_model, max_prompt_chars=6500)
    assert [b['id'] for b in json.loads(messages[1]['content'])['SOURCE_BLOCKS']] == ['b_bayes_odds']


def test_default_repair_budget_is_bounded(client, authoritative_model, authoritative_candidate):
    authoritative_candidate['evidence'][0]['claim'] = 'x' * 30000
    with pytest.raises(GenerationFailure, match='context budget'):
        repair_spec(client, authoritative_candidate, [failure('evidence.0.claim')], ['evidence.0.claim'],
            evidence=evidence(), ir_model=authoritative_model)
    assert not client.calls


def test_exact_required_serialized_boundary(authoritative_model, authoritative_candidate):
    del authoritative_candidate['schema_version']
    failures = [failure('schema_version')]
    messages = build_repair_context(authoritative_candidate, failures, ['schema_version'], ir_model=authoritative_model)
    minimum = sum(len(m['content']) for m in messages)
    bounded = build_repair_context(authoritative_candidate, failures, ['schema_version'],
        ir_model=authoritative_model, max_prompt_chars=minimum)
    assert sum(len(m['content']) for m in bounded) == minimum
    with pytest.raises(GenerationFailure, match='context budget'):
        build_repair_context(authoritative_candidate, failures, ['schema_version'],
            ir_model=authoritative_model, max_prompt_chars=minimum - 1)
