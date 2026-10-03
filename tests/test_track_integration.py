"""Cross-track gates use the actual frozen scientific runtime, with offline HTTP only."""
import copy
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from agent import run
from playground import models, orchestration, validation
from playground.budget import BudgetManager
from playground.generator import OpenRouterClient, build_generation_messages
from playground.retrieval import select_source_context
from playground.source import Case, SourceDocument, normalize_source
from playground.trace import TraceLogger

FROZEN_SHA = 'e2de90d6a61d84e9add864d1866891f4444e1ddb'
FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture
def ir():
    result = json.loads((FIXTURES / 'generic_ir.json').read_text())
    for claim in result['evidence']:
        claim['blocks'] = ['b0000']
    for grounding in result['mechanism_grounding']:
        grounding['blocks'] = ['b0000']
    return result


def context():
    document = SourceDocument(source_url='paper', origin='supplied', raw_text=
        'Posterior odds equal prior odds multiplied by the likelihood ratio.')
    normalize_source(document)
    return select_source_context(document, 'Bayesian odds update', 'students')


def case():
    return Case(source_url='paper', focus='Bayesian odds update', audience='students')


class HTTP:
    def __init__(self, *contents):
        self.contents = list(contents)
        self.payloads = []

    def post(self, url, **kwargs):
        self.payloads.append(copy.deepcopy(kwargs['json']))
        if not self.contents:
            raise AssertionError('Unexpected extra request')
        content = self.contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(status_code=200, headers={}, json=lambda: dict(
            choices=[dict(message=dict(content=content))],
            usage=dict(prompt_tokens=20, completion_tokens=30, total_tokens=50)))


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-integration-key')
    traces = []
    def make(*contents):
        trace = TraceLogger(tmp_path / f'trace-{len(traces)}.jsonl')
        traces.append(trace)
        http = HTTP(*contents)
        return OpenRouterClient('same/frozen-model', BudgetManager(), trace, session=http), http
    yield make
    for trace in traces:
        trace.close()


def patch(path, value):
    return json.dumps({'updates': [{'path': path, 'value': value}]})


def compile(client):
    return orchestration.compile_scientific_spec(client, context(), case(), max_prompt_chars=24000)


def test_person1_uses_exported_source_models():
    document = SourceDocument(source_url='paper', origin='supplied', raw_text='Original rule.')
    blocks = normalize_source(document)
    assert isinstance(document, models.SourceDocument)
    assert isinstance(blocks[0], models.SourceBlock)
    assert isinstance(case(), models.Case)
    assert isinstance(context(), models.FocusedEvidence)


def test_valid_generated_ir_is_scientifically_accepted_and_derived(make_client, ir):
    client, http = make_client(json.dumps(ir))
    result = compile(client)
    assert result.accepted
    assert result.validation.ok
    assert result.derived.evaluated_defaults['posterior'] == pytest.approx(0.5625)
    assert len(http.payloads) == 1
    assert not result.repair_attempted


def test_invalid_reference_triggers_one_authoritative_repair(make_client, ir):
    ir['computation']['nodes'][0]['inputs'][0]['ref'] = 'unknown'
    before = copy.deepcopy(ir)
    client, http = make_client(json.dumps(ir), patch('computation.nodes.0.inputs.0.ref', 'prior'))
    result = compile(client)
    assert result.accepted and result.validation.ok
    assert len(http.payloads) == 2
    payload = json.loads(http.payloads[1]['messages'][1]['content'])
    assert payload['allowed_paths'] == ['computation']  # Actual frozen report scope.
    assert any(f['check'] == 'computation' for f in payload['failures'])
    assert payload['reference_ids']['controls'] == ['prior', 'likelihood_ratio']
    assert ir == before
    assert {request['model'] for request in http.payloads} == {'same/frozen-model'}


def test_external_interface_rejection_preserves_best_and_is_traced(make_client, ir):
    ir['computation']['nodes'][0]['op'] = 'ref'
    renamed = copy.deepcopy(ir['computation'])
    renamed['nodes'][0]['id'] = 'renamed'
    client, http = make_client(json.dumps(ir), patch('computation', renamed))
    result = compile(client)
    assert not result.accepted and result.repair_attempted
    assert result.spec.model_dump()['computation'] == models.PaperMechanismIR.model_validate(ir).model_dump()['computation']
    assert result.spec.teaching.model_dump() == ir['teaching']
    assert result.spec.evidence[0].model_dump() == ir['evidence'][0]
    assert len(http.payloads) == 2
    client.trace.flush()
    events = [json.loads(line) for line in Path(client.trace._file.name).read_text().splitlines()]
    assert any(event['action'] == 'interface_rejected' for event in events)


