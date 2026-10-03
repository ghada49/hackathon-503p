"""Rubric recovery uses frozen detectors and never discards failed science checks."""
import copy
import json
from pathlib import Path

import pytest

from playground import orchestration, validation
from playground.source import SourceBlock


@pytest.fixture
def ir():
    return json.loads((Path(__file__).parent / 'fixtures/generic_ir.json').read_text())


def blocks(ir):
    ids = {b for e in ir['evidence'] for b in e['blocks']}
    ids.update(b for g in ir['mechanism_grounding'] for b in g['blocks'])
    return [SourceBlock(id=b, type='equation', text='Posterior odds = prior odds times likelihood ratio.', order=i)
            for i, b in enumerate(sorted(ids))]


def resolve(ir, **kwargs):
    return orchestration.resolve_candidate(ir, blocks(ir), **kwargs)


def dead_control():
    return dict(id='extra', type='slider', label='Unused extra', value_kind='scalar', default=1, min=0, max=2)


def bad_exploration(ir, title='Extra broken exploration'):
    e = copy.deepcopy(ir['explorations'][0])
    e['title'] = title
    e['expectation']['expected'] = 100
    return e


def test_three_controls_one_dead_reaches_full_success_without_mutating_original(ir):
    ir['controls'].append(dead_control())
    original = copy.deepcopy(ir)
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert result.assessment.validation.ok
    assert len(result.assessment.spec.controls) == 2
    assert len(result.reports) == 2
    assert any(f.check == 'control_influence' for f in result.reports[0].failures)
    assert ir == original


def test_two_controls_one_dead_cannot_pass_minima(ir):
    ir['controls'][1]['min'] = ir['controls'][1]['max'] = ir['controls'][1]['default']
    result = resolve(ir)
    assert result.status == 'USABLE_PARTIAL'
    assert not result.assessment.validation.ok
    assert result.minima['meaningful_controls'] == 1
    assert len(result.assessment.spec.controls) == 2


def test_three_explorations_one_bad_can_retain_two_valid(ir):
    ir['explorations'].append(bad_exploration(ir))
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert len(result.assessment.spec.explorations) == 2
    assert result.minima['valid_explorations'] == 2


def test_three_explorations_two_bad_still_fails_requirement(ir):
    ir['explorations'][1]['expectation'] = {'type': 'approx', 'value': 'posterior', 'expected': 100}
    ir['explorations'].append(bad_exploration(ir))
    result = resolve(ir)
    assert result.status == 'USABLE_PARTIAL'
    assert result.minima['valid_explorations'] == 1


@pytest.mark.parametrize('experience', [{'layout': 'not-allowed'}, {'calculation_order': ['missing']}])
def test_invalid_experience_uses_canonical_fallback_without_mutating_science(ir, experience):
    ir['experience'] = experience
    before = copy.deepcopy(ir)
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert result.assessment.derived.resolved_experience is None
    assert any(w.check == 'experience_fallback' for w in result.reports[0].warnings)
    assert ir == before


def test_bad_visual_binding_uses_best_compatible_scientific_fallback(ir):
    ir['visuals'] = [dict(type='bar_chart', value='posterior_distribution', bindings={'values': 'missing'})]
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert result.visual_plan['strategy'] == 'best_compatible'
    assert result.assessment.derived.resolved_visuals[0]['type'] == 'bar_chart'
    assert result.assessment.derived.resolved_visuals[0]['value'] == 'posterior_distribution'
    assert any(w.check == 'visual_bindings' for w in result.assessment.validation.warnings)


def test_scientific_fallback_preserves_visual_identity_and_experience_targets(ir):
    ir['visuals'] = [dict(id='posterior_view', type='bar_chart', value='posterior_distribution', bindings={'values': 'missing'})]
    ir['experience'] = {'hero_visual': 'posterior_view', 'annotations': [
        {'target': 'posterior_view', 'kind': 'hint', 'text': 'Compare prior and posterior'}]}
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    derived = result.assessment.derived
    assert derived.resolved_visuals[0]['id'] == 'posterior_view'
    assert derived.visual_ids == ['posterior_view']
    assert derived.resolved_experience.hero_visual == 'posterior_view'


def test_removed_optional_visual_target_uses_canonical_experience_fallback(ir):
    ir['visuals'] = [dict(id='good', type='bar_chart', value='posterior_distribution'),
                     dict(id='bad', type='number', value='missing')]
    ir['experience'] = {'hero_visual': 'bad'}
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert result.assessment.derived.resolved_experience is None
    assert result.assessment.derived.visual_ids == ['good']


