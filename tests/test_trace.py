import json
from playground.trace import TraceLogger


def test_jsonl_time_and_recursive_secret_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'example-secret-key')
    path = tmp_path / 'trace.jsonl'
    trace = TraceLogger(path)
    trace.log('generation', 'attempt', {'Authorization': 'Bearer example-secret-key', 'nested': {'api_key': 'other', 'reasoning': 'hidden'}, 'message': 'bad example-secret-key', 'completion_tokens': 9})
    trace.close()
    text = path.read_text()
    row = json.loads(text)
    assert row['t'] >= 0
    assert row['result']['completion_tokens'] == 9
    assert 'example-secret-key' not in text
    assert 'Bearer' not in text
    assert 'hidden' not in text
    assert 'other' not in text