@pytest.mark.parametrize('operand', [{}, {'ref': 'prior', 'const': 1}, {'op': 'add', 'inputs': [{}]}])
def test_final_operand_diagnostics_and_actual_paths(make_client, ir, operand):
    ir['computation']['nodes'][0]['inputs'][0] = operand
    client, http = make_client(json.dumps(ir), patch('computation.nodes.0.inputs.0', {'ref': 'prior'}))
    result = compile(client)
    assert result.accepted
    payload = json.loads(http.payloads[1]['messages'][1]['content'])
    assert any(f['message'] == 'Operand must be {ref}, {const}, or {op, inputs}.' for f in payload['failures'])
    assert payload['allowed_paths'] == ['computation.nodes.0']
    assert all('Ref' not in (f['path'] or '') for f in payload['failures'])


def test_dead_control_scopes_are_person2_scopes(make_client, ir):
    ir['controls'].append(dict(id='unused', type='slider', label='Unused', value_kind='scalar', default=1, min=0, max=2))
    # A scientific test depends on this control: optional pruning is unsafe.
    ir['tests'][0]['inputs']['unused'] = 1
    report = validation.validate_spec(ir, context().blocks)
    expected = sorted({path for f in report.failures if f.repairable for path in f.allowed_paths})
    client, http = make_client(json.dumps(ir), '{"updates":[]}')
    result = compile(client)
    assert not result.accepted
    payload = json.loads(http.payloads[1]['messages'][1]['content'])
    assert payload['allowed_paths'] == expected
    assert 'controls.2' in expected and any(path.startswith('computation.nodes.') for path in expected)
    assert any(path.startswith('visuals.') for path in expected)
    assert not any(path.startswith(('teaching', 'evidence', 'tests')) for path in expected)


@pytest.mark.parametrize('extra', ['control', 'exploration'])
def test_safe_extra_cleanup_avoids_semantic_repair(make_client, ir, extra):
    if extra == 'control':
        ir['controls'].append(dict(id='unused', type='slider', label='Unused', value_kind='scalar', default=1, min=0, max=2))
    else:
        e = copy.deepcopy(ir['explorations'][0])
        e['title'] = 'Extra invalid exploration'
        e['expectation']['expected'] = 100
        ir['explorations'].append(e)
    client, http = make_client(json.dumps(ir))
    result = compile(client)
    assert result.accepted and result.status == 'FULL_SUCCESS'
    assert not result.repair_attempted
    assert len(http.payloads) == 1
    assert len(result.resolution['strict_reports']) == 2


def test_partial_cli_artifact_is_honest_when_quality_minimum_fails(tmp_path, monkeypatch, ir):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-integration-key')
    ir['explorations'][1] = copy.deepcopy(ir['explorations'][0])
    ir['explorations'][1]['title'] = 'Same interaction'
    input_path = tmp_path / 'case.json'
    input_path.write_text(json.dumps({**case().model_dump(), 'excerpt': context().blocks[0].text}))
    output = tmp_path / 'out'
    http = HTTP(json.dumps(ir), '{"updates":[]}')
    assert run(input_path, output, 'same-model', session=http) == 1
    assert len(http.payloads) == 2
    payload = json.loads(http.payloads[1]['messages'][1]['content'])
    assert payload['allowed_paths'] == ['explorations.1']
    assert (output / 'derived_playground.json').exists()
    assert json.loads((output / 'validation.json').read_text())['ok'] is True
    assert json.loads((output / 'resolution.json').read_text())['status'] == 'USABLE_PARTIAL'
    assert json.loads((output / 'trace.jsonl').read_text().splitlines()[-1])['result']['success'] is False


def test_usable_partial_repair_replaces_unusable_original(make_client, ir):
    good_computation = copy.deepcopy(ir['computation'])
    ir['computation']['nodes'][0]['op'] = 'ref'
    ir['controls'][1]['min'] = ir['controls'][1]['max'] = ir['controls'][1]['default']
    client, http = make_client(json.dumps(ir), patch('computation', good_computation))
    result = compile(client)
    assert not result.accepted and result.status == 'USABLE_PARTIAL'
    assert result.derived is not None
    assert result.spec.computation.nodes[0].op == good_computation['nodes'][0]['op']
    assert not result.validation.ok
    assert len(http.payloads) == 2