def test_requested_valid_visual_has_priority_over_generic_fallback(ir):
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert result.visual_plan['strategy'] == 'requested'
    assert any(v['type'] == 'bar_chart' for v in result.assessment.derived.resolved_visuals)


def test_redundant_bad_grounding_can_be_removed_with_coverage_retained(ir):
    ir['mechanism_grounding'].append(dict(nodes=['posterior', 'missing'], blocks=['b_bayes_odds'], relationship='Redundant'))
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert len(result.assessment.spec.mechanism_grounding) == 1


def test_nonredundant_bad_grounding_is_not_deleted(ir):
    ir['mechanism_grounding'][0]['blocks'] = ['missing']
    # Supply only the original real source ID, never fabricate a replacement.
    result = orchestration.resolve_candidate(ir, [SourceBlock(id='b_bayes_odds', type='paragraph', text='Rule', order=0)])
    assert result.status == 'UNUSABLE'
    assert len(result.assessment.spec.mechanism_grounding) == 1
    assert any(f.check == 'mechanism_grounding' for f in result.assessment.validation.failures)


def test_cleanup_revalidates_and_derives_using_fresh_matching_report(ir, monkeypatch):
    ir['controls'].append(dead_control())
    reports, reused = [], []
    strict = orchestration.validate_spec
    derive = orchestration.derive_playground
    def validate(*args, **kwargs):
        report = strict(*args, **kwargs)
        reports.append(report)
        return report
    def checked_derive(*args, **kwargs):
        reused.append(kwargs['validation'])
        return derive(*args, **kwargs)
    monkeypatch.setattr(orchestration, 'validate_spec', validate)
    monkeypatch.setattr(orchestration, 'derive_playground', checked_derive)
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert len(reports) == 2 and reports[0] is not reports[1]
    assert reused == reports


@pytest.mark.parametrize('root', ['tests', 'invariants'])
def test_failed_scientific_check_never_deleted_during_cleanup(ir, root):
    ir['controls'].append(dead_control())
    if root == 'tests':
        ir[root][0]['assertions'][0]['expected'] = 100
    else:
        ir[root][0]['assertion'] = {'op': 'monotonic'}  # Scalar target is not a sequence.
    before = copy.deepcopy(ir)
    result = resolve(ir)
    assert result.status != 'FULL_SUCCESS'
    assert any(f.check == ('test_case' if root == 'tests' else 'invariant') for f in result.assessment.validation.failures)
    assert result.assessment.spec.model_dump(mode='json')[root] == orchestration.PaperMechanismIR.model_validate(ir).model_dump(mode='json')[root]
    assert ir == before


def test_non_executable_mechanism_is_unusable(ir):
    ir['computation']['nodes'][0]['op'] = 'ref'
    result = resolve(ir)
    assert result.status == 'UNUSABLE'
    assert result.assessment.derived is None


def test_dead_control_referenced_by_scientific_test_not_pruned(ir):
    ir['controls'].append(dead_control())
    ir['tests'][0]['inputs']['extra'] = 1
    result = resolve(ir)
    assert result.status != 'FULL_SUCCESS'
    assert len(result.assessment.spec.controls) == 3


def test_cleanup_removes_only_dependent_optional_presentation_steps(ir):
    ir['controls'].append(dead_control())
    ir['experience'] = {'guided_mode': [{'target': 'extra', 'instruction': 'Optional'},
                                      {'target': 'posterior', 'instruction': 'Read the result'}]}
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert [x.target for x in result.assessment.spec.experience.guided_mode] == ['posterior']


def test_minimum_counts_do_not_override_redundant_guided_learning(ir):
    ir['explorations'][1] = copy.deepcopy(ir['explorations'][0])
    ir['explorations'][1]['title'] = 'Same interaction again'
    result = resolve(ir)
    assert result.assessment.validation.ok
    assert result.status == 'USABLE_PARTIAL'
    assert not result.quality['distinct_explorations']


def test_warning_only_helper_grounding_is_retained(ir):
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert any(w.check == 'grounding_coverage' for w in result.assessment.validation.warnings)
    assert result.classification['warning']


@pytest.mark.parametrize('root', ['controls', 'explorations', 'mechanism_grounding', 'evidence'])
def test_exact_duplicate_optional_record_can_be_deduplicated(ir, root):
    ir[root].append(copy.deepcopy(ir[root][0]))
    before = copy.deepcopy(ir)
    result = resolve(ir)
    assert result.status == 'FULL_SUCCESS'
    assert len(getattr(result.assessment.spec, root)) == len(ir[root]) - 1
    assert ir == before
