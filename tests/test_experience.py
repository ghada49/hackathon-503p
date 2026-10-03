import copy
import json
import unittest
from pathlib import Path

from playground.experience import compile_experience, visual_registry, derive_visual_ids
from playground.renderer import render


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.ir = json.loads(Path('tests/fixtures/generic_ir.json').read_text(encoding='utf-8'))
        self.experience = json.loads(Path('examples/experiences/generic.json').read_text(encoding='utf-8'))

    def test_three_experiences_compile_without_mutating_science(self):
        for name in ('attention', 'entropy', 'generic'):
            ir = json.loads(Path(f'tests/fixtures/{name}_ir.json').read_text(encoding='utf-8'))
            experience = json.loads(Path(f'examples/experiences/{name}.json').read_text(encoding='utf-8'))
            before = copy.deepcopy(ir)
            compiled = compile_experience(ir, experience)
            self.assertEqual(compiled['mode'], 'directed', compiled)
            self.assertEqual(ir, before)

    def test_absent_experience_is_canonical(self):
        self.assertEqual(compile_experience(self.ir)['mode'], 'canonical')

    def test_missing_visual_reference_falls_back(self):
        self.experience['tree']['children'][0]['visual'] = 'missing'
        self.assertEqual(compile_experience(self.ir, self.experience)['mode'], 'canonical')

    def test_html_css_and_executable_fields_are_rejected(self):
        for field in ('html', 'css', 'javascript', 'onClick', 'style'):
            experience = {**self.experience, field: 'alert(1)'}
            self.assertEqual(compile_experience(self.ir, experience)['mode'], 'canonical')

    def test_deep_tree_falls_back(self):
        node = {'type': 'control_group', 'controls': ['prior', 'likelihood_ratio']}
        for _ in range(8):
            node = {'type': 'stack', 'children': [node]}
        self.assertEqual(compile_experience(self.ir, {'tree': node})['mode'], 'canonical')

    def test_all_controls_must_remain_available_exactly_once(self):
        for controls in (['prior'], ['prior', 'prior', 'likelihood_ratio']):
            experience = {'tree': {'type': 'stack', 'children': [
                {'type': 'control_group', 'controls': controls},
                {'type': 'visual', 'visual': 'posterior_distribution'}]}}
            self.assertEqual(compile_experience(self.ir, experience)['mode'], 'canonical')

    def test_directed_layout_cannot_remove_the_meaningful_visual(self):
        experience = {'tree': {'type': 'control_group', 'controls': ['prior', 'likelihood_ratio']}}
        self.assertEqual(compile_experience(self.ir, experience)['mode'], 'canonical')

    def test_invalid_condition_never_breaks_core_packaging(self):
        for bad in (float('nan'), float('inf'), 'posterior < 1', True):
            self.experience['annotations'][0]['when']['threshold'] = bad
            self.ir['experience'] = self.experience
            result = render(self.ir)
            self.assertIn('"mode": "canonical"', result)
            self.assertIn('"mode": "directed"', render(self.ir, experience=self.experience))
            self.assertIn('Bayesian Update with Odds', result)

    def test_shared_experience_uses_final_visual_namespace_and_fields(self):
        self.ir['experience'] = {'story': 'compare_cases', 'layout': 'controls_left',
            'hero_visual': 'visual_2', 'calculation_order': ['posterior'],
            'guided_mode': [{'target': 'what_changed', 'instruction': 'Inspect the changes.'}],
            'annotations': [{'target': 'main_visual', 'kind': 'insight', 'text': 'Inspect belief.'}]}
        self.assertEqual(compile_experience(self.ir)['contract'], 'shared')
        for extra in ({'tree': {}}, {'hero_visual': 'posterior_distribution'},
                      {'guided_mode': [{'target': 'prior', 'instruction': 'Change', 'highlight_dependency_path': True}]}):
            altered = copy.deepcopy(self.ir)
            altered['experience'].update(extra)
            self.assertEqual(compile_experience(altered)['mode'], 'canonical')

    def test_upstream_resolved_none_is_authoritative_and_override_is_explicit(self):
        derived = {'spec': {**self.ir, 'experience': {'layout': 'controls_left'}},
                   'evaluated_defaults': {}, 'visual_ids': derive_visual_ids(self.ir),
                   'resolved_experience': None}
        self.assertIn('"mode": "canonical"', render(derived))
        self.assertIn('"mode": "directed"', render(derived, experience=self.experience))
        derived['resolved_experience'] = {'story': None, 'layout': None, 'hero_visual': None,
            'calculation_order': [], 'emphasis_nodes': [], 'guided_mode': [], 'annotations': []}
        self.assertIn('"contract": "shared"', render(derived))

    def test_visual_ids_reserve_explicit_names_and_reject_collisions(self):
        self.ir['visuals'][1]['id'] = 'visual_0'
        self.assertEqual(derive_visual_ids(self.ir)[:2], ['visual_0_1', 'visual_0'])
        self.ir['visuals'][1]['id'] = 'controls'
        self.ir['experience'] = {'layout': 'controls_left'}
        self.assertEqual(compile_experience(self.ir)['mode'], 'canonical')

    def test_shared_formula_focus_keeps_the_requested_visual_and_supporting_figure(self):
        for layout in ('controls_left', 'comparison'):
            self.ir['experience'] = {'hero_visual': 'visual_0', 'layout': layout}
            compiled = compile_experience(self.ir)
            self.assertEqual(compiled['mode'], 'directed', compiled)
            self.assertEqual(compiled['plan']['primary_visual'], 'visual_0')

    def test_flat_contract_aliases_and_decorative_recovery(self):
        raw = {'story': 'compare_cases', 'layout': 'comparison',
               'hero_visual': 'posterior_distribution', 'calculation_order': ['prior_odds', 'posterior'],
               'emphasis_nodes': ['posterior'],
               'guided_mode': [{'target': 'prior', 'instruction': 'Change the prior', 'highlight_dependency_path': True}],
               'annotations': [{'target': 'missing', 'kind': 'warning', 'text': 'Skip'},
                               {'target': 'posterior', 'kind': 'insight', 'text': 'Observe'}]}
        result = compile_experience(self.ir, raw)
        self.assertEqual(result['mode'], 'directed', result)
        plan = result['plan']
        self.assertEqual(plan['story'], 'compare_two_cases')
        self.assertEqual(plan['primary_visual'], 'posterior_distribution')
        self.assertEqual([s['node'] for s in plan['calculation_story']], ['prior_odds', 'posterior'])
        self.assertEqual(len(plan['annotations']), 1)
        self.assertTrue(plan['guided_mode'][0]['highlight_dependency_path'])
        raw['hero_visual'] = 'missing'
        self.assertEqual(compile_experience(self.ir, raw)['mode'], 'directed')
        raw['layout'] = 'raw-css'
        self.assertEqual(compile_experience(self.ir, raw)['mode'], 'canonical')

    def test_derived_playground_adapter_keeps_science_and_graph(self):
        derived = {'spec': self.ir, 'evaluated_defaults': {'posterior': .5625},
                   'dependency_graph': {'likelihood_ratio': ['posterior']}}
        page = render(derived)
        self.assertIn('"dependencies": {"likelihood_ratio": ["posterior"]}', page)
        self.assertIn('"posterior": 0.5625', page)

    def test_calculation_steps_are_a_trusted_component(self):
        raw = {'story': 'build_step_by_step', 'calculation_order': ['prior_odds', 'posterior_odds', 'posterior'],
               'tree': {'type': 'split', 'children': [
                   {'type': 'control_group', 'controls': ['prior', 'likelihood_ratio']},
                   {'type': 'calculation_steps'}]}}
        self.assertEqual(compile_experience(self.ir, raw)['mode'], 'directed')

    def test_unrelated_frontend_cases_preserve_the_compiler_boundary(self):
        stories = set()
        for name in ('iterative', 'piecewise', 'markov', 'graph', 'recurrence'):
            ir = json.loads(Path(f'tests/fixtures/{name}_ir.json').read_text(encoding='utf-8'))
            raw = json.loads(Path(f'examples/experiences/{name}.json').read_text(encoding='utf-8'))
            original = copy.deepcopy(ir)
            result = compile_experience(ir, raw)
            self.assertEqual(result['mode'], 'directed', result)
            stories.add(result['plan']['story'])
            self.assertEqual(ir, original)
            page = render(ir, experience=raw)
            self.assertNotIn('<script src=', page)
        self.assertGreaterEqual(len(stories), 4)

    def test_plain_text_annotations_are_allowed_and_safely_serialized(self):
        self.experience['annotations'][0]['text'] = '</script><img src=x onerror=alert(1)>'
        result = render(self.ir, experience=self.experience)
        self.assertIn('"mode": "directed"', result)
        self.assertNotIn('</script><img', result)

    def test_registry_references_existing_visuals_without_schema_changes(self):
        self.assertEqual(visual_registry(self.ir)['posterior_distribution']['type'], 'bar_chart')
        self.assertEqual(visual_registry(self.ir)['formula_0']['type'], 'formula')

    def test_generated_layout_strategies_retain_controls_and_visuals(self):
        self.experience.pop('tree')
        self.experience['interactive_stage'] = {'primary_visual': 'posterior_distribution'}
        for layout in ('controls_left', 'controls_right', 'side_by_side', 'stacked',
                       'visual_first', 'equation_first', 'comparison', 'pipeline',
                       'focus', 'dashboard', 'spatial'):
            self.experience['interactive_stage']['layout'] = layout
            self.assertEqual(compile_experience(self.ir, self.experience)['mode'], 'directed', layout)


if __name__ == '__main__':
    unittest.main()
