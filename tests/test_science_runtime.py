"""Independent known answers, failure injection, and Python/browser-engine parity."""
from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
import unittest

import numpy as np
from pydantic import ValidationError

from playground.computation import (OPERATIONS, ComputationError, derive_dependencies,
                                    evaluate, evaluate_expression, infer_types_shapes, validate_types_shapes)
from playground.models import PaperMechanismIR, SourceBlock, Case
from playground.validation import derive_playground, validate_spec

ROOT = Path(__file__).resolve().parents[1]


def const(value):
    return {'const': value}


def expr(op, *args, params=None):
    return {'op': op, 'inputs': [x if isinstance(x, dict) else const(x) for x in args], 'params': params or {}}


def fixture(name='generic'):
    return json.loads((ROOT / 'tests' / 'fixtures' / f'{name}_ir.json').read_text(encoding='utf-8'))


def source_for(spec):
    """Synthetic source metadata for structural tests, not paper fidelity evidence."""
    ids = {b for item in spec['evidence'] + spec['mechanism_grounding'] for b in item['blocks']}
    return [SourceBlock(id=b, type='paragraph', text='Synthetic structural-test evidence', order=i) for i, b in enumerate(sorted(ids))]


def js(tasks):
    result = subprocess.run(['node', str(ROOT / 'tests' / 'js_conformance.cjs')],
                            input=json.dumps(tasks), text=True, capture_output=True, cwd=ROOT, timeout=30, check=True)
    return json.loads(result.stdout)


# Known answers are authored independently of either interpreter.
NORMAL_CASES = [
    ('add', expr('add', [1, 2], 3), [4, 5]),
    ('subtract', expr('subtract', 5, 2), 3),
    ('multiply', expr('multiply', [[1, 2], [3, 4]], 2), [[2, 4], [6, 8]]),
    ('divide', expr('divide', [4, 6], 2), [2, 3]),
    ('pow', expr('pow', [2, 3], 2), [4, 9]),
    ('negate', expr('negate', [2, -3]), [-2, 3]),
    ('sqrt', expr('sqrt', [0, 4]), [0, 2]),
    ('exp', expr('exp', 0), 1),
    ('log', expr('log', math.e), 1),
    ('log2', expr('log2', [1, 4]), [0, 2]),
    ('abs', expr('abs', [-1, 2]), [1, 2]),
    ('sin', expr('sin', 0), 0),
    ('cos', expr('cos', 0), 1),
    ('clip', expr('clip', [-2, 0, 2], -1, 1), [-1, 0, 1]),
    ('sum', expr('sum', [[1, 2], [3, 4]], params={'axis': 0}), [4, 6]),
    ('product', expr('product', [2, 3, 4]), 24),
    ('mean', expr('mean', [2, 4]), 3),
    ('min', expr('min', [3, 1, 2]), 1),
    ('max', expr('max', [3, 1, 2]), 3),
    ('argmin', expr('argmin', [3, 1, 2]), 1),
    ('argmax', expr('argmax', [3, 1, 2]), 0),
    ('dot', expr('dot', [1, 2], [3, 4]), 11),
    ('matmul', expr('matmul', [[1, 2]], [[3], [4]]), [[11]]),
    ('transpose', expr('transpose', [[1, 2, 3], [4, 5, 6]]), [[1, 4], [2, 5], [3, 6]]),
    ('index', expr('index', [1, 2, 3], -1), 3),
    ('slice', expr('slice', [1, 2, 3, 4], params={'start': 1, 'stop': 4, 'step': 2}), [2, 4]),
    ('reshape', expr('reshape', [1, 2, 3, 4], params={'shape': [2, 2]}), [[1, 2], [3, 4]]),
    ('flatten', expr('flatten', [[1, 2], [3, 4]]), [1, 2, 3, 4]),
    ('concat', expr('concat', [[1], [2]], [[3], [4]], params={'axis': 1}), [[1, 3], [2, 4]]),
    ('softmax', expr('softmax', [1000, 1000]), [.5, .5]),
    ('softmax_rows', expr('softmax_rows', [[1000, 1000], [-1000, -1000]]), [[.5, .5], [.5, .5]]),
    ('normalize', expr('normalize', [2, 6]), [.25, .75]),
    ('range', expr('range', 5, 0, -2), [5, 3, 1]),
    ('cumsum', expr('cumsum', [1, 2, 3]), [1, 3, 6]),
    ('difference', expr('difference', [1, 3, 6]), [2, 3]),
    ('equal', expr('equal', [1, 2], 1), [True, False]),
    ('not_equal', expr('not_equal', 'a', 'b'), True),
    ('less', expr('less', [1, 2], 2), [True, False]),
    ('less_equal', expr('less_equal', [1, 2], 2), [True, True]),
    ('greater', expr('greater', 3, 2), True),
    ('greater_equal', expr('greater_equal', 2, 2), True),
    ('and', expr('and', [True, False], True), [True, False]),
    ('or', expr('or', [True, False], True), [True, True]),
    ('not', expr('not', [True, False]), [False, True]),
    ('where', expr('where', expr('equal', [0, .5, .5], 0), 0,
                   expr('negate', expr('multiply', [0, .5, .5], expr('log2', [0, .5, .5])))), [0, .5, .5]),
    ('map', expr('map', [1, 2, 3], params={'body': expr('multiply', {'ref': 'item'}, 2)}), [2, 4, 6]),
    ('elementwise', expr('elementwise', [[1, 2], [3, 4]], params={'body': expr('pow', {'ref': 'item'}, 2)}), [[1, 4], [9, 16]]),
    ('iterate', expr('iterate', 8, 3, params={'body': expr('multiply', {'ref': 'state'}, .5)}), 1),
    ('scan', expr('scan', 0, [1, 2, 3], params={'body': expr('add', {'ref': 'state'}, {'ref': 'item'})}), [1, 3, 6]),
]

