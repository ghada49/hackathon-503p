import copy
import json
import sys
from types import SimpleNamespace
import pytest

from playground.generator import GenerationFailure, apply_restricted_patch, normalize_repair_path, validate_ir
from agent import run


def test_authoritative_snapshot_schema_matches_model(authoritative_model, authoritative_schema, authoritative_candidate):
    assert authoritative_model.model_json_schema() == authoritative_schema
    assert validate_ir(authoritative_candidate, authoritative_model).schema_version == '1.0'


@pytest.mark.parametrize('operand,path,value', [
    ({'ref': 123}, 'computation.nodes.0.inputs.0.ref', 'prior'),
    ({'const': None}, 'computation.nodes.0.inputs.0.const', 1),
    ({'op': 'add', 'inputs': [{'ref': 123}]}, 'computation.nodes.0.inputs.0.inputs.0.ref', 'prior'),
    ({'ref': 'prior', 'const': 1}, 'computation.nodes.0.inputs.0', {'ref': 'prior'}),
    ({}, 'computation.nodes.0.inputs.0', {'ref': 'prior'}),
    ({'op': '', 'inputs': []}, 'computation.nodes.0.inputs.0.op', 'add'),
    ({'op': 'add'}, 'computation.nodes.0.inputs.0.inputs', [{'const': 1}]),
])
def test_real_union_paths_repair_exact_leaf(authoritative_model, authoritative_candidate, operand, path, value):
    candidate = authoritative_candidate
    candidate['computation']['nodes'][0]['inputs'][0] = operand
    before = copy.deepcopy(candidate)
    with pytest.raises(GenerationFailure) as error:
        validate_ir(candidate, authoritative_model)
    failure = error.value
    assert failure.allowed_paths == [path]
    assert [f['path'] for f in failure.failures] == [path]
    patch = {'updates': [{'path': path, 'value': value}]}
    repaired = apply_restricted_patch(candidate, patch, failure.allowed_paths)
    validate_ir(repaired, authoritative_model)
    assert candidate == before


def test_initial_missing_version_authorized_but_never_injected(authoritative_model, authoritative_candidate):
    candidate = authoritative_candidate
    del candidate['schema_version']
    with pytest.raises(GenerationFailure) as error:
        validate_ir(candidate, authoritative_model)
    assert error.value.allowed_paths == ['schema_version']
    assert 'schema_version' not in candidate
    repaired = apply_restricted_patch(candidate, {'updates': [{'path': 'schema_version', 'value': '1.0'}]},
        error.value.allowed_paths, allow_initial_missing_version=True, ir_model=authoritative_model)
    assert validate_ir(repaired, authoritative_model).schema_version == '1.0'
    assert 'schema_version' not in candidate


def test_existing_wrong_version_is_not_implicitly_authorized(authoritative_model, authoritative_candidate):
    authoritative_candidate['schema_version'] = 'wrong'
    with pytest.raises(GenerationFailure) as error:
        validate_ir(authoritative_candidate, authoritative_model)
    assert error.value.allowed_paths == []
    assert not error.value.failures[0]['repairable']


@pytest.mark.parametrize('version', ['1.0', 'wrong'])
def test_initial_version_permission_cannot_overwrite_existing(authoritative_model, authoritative_candidate, version):
    authoritative_candidate['schema_version'] = version
    with pytest.raises(GenerationFailure):
        apply_restricted_patch(authoritative_candidate, {'updates': [{'path': 'schema_version', 'value': '1.0'}]},
            ['schema_version'], allow_initial_missing_version=True, ir_model=authoritative_model)


@pytest.mark.parametrize('path', ['computation.nodes.-1', 'computation.nodes.01', 'computation..nodes', 'computation.nodes[0]', '__class__', 'computation.nodes.0.inputs.0.Ref.ref'])
def test_malformed_or_synthetic_patch_paths_rejected(authoritative_candidate, path):
    with pytest.raises(GenerationFailure):
        apply_restricted_patch(authoritative_candidate, {'updates': [{'path': path, 'value': 'bad'}]},
            ['computation.nodes.0.inputs.0.ref'])