@pytest.mark.parametrize('repair', ['malformed', '{"updates":[{"path":"teaching.title","value":"tampered"}]}', '{"updates":[]}'])
def test_failed_repair_preserves_original_usable_candidate(make_client, ir, repair):
    ir['symbols'] = []
    original = copy.deepcopy(ir)
    client, http = make_client(json.dumps(ir), repair)
    result = compile(client)
    assert not result.accepted and result.repair_attempted
    assert result.spec.model_dump()['symbols'] == []
    assert result.spec.teaching.title == original['teaching']['title']
    assert result.derived.evaluated_defaults['posterior'] == pytest.approx(0.5625)
    assert ir == original
    assert len(http.payloads) == 2


def test_evaluated_values_do_not_imply_acceptance(make_client, ir):
    ir['symbols'] = []
    client, _ = make_client(json.dumps(ir), '{"updates":[]}')
    result = compile(client)
    assert result.derived is not None
    assert not result.validation.ok
    assert not result.accepted


def test_report_reused_for_exact_assessment_and_invalidated_after_repair(make_client, ir, monkeypatch):
    ir['symbols'] = []
    valid_symbols = json.loads((FIXTURES / 'generic_ir.json').read_text())['symbols']
    reports = []
    reused = []
    original_validate = orchestration.validate_spec
    original_derive = orchestration.derive_playground
    def validate(*args, **kwargs):
        report = original_validate(*args, **kwargs)
        reports.append(report)
        return report
    def derive(spec, source_blocks, *, validation):
        assert validation is reports[-1]
        reused.append(validation)
        return original_derive(spec, source_blocks, validation=validation)
    monkeypatch.setattr(orchestration, 'validate_spec', validate)
    monkeypatch.setattr(orchestration, 'derive_playground', derive)
    client, _ = make_client(json.dumps(ir), patch('symbols', valid_symbols))
    result = compile(client)
    assert result.accepted
    assert len(reports) == 2 and len(reused) == 2
    assert reports[0] is not reports[1]
    assert not reports[0].ok and reports[1].ok


def test_changed_source_context_always_gets_new_report(ir):
    first = orchestration.assess_candidate(ir, context().blocks)
    changed = [models.SourceBlock(id='other', type='paragraph', text='Different source.', order=0)]
    second = orchestration.assess_candidate(ir, changed)
    assert first.validation.ok and not second.validation.ok
    assert first.validation is not second.validation


@pytest.mark.parametrize('experience', [None, {'story': 'input_to_output', 'hero_visual': 'visual_1'},
    {'story': 'invalid'}, {'guided_mode': [{'target': 'missing', 'instruction': 'Observe'}]}])
def test_experience_uses_authoritative_canonical_fallback_without_repair(make_client, ir, experience):
    if experience is not None:
        ir['experience'] = experience
    client, http = make_client(json.dumps(ir))
    result = compile(client)
    assert result.accepted
    assert len(http.payloads) == 1
    expected_present = experience is not None and experience.get('story') == 'input_to_output'
    assert (result.derived.resolved_experience is not None) == expected_present


def test_visual_component_collision_is_recoverable(make_client, ir):
    ir['visuals'][1]['id'] = 'controls'
    ir['experience'] = {'hero_visual': 'controls'}
    client, http = make_client(json.dumps(ir))
    result = compile(client)
    assert result.accepted and len(http.payloads) == 1
    assert result.derived.resolved_experience is None


@pytest.mark.parametrize('expression,reason', [
    ({'op': 'equal', 'inputs': [{'const': [1, '1']}, {'const': [1, 1]}]}, 'single type'),
    ({'op': 'concat', 'inputs': [{'op': 'range', 'inputs': [{'const': 6000}]}, {'op': 'range', 'inputs': [{'const': 6000}]}]}, 'projected output'),
])
def test_mixed_arrays_and_allocation_failures_stay_clean(make_client, ir, expression, reason):
    ir['computation'] = dict(nodes=[dict(id='invalid', **expression)], outputs=['invalid'])
    ir['mechanism_grounding'][0]['nodes'] = ['invalid']
    client, http = make_client(json.dumps(ir), '{"updates":[]}')
    result = compile(client)
    assert not result.accepted
    assert any(reason in failure.message for failure in result.validation.failures)
    assert len(http.payloads) == 2