EXTRA_CASES = [
    expr('where', True, 7, expr('divide', 1, 0)),
    expr('where', [False, True], expr('divide', 1, [0, 2]), 0),
    expr('where', [False, True], expr('sqrt', [-1, 4]), 0),
    expr('slice', [1, 2, 3], params={'step': -1}),
    expr('slice', [1, 2, 3], params={'start': -2, 'stop': -1}),
    expr('softmax', [[1, 2], [3, 4]], params={'axis': 0}),
    expr('softmax', [[1, 2], [3, 4]]),
    expr('normalize', [[1, 3], [2, 2]], params={'axis': -1}),
    expr('cumsum', [[1, 2], [3, 4]], params={'axis': 0}),
    expr('difference', [[1, 2], [3, 4]], params={'axis': 1}),
    expr('sum', [[1, 2], [3, 4]], params={'axis': -1}),
    expr('concat', 1, 2, params={'axis': 0, 'promote_scalars': True}),
    expr('map', [1, 2], params={'body': expr('add', {'ref': 'item'}, {'ref': 'index'})}),
    expr('iterate', [1, 0], 2, params={'body': expr('multiply', {'ref': 'state'}, .5)}),
    expr('iterate', 1, 100, params={'body': expr('add', {'ref': 'state'}, 1)}),
    expr('iterate', 7, 0, params={'body': expr('add', {'ref': 'state'}, 1)}),
    expr('scan', 0, [], params={'body': expr('add', {'ref': 'state'}, {'ref': 'item'})}),
]