@pytest.mark.parametrize('location,expected', [
    (('computation', 'nodes', 0, 'inputs', 0, 'Ref', 'ref'), 'computation.nodes.0.inputs.0.ref'),
    (('computation', 'nodes', 0, 'inputs', 0, 'Const', 'const'), 'computation.nodes.0.inputs.0.const'),
    (('computation', 'nodes', 0, 'inputs', 1, 'Op', 'inputs', 1, 'Ref', 'ref'), 'computation.nodes.0.inputs.1.inputs.1.ref'),
])
def test_named_union_labels_normalize_against_authoritative_schema(authoritative_candidate, authoritative_schema, location, expected):
    assert normalize_repair_path(authoritative_candidate, location, authoritative_schema) == expected


def test_authoritative_missing_ref_field_is_legitimate_leaf(authoritative_model):
    reference = sys.modules[authoritative_model.__module__].Reference
    with pytest.raises(GenerationFailure) as error:
        validate_ir({}, reference)
    assert error.value.allowed_paths == ['ref']


@pytest.mark.parametrize('extra_key', ['unexpected', 'bad-key'])
def test_extra_operand_member_authorizes_replaceable_container(authoritative_model, authoritative_candidate, extra_key):
    authoritative_candidate['computation']['nodes'][0]['inputs'][0] = {'ref': 'prior', extra_key: True}
    with pytest.raises(GenerationFailure) as error:
        validate_ir(authoritative_candidate, authoritative_model)
    path = 'computation.nodes.0.inputs.0'
    assert error.value.allowed_paths == [path]
    repaired = apply_restricted_patch(authoritative_candidate,
        {'updates': [{'path': path, 'value': {'ref': 'prior'}}]}, error.value.allowed_paths)
    validate_ir(repaired, authoritative_model)


class OfflineHTTP:
    def __init__(self, contents):
        self.contents = iter(contents)
        self.payloads = []

    def post(self, url, **kwargs):
        self.payloads.append(copy.deepcopy(kwargs['json']))
        content = next(self.contents)
        return SimpleNamespace(status_code=200, headers={}, json=lambda: dict(choices=[dict(message=dict(content=content))],
            usage=dict(prompt_tokens=2, completion_tokens=4, total_tokens=6)))


def case_file(tmp_path):
    path = tmp_path / 'case.json'
    path.write_text(json.dumps(dict(source_url='paper', focus='odds update', audience='students',
        excerpt='Posterior odds equal prior odds multiplied by the likelihood ratio.')), encoding='utf-8')
    return path


def test_cli_initial_missing_version_real_model_offline(tmp_path, monkeypatch, authoritative_model, authoritative_candidate):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-fixture-key')
    del authoritative_candidate['schema_version']
    before = copy.deepcopy(authoritative_candidate)
    http = OfflineHTTP([json.dumps(authoritative_candidate), '{"updates":[{"path":"schema_version","value":"1.0"}]}'])
    assert run(case_file(tmp_path), tmp_path / 'out', 'same-model', session=http, ir_model=authoritative_model) == 0
    assert json.loads((tmp_path / 'out' / 'spec.json').read_text())['schema_version'] == '1.0'
    assert len(http.payloads) == 2
    assert authoritative_candidate == before
    payload = json.loads(http.payloads[1]['messages'][1]['content'])
    assert payload['allowed_paths'] == ['schema_version']
    assert 'SOURCE_BLOCKS' not in payload


def test_cli_repair_budget_denial_real_model_no_second_request(tmp_path, monkeypatch, authoritative_model, authoritative_candidate):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'offline-fixture-key')
    authoritative_candidate['controls'][0]['default'] = {'unsupported': 'x' * 30000}
    http = OfflineHTTP([json.dumps(authoritative_candidate)])
    assert run(case_file(tmp_path), tmp_path / 'out', 'same-model', session=http, ir_model=authoritative_model) == 1
    assert len(http.payloads) == 1
    trace = [json.loads(row) for row in (tmp_path / 'out' / 'trace.jsonl').read_text().splitlines()]
    assert any(row['action'] == 'repair_skipped' for row in trace)
    assert trace[-1]['result']['semantic_calls'] == 1
