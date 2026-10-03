"""Submission resilience without model calls or changes to frozen science."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent
from playground.artifact import validate_artifact
from playground.models import SourceBlock
from playground.orchestration import CompilationResult, resolve_candidate
from playground.renderer import render


@pytest.fixture
def spec():
    value = json.loads((Path(__file__).parent / 'fixtures/generic_ir.json').read_text())
    for item in value['evidence'] + value['mechanism_grounding']:
        item['blocks'] = ['b1']
    return value


def resolve(spec):
    return resolve_candidate(spec, [SourceBlock(id='b1', type='paragraph',
        text='Posterior odds equal prior odds times likelihood ratio.', order=0)])


def package(tmp_path, monkeypatch, resolution):
    assessment = resolution.assessment
    result = CompilationResult(assessment.spec, assessment.validation, assessment.derived,
        resolution.accepted, reason=None if resolution.accepted else 'Unmet rubric requirements',
        resolution=resolution.metadata())
    monkeypatch.setattr('playground.orchestration.compile_scientific_spec', lambda *a, **k: result)
    case = tmp_path / 'case.json'
    case.write_text(json.dumps({'source_url': 'paper', 'focus': 'odds', 'audience': 'students',
        'source_blocks': [{'id': 'b1', 'type': 'paragraph', 'text': 'Posterior odds rule.', 'order': 0}]}))
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'index.html').write_text('stale prior artifact')
    code = agent.run(case, output, 'offline/test-model')
    events = [json.loads(line) for line in (output / 'trace.jsonl').read_text().splitlines()]
    return code, output, events


@pytest.mark.parametrize('partial', [False, True])
def test_full_and_safe_partial_packaging_preserve_truthful_status(tmp_path, monkeypatch, spec, partial):
    if partial:
        spec['explorations'] = spec['explorations'][:1]
    resolution = resolve(spec)
    code, output, events = package(tmp_path, monkeypatch, resolution)
    assert code == (1 if partial else 0)
    assert (output / 'index.html').is_file()
    assert 'stale prior artifact' not in (output / 'index.html').read_text(encoding='utf-8')
    assert validate_artifact(output / 'index.html')['self_contained_resources']
    assert json.loads((output / 'resolution.json').read_text()) == resolution.metadata()
    assert resolution.status == ('USABLE_PARTIAL' if partial else 'FULL_SUCCESS')
    assert json.loads((output / 'validation.json').read_text()) == resolution.assessment.validation.model_dump(mode='json')
    assert events[-1]['result']['success'] is (not partial)
    assert any(e['action'] == 'validate_html' and e['result']['success'] for e in events)


@pytest.mark.parametrize('defect', ['test', 'invariant', 'grounding', 'computation', 'explanation'])
def test_unsafe_candidates_leave_no_page(tmp_path, monkeypatch, spec, defect):
    spec['explorations'] = spec['explorations'][:1]
    if defect == 'test':
        spec['tests'][0]['assertions'][0]['expected'] = 100
    elif defect == 'invariant':
        spec['invariants'][0]['assertion'] = {'op': 'less_than', 'expected': 0}
    elif defect == 'grounding':
        spec['mechanism_grounding'][0]['blocks'] = ['missing']
    elif defect == 'computation':
        spec['computation']['nodes'][0]['op'] = 'unknown'
    else:
        spec['symbols'] = []
    resolution = resolve(spec)
    if defect in {'test', 'invariant'}:
        assert resolution.status == 'USABLE_PARTIAL'
        assert not resolution.minima['scientific_checks_pass']
    code, output, events = package(tmp_path, monkeypatch, resolution)
    assert code == 1
    assert not (output / 'index.html').exists()
    assert (output / 'resolution.json').is_file()
    assert events[-1]['result']['success'] is False
    assert not any(e['action'] == 'render_html' for e in events)


@pytest.mark.parametrize('key', ['executable', 'grounded', 'scientific_checks_pass',
                                'meaningful_visual', 'explanation_present'])
@pytest.mark.parametrize('value', [False, None])
def test_partial_gate_requires_every_explicit_safety_minimum(spec, key, value):
    spec['explorations'] = spec['explorations'][:1]
    resolution = resolve(spec)
    metadata = resolution.metadata()
    result = SimpleNamespace(resolution=metadata, derived=resolution.assessment.derived)
    assert agent._safe_renderable_partial(result)
    if value is None:
        metadata['minima'].pop(key)
    else:
        metadata['minima'][key] = value
    assert not agent._safe_renderable_partial(result)


def test_partial_gate_requires_derivation_and_partial_status(spec):
    spec['explorations'] = spec['explorations'][:1]
    resolution = resolve(spec)
    metadata = resolution.metadata()
    assert not agent._safe_renderable_partial(SimpleNamespace(resolution=metadata, derived=None))
    metadata['status'] = 'UNUSABLE'
    assert not agent._safe_renderable_partial(SimpleNamespace(resolution=metadata, derived=resolution.assessment.derived))


@pytest.mark.parametrize('stage', ['render', 'validate'])
def test_partial_packaging_failure_removes_page_and_keeps_diagnostics(tmp_path, monkeypatch, spec, stage):
    spec['explorations'] = spec['explorations'][:1]
    resolution = resolve(spec)

    def fail(*args, **kwargs):
        (tmp_path / 'output/index.html').write_text('incomplete rendering')
        raise ValueError('Injected packaging failure')

    monkeypatch.setattr(agent, 'render_to_file' if stage == 'render' else 'validate_artifact', fail)
    code, output, events = package(tmp_path, monkeypatch, resolution)
    assert code == 1
    assert not (output / 'index.html').exists()
    assert json.loads((output / 'resolution.json').read_text())['status'] == 'USABLE_PARTIAL'
    assert (output / 'validation.json').is_file()
    assert (output / 'derived_playground.json').is_file()
    assert events[-1]['result']['success'] is False
    assert any(e['stage'] == 'artifact' and e['action'] == 'failed' for e in events)


@pytest.mark.parametrize('experience', ['directed', 'invalid', 'absent'])
def test_dependency_recovery_declares_supported_pipeline_and_preserves_ids(spec, experience):
    spec['visuals'] = [{'id': 'mechanism', 'type': 'unsupported', 'value': 'posterior'}]
    spec['computation']['outputs'] = ['posterior']
    if experience != 'absent':
        spec['experience'] = {'hero_visual': 'mechanism' if experience == 'directed' else 'missing',
                              'layout': 'controls_left'}
    original = copy.deepcopy(spec)
    resolution = resolve(spec)
    assert resolution.status == 'FULL_SUCCESS'
    assert resolution.visual_plan['strategy'] == 'dependency'
    visual = resolution.assessment.derived.resolved_visuals[0]
    assert visual['type'] == 'pipeline'
    assert 'dependency_graph' not in visual.get('options', {})
    assert {'prior', 'prior_odds', 'posterior'}.issubset(visual['bindings'])
    assert resolution.assessment.derived.visual_ids == ['mechanism']
    page = render(resolution.assessment.derived)
    assert f'"mode": "{"directed" if experience == "directed" else "canonical"}"' in page
    assert spec == original


@pytest.mark.parametrize('difference', ['target', 'type', 'expected'])
def test_same_setup_different_validated_consequences_are_distinct(spec, difference):
    first = copy.deepcopy(spec['explorations'][0])
    second = copy.deepcopy(first)
    second['title'] = 'Inspect another consequence'
    if difference == 'target':
        second['expectation'] = {'type': 'approx', 'value': 'posterior_complement', 'expected': .7}
    elif difference == 'type':
        second['expectation'] = {'type': 'greater_than', 'value': 'posterior', 'expected': .2}
    else:
        first['expectation'] = {'type': 'greater_than', 'value': 'posterior', 'expected': .2}
        second['expectation'] = {'type': 'greater_than', 'value': 'posterior', 'expected': .25}
    spec['explorations'] = [first, second]
    resolution = resolve(spec)
    assert resolution.assessment.validation.ok
    assert resolution.minima['valid_explorations'] == 2
    assert resolution.quality['distinct_explorations']
    assert resolution.status == 'FULL_SUCCESS'
    assert not resolution.repair_requests


def test_title_or_prose_changes_do_not_disguise_duplicate_explorations(spec):
    second = copy.deepcopy(spec['explorations'][0])
    second.update(title='New title', observe='Reworded observation', why='Reworded explanation')
    second['expectation']['tolerance'] = 1e-8
    spec['explorations'] = [spec['explorations'][0], second]
    resolution = resolve(spec)
    assert resolution.assessment.validation.ok
    assert not resolution.quality['distinct_explorations']
    assert resolution.status == 'USABLE_PARTIAL'
    assert [r['path'] for r in resolution.repair_requests] == ['explorations.1']


def test_invalid_different_expectation_does_not_earn_distinct_exploration_credit(spec):
    second = copy.deepcopy(spec['explorations'][0])
    second['title'] = 'Invalid consequence'
    second['expectation'] = {'type': 'approx', 'value': 'posterior_complement', 'expected': 100}
    spec['explorations'] = [spec['explorations'][0], second]
    resolution = resolve(spec)
    assert resolution.minima['valid_explorations'] == 1
    assert resolution.status == 'USABLE_PARTIAL'


def test_committed_showcase_reproduces_through_mock_agent_pipeline(tmp_path):
    from scripts.generate_showcase import ROOT, generate_showcase
    page = generate_showcase(tmp_path / 'showcase.html', tmp_path / 'pipeline')
    assert page.read_bytes() == (ROOT / 'examples/output/attention/index.html').read_bytes()
    assert page.stat().st_size < 250_000
    assert validate_artifact(page)['self_contained_resources']
    trace = [json.loads(line) for line in (tmp_path / 'pipeline/trace.jsonl').read_text().splitlines()]
    assert trace[-1]['result']['success'] is True