FAILURE_CASES = [
    expr('eval', 'alert(1)'), expr('add', 1), expr('divide', 1, 0),
    expr('normalize', [0, 0]), expr('log2', 0), expr('log', -1), expr('sqrt', -1),
    expr('exp', 1000), expr('pow', -1, .5), expr('add', [1, 2], [1]),
    expr('matmul', [[1, 2]], [[3, 4]]), expr('dot', [1, 2], [1]),
    expr('transpose', [1, 2]), expr('index', [1], 2), expr('index', [1], .5),
    expr('reshape', [1, 2], params={'shape': [3]}), expr('range', 0, 1, 0), expr('range', 10001),
    expr('sum', [1, 2], params={'axis': 2}), expr('slice', [1], params={'step': 0}),
    expr('sum', []), expr('softmax_rows', [1, 2]), expr('clip', 0, 2, 1),
    expr('and', 1, True), expr('add', '1', 2), expr('equal', True, 1),
    expr('iterate', 0, 101, params={'body': expr('add', {'ref': 'state'}, 1)}),
    expr('iterate', 0, -1, params={'body': expr('add', {'ref': 'state'}, 1)}),
    expr('iterate', 0, 1, params={'body': const([1])}),
    expr('map', [1, 2]), expr('scan', 0, [[1]], params={'body': const(1)}),
    expr('add', 1, 2, params={'code': 'alert(1)'}),
    expr('add', [True, 1], 2),
]