def test_source_grounding_missing_ids_is_not_accepted(make_client, ir):
    ir['evidence'][0]['blocks'] = ['missing']
    client, _ = make_client(json.dumps(ir), '{"updates":[]}')
    result = compile(client)
    assert not result.accepted
    assert any(f.check == 'grounding' for f in result.validation.failures)


def test_cli_writes_scientific_report_and_preserved_best_on_failure(tmp_path, monkeypatch, ir):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-integration-key')
    ir['symbols'] = []
    input_path = tmp_path / 'case.json'
    input_path.write_text(json.dumps({**case().model_dump(), 'excerpt': context().blocks[0].text}))
    output = tmp_path / 'out'
    http = HTTP(json.dumps(ir), '{"updates":[]}')
    assert run(input_path, output, 'same-model', session=http) == 1
    assert json.loads((output / 'validation.json').read_text())['ok'] is False
    assert json.loads((output / 'spec.json').read_text())['symbols'] == []
    assert (output / 'derived_playground.json').exists()
    assert json.loads((output / 'trace.jsonl').read_text().splitlines()[-1])['result']['success'] is False


def test_generation_registry_is_the_frozen_runtime_registry():
    from playground.computation import OPERATIONS
    messages = build_generation_messages(case(), context(), models.PaperMechanismIR.model_json_schema())
    contract = json.loads(messages[0]['content'].split('CONTRACT\n')[1])
    assert contract['ALLOWED_OPERATIONS'] == {
        name: {'arity': list(rule.arity), 'params': list(rule.params)} for name, rule in OPERATIONS.items()}


def test_missing_version_repair_uses_final_schema_then_science(make_client, ir):
    del ir['schema_version']
    client, http = make_client(json.dumps(ir), patch('schema_version', '1.0'))
    result = compile(client)
    assert result.accepted and result.spec.schema_version == '1.0'
    payload = json.loads(http.payloads[1]['messages'][1]['content'])
    assert payload['allowed_paths'] == ['schema_version']
    assert 'schema_version' not in ir


def test_malformed_json_initial_reconstruction_is_scientifically_validated(make_client, ir):
    updates = [{'path': name, 'value': value} for name, value in ir.items()]
    client, http = make_client('bad JSON', json.dumps({'updates': updates}))
    result = compile(client)
    assert result.accepted and result.validation.ok
    assert len(http.payloads) == 2


def test_scientific_validation_wall_time_uses_run_budget(ir, monkeypatch):
    import playground.budget as budget_module
    monkeypatch.setattr(budget_module, 'DEADLINE_SECONDS', 0.03)
    started = time.monotonic()
    report = validation.validate_spec(ir, context().blocks)
    def slow(*args, **kwargs):
        time.sleep(0.3)
        return report
    monkeypatch.setattr(orchestration, 'validate_spec', slow)
    with pytest.raises(budget_module.BudgetExceeded):
        orchestration.assess_candidate(ir, context().blocks, budget=BudgetManager())
    assert time.monotonic() - started < 0.25


def test_repair_deadline_preserves_prior_best(make_client, ir, monkeypatch):
    ir['symbols'] = []
    client, _ = make_client(json.dumps(ir), patch('symbols', [{'symbol': 'x', 'meaning': 'Placeholder', 'kind': 'scalar'}]))
    now = [0.0]
    client.budget = BudgetManager(clock=lambda: now[0])
    original_validate = orchestration.validate_spec
    calls = []
    def validate(*args, **kwargs):
        report = original_validate(*args, **kwargs)
        calls.append(report)
        if len(calls) == 2:
            now[0] = 571.0
        return report
    monkeypatch.setattr(orchestration, 'validate_spec', validate)
    result = compile(client)
    assert not result.accepted
    assert result.spec.symbols == []
    assert result.derived is not None


@pytest.mark.parametrize('failed_artifact', ['validation.json', 'spec.json'])
def test_cli_output_failure_never_reports_success(tmp_path, monkeypatch, ir, failed_artifact):
    import agent
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-integration-key')
    input_path = tmp_path / 'case.json'
    input_path.write_text(json.dumps({**case().model_dump(), 'excerpt': context().blocks[0].text}))
    original_write = agent._write_json
    def fail_write(path, data):
        if path.name == failed_artifact:
            raise OSError('disk full')
        original_write(path, data)
    monkeypatch.setattr(agent, '_write_json', fail_write)
    output = tmp_path / 'out'
    assert agent.run(input_path, output, 'same-model', session=HTTP(json.dumps(ir))) == 1
    final = json.loads((output / 'trace.jsonl').read_text().splitlines()[-1])
    assert final['result']['success'] is False
