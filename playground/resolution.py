"""Small, conservative recovery policy over strict Person 2 reports.

Structural quality guards preserve the learning interface; they do not prove
semantic fidelity to a paper. No scientific test/invariant is removed or weakened.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
import re

from playground.models import VisualSpec
from playground.validation import NON_TABLE, VISUAL_TYPES, derive_visual_ids, resolve_experience


@dataclass
class Resolution:
    assessment: object
    status: str
    reports: list
    minima: dict
    quality: dict
    classification: dict
    visual_plan: dict
    actions: list
    repair_requests: list = field(default_factory=list)

    @property
    def accepted(self):
        return self.status == 'FULL_SUCCESS'

    def metadata(self):
        return dict(status=self.status, minima=self.minima, quality=self.quality,
                    classification=self.classification, visual_plan=self.visual_plan, actions=self.actions,
                    strict_reports=[report.model_dump(mode='json') for report in self.reports],
                    repair_requests=self.repair_requests)


def _bad_indices(report, root, checks):
    return {int(f.path.split('.')[1]) for f in report.failures if f.check in checks and f.path
            and re.fullmatch(root + r'\.\d+', f.path)}


def _visual_plan(assessment):
    """Prefer requested valid science views; fallback binds only existing computed data."""
    spec, derived = assessment.spec, assessment.derived
    if spec is None or derived is None:
        return dict(strategy='unavailable', visuals=[])
    values = derived.evaluated_defaults
    valid = [dict(v.model_dump(mode='json'), id=derived.visual_ids[i]) for i, v in enumerate(spec.visuals) if v.type in VISUAL_TYPES
             and (set(v.bindings.values()) | ({v.value} if v.value else set()))
             and not (set(v.bindings.values()) | ({v.value} if v.value else set())) - set(values)]
    if any(v['type'] in NON_TABLE for v in valid):
        return dict(strategy='requested', visuals=valid)
    # Try the requested known target before core outputs, retaining compatible scientific views.
    targets = [(v.value, v.type, derived.visual_ids[i]) for i, v in enumerate(spec.visuals) if v.value in values]
    fallback_id = derived.visual_ids[0] if derived.visual_ids else 'scientific_fallback'
    reserved = {node.id for node in spec.computation.nodes} | {control.id for control in spec.controls}
    while not derived.visual_ids and fallback_id in reserved:
        fallback_id += '_'
    targets += [(name, None, fallback_id) for name in spec.computation.outputs]
    nodes = {node.id: node for node in spec.computation.nodes}
    for name, requested, visual_id in targets:
        value = values.get(name)
        if not isinstance(value, list) or not value:
            continue
        matrix = isinstance(value[0], list)
        kind = nodes[name].kind if name in nodes else None
        compatible = 'heatmap' if matrix else 'line_chart' if kind == 'sequence' else 'bar_chart'
        if requested in ({'heatmap'} if matrix else {'bar_chart', 'line_chart', 'vector'}):
            compatible = requested
        return dict(strategy='best_compatible', visuals=[dict(id=visual_id, type=compatible, value=name, bindings={},
                    title=nodes[name].label or name if name in nodes else name)])
    outputs = [name for name in spec.computation.outputs if name in nodes and name in values]
    if outputs:
        return dict(strategy='dependency', visuals=[dict(id=fallback_id, type='nodes_edges',
                    bindings={name: name for name in outputs}, title='Mechanism relationships',
                    options=dict(dependency_graph=derived.dependency_graph, supporting_values=outputs))])
    return dict(strategy='unavailable', visuals=[])


def _criteria(assessment):
    spec, report, derived = assessment.spec, assessment.validation, assessment.derived
    controls, explorations = set(), set()
    if spec is not None and derived is not None:
        outputs = set(spec.computation.outputs)
        core = outputs | {name for name, downstream in derived.dependency_graph.items() if outputs.intersection(downstream)}
        bad_controls = _bad_indices(report, 'controls', {'control_boundary', 'control_influence', 'control_visible_influence'})
        for i, control in enumerate(spec.controls):
            if i not in bad_controls and any(c['check'] == 'control_influence' and c['passed']
                    and c['details'].get('control') == control.id
                    and core.intersection(c['details'].get('visible_changes', [])) for c in report.checks):
                controls.add(i)
        bad_explorations = _bad_indices(report, 'explorations', {'exploration'})
        for i, exploration in enumerate(spec.explorations):
            if i not in bad_explorations and any(c['check'] == 'exploration' and c['passed']
                    and c['details'].get('title') == exploration.title
                    and core.intersection(c['details'].get('visible_changes', [])) for c in report.checks):
                explorations.add(i)
    grounding = bool(report.rubric_summary.get('scientific', {}).get('source_references_verified')) and not any(
        f.check in {'grounding', 'mechanism_grounding', 'source_blocks'} for f in report.failures)
    checks_ok = not any(f.check in {'test_case', 'invariant'} for f in report.failures)
    plan = _visual_plan(assessment)
    minima = dict(executable=derived is not None, grounded=grounding,
        meaningful_controls=len(controls), valid_explorations=len(explorations), meaningful_visual=bool(plan['visuals']),
        explanation_present=spec is not None and bool(spec.teaching and spec.symbols and spec.limitation),
        autonomous_checks_present=spec is not None and bool(spec.tests and spec.invariants), scientific_checks_pass=checks_ok)
    quality = dict(structural_only=True, core_and_teaching_preserved=True,
        distinct_controls=spec is not None and len({spec.controls[i].label for i in controls}) == len(controls),
        distinct_explorations=spec is not None and len({json.dumps(spec.explorations[i].change.suggested_values, sort_keys=True)
                                                     for i in explorations}) == len(explorations),
        scientific_visual=plan['strategy'] != 'unavailable')
    viable = all(minima[key] for key in ('executable', 'grounded', 'meaningful_visual', 'explanation_present',
                                        'autonomous_checks_present', 'scientific_checks_pass')) and len(controls) >= 2 and len(explorations) >= 2
    coherent = quality['distinct_controls'] and quality['distinct_explorations'] and quality['scientific_visual']
    status = 'FULL_SUCCESS' if report.ok and viable and coherent else 'USABLE_PARTIAL' if derived is not None and grounding else 'UNUSABLE'
    return status, minima, quality, plan, controls, explorations


def resolve_assessment(assessment, source_blocks, *, assess, trace=None, budget=None):
    """One atomic cleanup proposal and at most one fresh strict assessment; no model calls."""
    reports, actions = [assessment.validation], []
    status, minima, quality, plan, controls, explorations = _criteria(assessment)
    report, spec = assessment.validation, assessment.spec
    removable_controls, removable_explorations, removable_grounding = set(), set(), set()
    if spec is not None and assessment.derived is not None and minima['scientific_checks_pass']:
        if len(explorations) >= 2:
            removable_explorations = _bad_indices(report, 'explorations', {'exploration'})
        if len(controls) >= 2:
            bad = _bad_indices(report, 'controls', {'control_influence', 'control_visible_influence'})
            # Scientific inputs/assertions stay untouched, as do valid guided interactions.
            protected = {key for test in spec.tests for key in test.inputs}
            protected.update(a.value for test in spec.tests for a in test.assertions if a.value)
            protected.update(inv.value for inv in spec.invariants)
            protected.update(inv.assertion.value for inv in spec.invariants if inv.assertion.value)
            protected.update(key for i, e in enumerate(spec.explorations) if i not in removable_explorations
                             for key in e.change.suggested_values)
            protected.update(e.expectation.value for i, e in enumerate(spec.explorations)
                             if i not in removable_explorations and e.expectation)
            removable_controls = {i for i in bad if not assessment.derived.dependency_graph.get(spec.controls[i].id)
                                  and spec.controls[i].id not in protected}
        bad_grounding = _bad_indices(report, 'mechanism_grounding', {'mechanism_grounding'})
        covered = {node for i, g in enumerate(spec.mechanism_grounding) if i not in bad_grounding for node in g.nodes}
        node_ids = {node.id for node in spec.computation.nodes}
        removable_grounding = {i for i in bad_grounding if (set(spec.mechanism_grounding[i].nodes) & node_ids) <= covered}
    degradable = {'controls': removable_controls, 'explorations': removable_explorations,
                  'mechanism_grounding': removable_grounding, 'evidence': set()}
    if spec is not None and minima['scientific_checks_pass']:
        for root, indices in degradable.items():
            seen, duplicates = set(), set()
            for i, item in enumerate(getattr(spec, root)):
                key = item.model_dump_json()
                if key in seen:
                    duplicates.add(i)
                seen.add(key)
            useful = controls if root == 'controls' else explorations if root == 'explorations' else None
            identical_control_cleanup = root == 'controls' and any(f.check == 'unique_controls' for f in report.failures)
            if useful is None or len(useful - duplicates - indices) >= 2 or identical_control_cleanup:
                indices.update(duplicates)
    def can_degrade(failure):
        return any(failure.path == root + '.' + str(i) for root, indices in degradable.items() for i in indices)
    classification = dict(blocking=[f.model_dump(mode='json') for f in report.failures if not can_degrade(f)],
                          degradable=[f.model_dump(mode='json') for f in report.failures if can_degrade(f)],
                          warning=[w.model_dump(mode='json') for w in report.warnings])
    if any(degradable.values()):
        candidate = spec.model_dump(mode='json')
        removed_ids = {spec.controls[i].id for i in removable_controls} - {
            control.id for i, control in enumerate(spec.controls) if i not in removable_controls}
        for root, indices in degradable.items():
            candidate[root] = [item for i, item in enumerate(candidate[root]) if i not in indices]
            actions.extend(root + '.' + str(i) for i in sorted(indices))
        if removed_ids and candidate.get('experience'):
            for field in ('guided_mode', 'annotations'):
                candidate['experience'][field] = [item for item in candidate['experience'].get(field, []) if item['target'] not in removed_ids]
        fresh = assess(copy.deepcopy(candidate), source_blocks, trace=trace, budget=budget)
        reports.append(fresh.validation)
        trial_status, trial_minima, trial_quality, trial_plan, _, _ = _criteria(fresh)
        # Cleanup may not weaken checks, source grounding, or the useful learning interface.
        if trial_minima['grounded'] and trial_minima['scientific_checks_pass'] and trial_quality['distinct_controls'] and trial_quality['distinct_explorations']:
            assessment, status, minima, quality, plan = fresh, trial_status, trial_minima, trial_quality, trial_plan
        else:
            actions = []
    if assessment.derived is not None:
        assessment = copy.deepcopy(assessment)
        assessment.derived.resolved_visuals = copy.deepcopy(plan['visuals'])
        presentation = assessment.spec.model_copy(deep=True, update={'visuals': [VisualSpec.model_validate(v) for v in plan['visuals']]})
        assessment.derived.visual_ids = derive_visual_ids(presentation)
        assessment.derived.resolved_experience, issues = resolve_experience(presentation)
        plan['experience_issues'] = issues
    # These are rubric/quality requests, kept separate from Person 2's strict defects.
    requests = []
    if assessment.spec is not None and assessment.validation.ok and status != 'FULL_SUCCESS':
        paths = set()
        for root, key in [('controls', 'distinct_controls'), ('explorations', 'distinct_explorations')]:
            if not quality[key]:
                seen = set()
                for i, item in enumerate(getattr(assessment.spec, root)):
                    identity = item.label if root == 'controls' else json.dumps(item.change.suggested_values, sort_keys=True)
                    if identity in seen:
                        paths.add(f'{root}.{i}.label' if root == 'controls' else f'{root}.{i}')
                    seen.add(identity)
        paths.update(root for root in ('tests', 'invariants') if not getattr(assessment.spec, root))
        for path in sorted(paths):
            requests.append(dict(check='rubric_quality', severity='serious', path=path,
                message='Restore distinct meaningful guided learning and required autonomous checks; preserve the focused mechanism.',
                repairable=True, allowed_paths=[path]))
    result = Resolution(assessment, status, reports, minima, quality, classification, plan, actions, requests)
    if trace:
        trace.log('resolution', 'rubric_resolution', result.metadata())
    return result