class ComputationTests(unittest.TestCase):
    def assertValue(self, actual, expected):
        a, b = np.asarray(actual), np.asarray(expected)
        self.assertEqual(a.shape, b.shape)
        if a.dtype.kind in 'iuf' and b.dtype.kind in 'iuf':
            np.testing.assert_allclose(a, b, atol=1e-10, rtol=1e-10)
        else:
            self.assertEqual(actual, expected)

    def test_registry_has_independent_known_answer_for_every_operator(self):
        self.assertEqual(set(OPERATIONS), {op for op, _, _ in NORMAL_CASES})

    def test_known_answers(self):
        for name, expression, expected in NORMAL_CASES:
            with self.subTest(op=name):
                self.assertValue(evaluate_expression(expression), expected)

    def test_static_inference_for_every_operator(self):
        tasks = []
        for name, expression, expected in NORMAL_CASES:
            s = fixture()
            s['computation'] = {'nodes': [{'id': 'answer', **expression}], 'outputs': ['answer']}
            with self.subTest(op=name):
                types = validate_types_shapes(PaperMechanismIR.model_validate(s))
                actual_shape = np.asarray(expected).shape
                self.assertEqual(len(types['answer'].shape), len(actual_shape))
                for inferred, actual in zip(types['answer'].shape, actual_shape):
                    if inferred is not None: self.assertEqual(inferred, actual)
            tasks.append({'mode': 'types', 'spec': s})
        if shutil.which('node'):
            for (name, _, _), task, answer in zip(NORMAL_CASES, tasks, js(tasks)):
                with self.subTest(js_op=name):
                    self.assertTrue(answer['ok'], answer)
                    t = validate_types_shapes(PaperMechanismIR.model_validate(task['spec']))['answer']
                    self.assertEqual(answer['value']['answer'], {'dtype': t.dtype, 'shape': list(t.shape)})

    def test_deterministic_failures(self):
        for expression in FAILURE_CASES:
            with self.subTest(expression=expression):
                with self.assertRaises(ComputationError):
                    evaluate_expression(expression)

    def test_public_examples(self):
        attention = evaluate(fixture('attention'))
        np.testing.assert_allclose(np.sum(attention['weights'], axis=1), 1)
        np.testing.assert_allclose(attention['attention_output'], np.asarray(attention['weights']) @ np.asarray(attention['V']))
        self.assertEqual(evaluate(fixture('entropy'))['entropy'], 2)
        self.assertEqual(evaluate(fixture('entropy'), {'probabilities': [1, 0, 0, 0]})['entropy'], 0)
        self.assertEqual(evaluate(fixture('entropy'), {'num_outcomes': 2})['entropy'], 1)
        self.assertAlmostEqual(evaluate(fixture())['posterior'], .5625)

    def test_cycles_unknown_refs_and_shapes(self):
        for mutation in ('cycle', 'unknown', 'shape', 'kind'):
            s = fixture()
            if mutation == 'cycle': s['computation']['nodes'][0]['inputs'][0] = {'ref': 'posterior'}
            if mutation == 'unknown': s['computation']['nodes'][0]['inputs'][0] = {'ref': 'missing'}
            if mutation == 'shape': s['computation']['nodes'][0]['shape'] = [2, 2]
            if mutation == 'kind': s['computation']['nodes'][0]['kind'] = 'matrix'
            with self.subTest(mutation=mutation), self.assertRaises(ComputationError): evaluate(s)

    def test_topological_order_and_dependencies(self):
        s = fixture('entropy')
        s['computation']['nodes'].reverse()
        spec = PaperMechanismIR.model_validate(s)
        self.assertEqual(evaluate(spec)['entropy'], 2)
        self.assertIn('entropy', derive_dependencies(spec)['num_outcomes'])
        self.assertEqual(infer_types_shapes(spec)['entropy'], {'kind': 'scalar', 'shape': []})

    def test_static_shape_check_in_inactive_branch(self):
        s = fixture()
        node = s['computation']['nodes'][0]
        node['op'] = 'where'
        node['inputs'] = [const(True), const(.5), expr('matmul', [[1, 2]], [[1, 2]])]
        with self.assertRaises(ComputationError): evaluate(s)
        if shutil.which('node'):
            self.assertFalse(js([{'spec': s}])[0]['ok'])

    def test_general_mechanisms_without_paper_dispatch(self):
        cases = [
            (expr('divide', 1, expr('add', 1, expr('exp', expr('negate', 0)))), .5),
            (expr('iterate', 10, 3, params={'body': expr('subtract', {'ref': 'state'}, expr('multiply', .1, expr('multiply', 2, {'ref': 'state'})))}), 5.12),
            (expr('scan', 0, [2, 4, 6], params={'body': expr('add', expr('multiply', .5, {'ref': 'state'}), expr('multiply', .5, {'ref': 'item'}))}), [1, 2.5, 4.25]),
            (expr('dot', [3, 4], [1, 0]), 3),
            (expr('sum', expr('map', [1, 2, 3], params={'body': expr('pow', {'ref': 'item'}, 2)})), 14),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression): self.assertValue(evaluate_expression(expression), expected)
        if shutil.which('node'):
            for (_, expected), answer in zip(cases, js([{'expression': e} for e, _ in cases])):
                self.assertTrue(answer['ok'], answer)
                self.assertValue(answer['value'], expected)

    @unittest.skipUnless(shutil.which('node'), 'Node is required only for development parity tests')
    def test_javascript_parity_and_independent_answers(self):
        tasks = [{'expression': e} for _, e, _ in NORMAL_CASES] + [{'expression': e} for e in EXTRA_CASES]
        answers = js(tasks)
        for i, (_, expression, expected) in enumerate(NORMAL_CASES):
            with self.subTest(expression=expression):
                self.assertTrue(answers[i]['ok'], answers[i])
                self.assertValue(answers[i]['value'], expected)
        for i, expression in enumerate(EXTRA_CASES, len(NORMAL_CASES)):
            with self.subTest(expression=expression):
                self.assertTrue(answers[i]['ok'], answers[i])
                self.assertValue(answers[i]['value'], evaluate_expression(expression))
        rejected = js([{'expression': e} for e in FAILURE_CASES])
        for expression, answer in zip(FAILURE_CASES, rejected):
            with self.subTest(expression=expression): self.assertFalse(answer['ok'], answer)

    @unittest.skipUnless(shutil.which('node'), 'Development-only Node harness')
    def test_full_fixture_and_scenario_parity(self):
        tasks = []
        for name in ('attention', 'entropy', 'generic'):
            s = fixture(name)
            states = [t['inputs'] for t in s['tests']] + [e['change']['suggested_values'] for e in s['explorations']] + [{}]
            tasks.extend({'spec': s, 'inputs': state} for state in states)
        answers = js(tasks)
        for task, answer in zip(tasks, answers):
            with self.subTest(title=task['spec']['teaching']['title'], state=task['inputs']):
                self.assertTrue(answer['ok'], answer)
                expected = evaluate(task['spec'], task['inputs'])
                self.assertEqual(set(answer['value']), set(expected))
                for key in expected: self.assertValue(answer['value'][key], expected[key])
        registry = js([{'mode': 'registry'}])[0]['value']
        self.assertEqual(set(registry), set(OPERATIONS))
        for op in registry:
            self.assertEqual(registry[op]['arity'], list(OPERATIONS[op].arity))
            self.assertEqual(registry[op]['params'], list(OPERATIONS[op].params))
        s = PaperMechanismIR.model_validate(fixture('entropy'))
        self.assertEqual(js([{'mode': 'dependencies', 'spec': s.model_dump()}])[0]['value'], derive_dependencies(s))
        python_types = {k: {'dtype': v.dtype, 'shape': list(v.shape)} for k, v in validate_types_shapes(s).items()}
        self.assertEqual(js([{'mode': 'types', 'spec': s.model_dump()}])[0]['value'], python_types)

    def test_slice_accepts_integral_float_indices(self):
        expression = expr('slice', [1, 2, 3, 4], params={'start': 1.0, 'stop': -1.0})
        self.assertEqual(evaluate_expression(expression), [2, 3])
        with self.assertRaises(ComputationError):
            evaluate_expression(expr('slice', [1, 2, 3, 4], params={'start': 1.5}))
        s = fixture('entropy')
        s['controls'][1] = {'id': 'num_outcomes', 'type': 'slider', 'label': 'Outcomes', 'value_kind': 'scalar',
                            'default': 3, 'min': 2, 'max': 4, 'step': 1}
        self.assertEqual(evaluate(s, {'num_outcomes': 2.0})['entropy'], 1)
        self.assertTrue(validate_spec(s, source_for(s)).ok)

    @unittest.skipUnless(shutil.which('node'), 'Development-only Node harness')
    def test_reductions_match_javascript_exactly(self):
        # Summation order is identical; exp/log may still differ by an ulp between numpy and V8.
        cases = [expr('sum', [0.1] * 10), expr('mean', [[0.1, 0.2, 0.3], [0.7, 0.1, 0.2]], params={'axis': 1}),
                 expr('normalize', [0.1] * 10),
                 expr('product', [[1.1, 1.3], [1.7, 1.9]], params={'axis': 0}),
                 expr('slice', [1, 2, 3, 4], params={'start': 1.0, 'stop': 3.0})]
        for expression, answer in zip(cases, js([{'expression': e} for e in cases])):
            with self.subTest(expression=expression):
                self.assertEqual(answer['value'], evaluate_expression(expression))


