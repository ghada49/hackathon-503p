"""Integration gates for the final scientific runtime contract."""
import json
import shutil
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import patch

from playground.computation import ComputationError, evaluate, evaluate_expression
from playground.models import PaperMechanismIR
from playground.validation import derive_playground, validate_spec
from test_science_runtime import ROOT, const, expr, fixture, js, source_for
from test_runtime_freeze_regressions import CountingEvaluator


class FinalContractTests(unittest.TestCase):
    def test_mixed_array_rejection_and_valid_homogeneous_arrays(self):
        invalid = [[1, '1'], ['1', 1], [True, 1], [1, False],
                   ['true', True], [[1, 2], [3, '4']]]
        cases = [expr('equal', value, value) for value in invalid]
        cases += [expr('concat', ['1'], [1])]
        for expression in cases:
            with self.subTest(expression=expression), self.assertRaises(ComputationError):
                evaluate_expression(expression)
        valid = [[1, 2.5], [True, False], ['a', 'b'], [[1, 2.5], [3, 4]]]
        for value in valid:
            self.assertEqual(evaluate_expression(expr('flatten', value)),
                             value if not isinstance(value[0], list) else [1, 2.5, 3, 4])
        if shutil.which('node'):
            for answer in js([{'expression': e} for e in cases]):
                self.assertFalse(answer['ok'], answer)
            for value, answer in zip(valid, js([{'expression': expr('flatten', v)} for v in valid])):
                self.assertTrue(answer['ok'], answer)
                self.assertEqual(answer['value'], evaluate_expression(expr('flatten', value)))

    def test_mixed_arrays_rejected_in_full_ir_and_control_overrides(self):
        s = fixture()
        s['computation']['nodes'].append({'id': 'mixed', **expr('equal', ['1', 1], ['1', '1'])})
        with self.assertRaises(ComputationError):
            evaluate(s)
        controls = fixture()
        controls['controls'].append({'id': 'vector_input', 'type': 'vector_editor',
                                    'label': 'Vector', 'value_kind': 'vector', 'default': [1, 2]})
        with self.assertRaises(ComputationError):
            evaluate(controls, {'vector_input': [True, 2]})
        if shutil.which('node'):
            for answer in js([{'spec': s}, {'spec': controls, 'inputs': {'vector_input': [True, 2]}}]):
                self.assertFalse(answer['ok'], answer)

    def test_scan_rejects_before_body_execution(self):
        body = expr('divide', {'ref': 'state'}, 0)
        expression = expr('scan', [1] * 1000, list(range(11)), params={'body': body})
        evaluator = CountingEvaluator(body)
        with self.assertRaisesRegex(ComputationError, 'scan projected output'):
            evaluator.expression(expression, {})
        self.assertEqual(evaluator.body_calls, 0)
        if shutil.which('node'):
            answer = js([{'expression': expression}])[0]
            self.assertFalse(answer['ok'])
            self.assertIn('scan projected output', answer['error'])

    def test_concat_rejects_before_numpy_allocation(self):
        for axis, value in [(0, [1] * 6000), (1, [[1] * 6000])]:
            expression = expr('concat', value, value, params={'axis': axis})
            with patch('playground.computation.np.concatenate', side_effect=AssertionError('Allocated')) as allocate:
                with self.assertRaisesRegex(ComputationError, 'concat projected output'):
                    evaluate_expression(expression)
                allocate.assert_not_called()

    @unittest.skipUnless(shutil.which('node'), 'Node required for allocation regression')
    def test_concat_rejects_before_javascript_materialization(self):
        script = r'''
const runtime = require('./runtime/computation.js');
const originalFlat = Array.prototype.flat, originalFlatMap = Array.prototype.flatMap;
let materialized = false;
Array.prototype.flat = function(depth) {
  if (depth === 1 && this.length === 2 && this.every(x => Array.isArray(x) && x.length === 6000)) {
    materialized = true; throw Error('Allocated');
  }
  return originalFlat.call(this, depth);
};
Array.prototype.flatMap = function(fn) { materialized = true; throw Error('Allocated'); };
const errors = [];
try {
  for (const axis of [0, 1]) {
    const row = Array(6000).fill(1), value = axis === 0 ? row : [row];
    try { runtime.evaluateExpression({op:'concat', inputs:[{const:value},{const:value}], params:{axis}}); }
    catch (e) { errors.push(e.message); }
  }
} finally { Array.prototype.flat = originalFlat; Array.prototype.flatMap = originalFlatMap; }
process.stdout.write(JSON.stringify({materialized, errors}));
'''
        answer = json.loads(subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True,
                                           text=True, check=True, timeout=30).stdout)
        self.assertFalse(answer['materialized'])
        self.assertEqual(answer['errors'], ['concat projected output exceeds element limit'] * 2)

    def test_scan_concat_at_limit_and_empty_results(self):
        cases = [expr('scan', expr('range', 100), expr('range', 100), params={'body': {'ref': 'state'}}),
                 expr('concat', expr('range', 5000), expr('range', 5000)),
                 expr('scan', 0, [], params={'body': expr('divide', 1, 0)}),
                 expr('concat', [], [])]
        results = [evaluate_expression(e) for e in cases]
        self.assertEqual(len(results[0]), 100)
        self.assertEqual(len(results[0][0]), 100)
        self.assertEqual(len(results[1]), 10000)
        self.assertEqual(results[2:], [[], []])
        if shutil.which('node'):
            for answer, expected in zip(js([{'expression': e} for e in cases]), results):
                self.assertTrue(answer['ok'], answer)
                self.assertEqual(answer['value'], expected)

    def test_visual_component_collisions_use_recoverable_fallback(self):
        for reserved in ('controls', 'main_visual', 'teaching'):
            s = fixture()
            s['visuals'][1]['id'] = reserved
            s['experience'] = {'hero_visual': reserved, 'guided_mode': [
                {'target': reserved, 'instruction': 'Inspect this target.'}]}
            report = validate_spec(s, source_for(s))
            self.assertTrue(report.ok, report.model_dump())
            self.assertTrue(any(w.check == 'experience_fallback' and w.severity == 'recoverable'
                                for w in report.warnings))
            self.assertIsNone(derive_playground(s, validation=report).resolved_experience)

    def test_dead_control_scopes_support_wiring_without_unrelated_fields(self):
        s = fixture()
        s['controls'].append({**s['controls'][0], 'id': 'unused'})
        s['computation']['nodes'].append({'id': 'unrelated', **expr('add', 1, 2)})
        s['visuals'].append({'type': 'number', 'value': 'unrelated'})
        report = validate_spec(s, source_for(s))
        failure = next(f for f in report.failures if f.check == 'control_influence' and f.path == 'controls.2')
        paths = set(failure.allowed_paths)
        self.assertIn('controls.2', paths)
        self.assertIn('computation.nodes.0', paths)
        self.assertIn('visuals.1.bindings', paths)
        self.assertNotIn('computation.nodes.5', paths)
        self.assertNotIn('visuals.4.bindings', paths)
        self.assertFalse(any(p.split('.')[0] in {'teaching', 'evidence', 'provenance', 'tests', 'invariants'} for p in paths))
        repaired = deepcopy(s)
        repaired['computation']['nodes'][0]['inputs'][0] = expr('multiply', {'ref': 'prior'}, {'ref': 'unused'})
        after = validate_spec(repaired, source_for(repaired))
        self.assertFalse(any(f.path == 'controls.2' and f.check in {'control_influence', 'control_visible_influence'}
                             for f in after.failures))

    def test_hidden_control_path_scopes_do_not_open_other_nodes(self):
        s = fixture()
        s['controls'].append({**s['controls'][0], 'id': 'hidden_control'})
        s['computation']['nodes'].append({'id': 'hidden', **expr('multiply', {'ref': 'hidden_control'}, 2)})
        report = validate_spec(s, source_for(s))
        failure = next(f for f in report.failures if f.check == 'control_visible_influence' and f.path == 'controls.2')
        self.assertIn('computation.nodes.5', failure.allowed_paths)  # Can enable node.display.
        self.assertFalse(any(p.startswith('computation.nodes.') and p != 'computation.nodes.5'
                             for p in failure.allowed_paths))

    def test_invalid_operand_has_exact_message_and_real_path(self):
        for nested in (False, True):
            s = fixture()
            operand = 'prior/(1-prior)'
            if nested:
                operand = expr('add', operand, 1)
                operand['inputs'][0] = 'prior/(1-prior)'
            s['computation']['nodes'][0]['inputs'][0] = operand
            report = validate_spec(s)
            self.assertEqual(len(report.failures), 1)
            failure = report.failures[0]
            self.assertEqual(failure.message, 'Operand must be {ref}, {const}, or {op, inputs}.')
            self.assertEqual(failure.path, 'computation.nodes.0.inputs.0' + ('.inputs.0' if nested else ''))

    def test_validation_report_reuse_and_default_behavior(self):
        s = fixture()
        s['tests'][0]['assertions'][0]['expected'] = .99
        report = validate_spec(s, source_for(s))
        with patch('playground.validation.validate_spec', side_effect=AssertionError('Revalidated')):
            derived = derive_playground(s, validation=report)
        self.assertIs(derived.validation, report)
        self.assertFalse(derived.validation.ok)
        self.assertAlmostEqual(derived.evaluated_defaults['posterior'], .5625)
        with patch('playground.validation.validate_spec', wraps=validate_spec) as validate:
            fresh = derive_playground(s, source_for(s))
            validate.assert_called_once()
        self.assertEqual(fresh.validation.model_dump(), report.model_dump())
        s['computation']['nodes'][0]['inputs'][1] = const(0)
        with self.assertRaises(ComputationError):
            derive_playground(s, validation=report)


if __name__ == '__main__':
    unittest.main()
