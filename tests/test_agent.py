import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from agent import main, run
from playground.generator import GenerationFailure


class FakeIR(BaseModel):
    schema_version: str
    teaching: dict


class HTTP:
    def __init__(self, contents):
        self.contents = iter(contents)
        self.models = []

    def post(self, url, **kwargs):
        self.models.append(kwargs['json']['model'])
        content = next(self.contents)
        return SimpleNamespace(status_code=200, headers={}, json=lambda: dict(id='req', choices=[dict(message=dict(content=content))], usage=dict(prompt_tokens=2, completion_tokens=4, total_tokens=6)))


def input_case(tmp_path):
    path = tmp_path / 'case.json'
    path.write_text(json.dumps(dict(source_url='paper', focus='rule', audience='students', excerpt='The scientific rule.')), encoding='utf-8')
    return path


def test_run_generates_validated_spec_and_final_trace(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    output = tmp_path / 'out'
    http = HTTP(['{"schema_version":"1.0","teaching":{"title":"Rule"}}'])
    assert run(input_case(tmp_path), output, 'exact/model', session=http, ir_model=FakeIR) == 0
    assert json.loads((output / 'spec.json').read_text())['teaching']['title'] == 'Rule'
    rows = [json.loads(line) for line in (output / 'trace.jsonl').read_text().splitlines()]
    assert rows[-1]['result']['success'] is True
    assert rows[-1]['result']['semantic_calls'] == 1
    assert http.models == ['exact/model']


def test_schema_failure_gets_one_targeted_repair(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    http = HTTP(['{"schema_version":"1.0"}', '{"updates":[{"path":"teaching","value":{"title":"Rule"}}]}'])
    output = tmp_path / 'out'
    assert run(input_case(tmp_path), output, 'exact/model', session=http, ir_model=FakeIR) == 0
    final = json.loads((output / 'trace.jsonl').read_text().splitlines()[-1])['result']
    assert (final['semantic_calls'], final['repairs'], final['http_requests']) == (2, 1, 2)
    assert http.models == ['exact/model', 'exact/model']


def test_invalid_json_repair_can_supply_initial_ir(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    http = HTTP(['bad JSON', '{"updates":[{"path":"schema_version","value":"1.0"},{"path":"teaching","value":{"title":"Rule"}}]}'])
    assert run(input_case(tmp_path), tmp_path / 'out', 'model', session=http, ir_model=FakeIR) == 0


def test_bad_input_still_flushes_trace_and_removes_stale_spec(tmp_path):
    output = tmp_path / 'out'
    output.mkdir()
    (output / 'spec.json').write_text('{}')
    path = tmp_path / 'bad.json'
    path.write_text('{}')
    assert run(path, output, 'model') != 0
    assert not (output / 'spec.json').exists()
    final = json.loads((output / 'trace.jsonl').read_text().splitlines()[-1])
    assert final['result']['success'] is False


def test_missing_shared_model_fails_before_paid_request(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    # The import seam is the absent Person 2 boundary; no replacement models.py is created.
    def missing():
        from playground.generator import IntegrationUnavailable
        raise IntegrationUnavailable('Missing shared IR')
    monkeypatch.setattr('agent.shared_ir_model', missing)
    output = tmp_path / 'out'
    assert run(input_case(tmp_path), output, 'model', session=HTTP([])) != 0
    final = json.loads((output / 'trace.jsonl').read_text().splitlines()[-1])['result']
    assert final['http_requests'] == 0
    assert final['semantic_calls'] == 0


@pytest.mark.parametrize('args', [[], ['--input', 'case.json'], ['--input', 'case.json', '--output', 'out']])
def test_cli_requires_all_flags(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code != 0


def test_missing_key_safe_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    assert run(input_case(tmp_path), tmp_path / 'out', 'model', session=HTTP([]), ir_model=FakeIR) != 0
    assert 'OPENROUTER_API_KEY' in capsys.readouterr().err


def test_source_document_export_preserves_raw_and_structural_map(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    output = tmp_path / 'out'
    assert run(input_case(tmp_path), output, 'model', session=HTTP(['{"schema_version":"1.0","teaching":{}}']), ir_model=FakeIR) == 0
    doc = json.loads((output / 'source_document.json').read_text())
    assert doc['raw_source'] == 'The scientific rule.'
    assert doc['raw_text'] == 'The scientific rule.'
    assert doc['structural_map']['block_order'] == ['b0000']
    rows = [json.loads(line) for line in (output / 'trace.jsonl').read_text().splitlines()]
    selected = next(row for row in rows if row['action'] == 'select_source_context')
    assert selected['result']['mode'] == 'full'


def test_too_small_prompt_budget_fails_without_http(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    output = tmp_path / 'out'
    assert run(input_case(tmp_path), output, 'model', session=HTTP([]), ir_model=FakeIR, context_max_chars=100) != 0
    final = json.loads((output / 'trace.jsonl').read_text().splitlines()[-1])['result']
    assert final['semantic_calls'] == 0
    assert final['http_requests'] == 0


def test_invalid_case_does_not_log_credentials_from_extra_fields(tmp_path, capsys):
    path = tmp_path / 'bad-case.json'
    path.write_text(json.dumps(dict(focus='science', audience='students', password='private-credential')), encoding='utf-8')
    output = tmp_path / 'out'
    assert run(path, output, 'model') != 0
    assert 'private-credential' not in (output / 'trace.jsonl').read_text()
    assert 'private-credential' not in capsys.readouterr().err