class ValidationTests(unittest.TestCase):
    def test_supplied_fixtures_validate(self):
        for name in ('attention', 'entropy', 'generic'):
            s = fixture(name)
            result = validate_spec(s, source_for(s))
            with self.subTest(name=name):
                self.assertTrue(result.ok, result.model_dump())
                self.assertTrue(result.rubric_summary['interaction']['all_controls_affect_visible_output'])
                self.assertEqual(result.rubric_summary['teaching']['explorations_valid'], 2)
                self.assertTrue(derive_playground(s, source_for(s)).evaluated_defaults)

    def test_schema_rejects_executable_fields_and_bad_operands(self):
        for mutation in ('code', 'operand', 'nan'):
            s = fixture()
            if mutation == 'code': s['compute_js'] = 'alert(1)'
            if mutation == 'operand': s['computation']['nodes'][0]['inputs'][0] = 'prior/(1-prior)'
            if mutation == 'nan': s['controls'][0]['default'] = float('nan')
            with self.subTest(mutation=mutation): self.assertFalse(validate_spec(s).ok)

    def test_unknown_source_refs_and_grounding(self):
        s = fixture()
        self.assertFalse(validate_spec(s, []).ok)
        s['mechanism_grounding'] = []
        self.assertFalse(validate_spec(s, source_for(s)).ok)

    def test_dead_controls_and_fake_visible_echo_fail(self):
        s = fixture()
        s['controls'].append({**s['controls'][0], 'id': 'unused'})
        s['computation']['outputs'].append('unused')
        result = validate_spec(s, source_for(s))
        self.assertFalse(result.ok)
        self.assertIn('control_visible_influence', {f.check for f in result.failures})

    def test_boundary_division_by_zero_fails(self):
        s = fixture()
        s['controls'][0]['max'] = 1
        result = validate_spec(s, source_for(s))
        self.assertFalse(result.ok)
        self.assertIn('control_boundary', {f.check for f in result.failures})

    def test_invalid_exploration_and_expectation(self):
        for mutation in ('unknown', 'bounds', 'same', 'expectation'):
            s = fixture()
            e = s['explorations'][0]
            if mutation == 'unknown': e['change']['suggested_values'] = {'missing': 1}
            if mutation == 'bounds': e['change']['suggested_values'] = {'prior': 100}
            if mutation == 'same': e['change']['suggested_values'] = {}
            if mutation == 'expectation': e['expectation']['expected'] = .99
            with self.subTest(mutation=mutation): self.assertFalse(validate_spec(s, source_for(s)).ok)

    def test_invariants_rechecked_on_boundaries(self):
        s = fixture()
        s['invariants'][0]['assertion'] = {'op': 'less_than', 'expected': .6}
        result = validate_spec(s, source_for(s))
        self.assertFalse(result.ok)
        self.assertIn('invariant', {f.check for f in result.failures})

    def test_visual_fallback_is_recoverable_and_binding_error_is_not(self):
        s = fixture()
        s['visuals'] = [{'type': 'unsupported', 'value': 'posterior'}]
        result = validate_spec(s, source_for(s))
        self.assertTrue(result.ok, result.model_dump())
        self.assertTrue(result.rubric_summary['visual']['requires_fallback'])
        s['visuals'][0]['value'] = 'missing'
        self.assertFalse(validate_spec(s, source_for(s)).ok)

    def test_schema_errors_use_ir_paths(self):
        s = fixture()
        s['computation']['nodes'][0]['inputs'][0] = {'ref': 'prior', 'bogus': 1}
        failures = validate_spec(s).failures
        self.assertEqual([(f.path, f.allowed_paths) for f in failures],
                         [('computation.nodes.0.inputs.0.bogus', ['computation.nodes.0.inputs.0.bogus'])])

    def test_repair_paths_and_rubric_keys(self):
        s = fixture()
        s['controls'].append({**s['controls'][0], 'id': 'unused'})
        result = validate_spec(s, source_for(s))
        failure = next(f for f in result.failures if f.check == 'control_visible_influence')
        self.assertEqual(failure.allowed_paths, ['controls.2', 'computation.outputs', 'computation.nodes', 'visuals'])
        self.assertTrue(result.rubric_summary['visual']['meaningful_non_table_visual'])

    def test_derive_playground_keeps_usable_candidates(self):
        s = fixture()
        s['visuals'][0]['value'] = 'missing'
        result = validate_spec(s, source_for(s))
        self.assertFalse(result.ok)
        derived = derive_playground(s, validation=result)
        self.assertNotIn('missing', derived.visible_nodes)
        self.assertAlmostEqual(derived.evaluated_defaults['posterior'], .5625)
        s['controls'][0]['default'] = 1
        with self.assertRaises(ComputationError):
            derive_playground(s, source_for(s))

    def test_trace_callback_and_case_extra_fields(self):
        events = []
        s = fixture()
        validate_spec(s, source_for(s), lambda stage, action, result: events.append((stage, action, result)))
        self.assertTrue(any(action == 'control_influence' for _, action, _ in events))
        self.assertEqual(Case(source_url='url', focus='focus', audience='audience', excerpt='text').model_extra['excerpt'], 'text')


if __name__ == '__main__':
    unittest.main()
