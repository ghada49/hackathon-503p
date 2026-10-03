"""Regression gates for boolean parity and allocation bounds before contract freeze."""
from __future__ import annotations

import shutil
import unittest

from playground.computation import ComputationError, Evaluator, evaluate, evaluate_expression
from test_science_runtime import const, expr, fixture, js


class BooleanWhereTests(unittest.TestCase):
    def assertBooleanTree(self, actual, expected):
        if isinstance(expected, list):
            self.assertIsInstance(actual, list)
            self.assertEqual(len(actual), len(expected))
            for a, b in zip(actual, expected):
                self.assertBooleanTree(a, b)
        else:
            self.assertIs(type(actual), bool)  # True == 1 must not hide coercion.
            self.assertEqual(actual, expected)

    def cases(self):
        nested = expr('where', [True, False],
                      expr('not', expr('where', [True, False], [False, True], True)),
                      False)
        return [
            (expr('where', [True, True], [True, False], False), [True, False]),
            (expr('where', [False, False], True, [True, False]), [True, False]),
            (expr('where', [[True, True], [True, True]], [[True, False], [False, True]], False),
             [[True, False], [False, True]]),
            (expr('where', [[False, False], [False, False]], True, [[True, False], [False, True]]),
             [[True, False], [False, True]]),
            (expr('where', [True, False], True, False), [True, False]),
            (nested, [True, False]),
            (expr('where', [True, True], True, expr('greater', expr('divide', 1, 0), 0)),
             [True, True]),
        ]

    def test_python_preserves_boolean_dtype_and_downstream_logic(self):
        for expression, expected in self.cases():
            with self.subTest(expression=expression):
                self.assertBooleanTree(evaluate_expression(expression), expected)
                inverse = evaluate_expression(expr('not', expression))
                # Check downstream boolean consumption as well as displayed values.
                self.assertBooleanTree(evaluate_expression(expr('not', const(inverse))), expected)

    @unittest.skipUnless(shutil.which('node'), 'Node required for parity regression')
    def test_boolean_where_full_ir_parity(self):
        tasks, expected_values = [], []
        for expression, expected in self.cases():
            s = fixture()
            s['computation'] = {
                'nodes': [{'id': 'flags', **expression},
                          {'id': 'inverted', **expr('not', {'ref': 'flags'})}],
                'outputs': ['flags', 'inverted'],
            }
            values = evaluate(s)
            self.assertBooleanTree(values['flags'], expected)
            tasks.append({'spec': s})
            expected_values.append(values)
        for answer, expected in zip(js(tasks), expected_values):
            self.assertTrue(answer['ok'], answer)
            for node in ('flags', 'inverted'):
                self.assertBooleanTree(answer['value'][node], expected[node])


class CountingEvaluator(Evaluator):
    """Observe body execution directly, without allocating an oversized fixture."""
    def __init__(self, body):
        super().__init__()
        self.body = body
        self.body_calls = 0

    def expression(self, expression, values, mask=None, depth=0):
        if expression is self.body:
            self.body_calls += 1
        return super().expression(expression, values, mask, depth)


class MapAllocationTests(unittest.TestCase):
    def oversized_cases(self):
        static_body = expr('divide', [1] * 100, 0)
        # Unknown length before evaluation. The first result has 100 entries;
        # evaluating the second body would hit an intentionally invalid domain.
        dynamic_body = expr('where', expr('equal', {'ref': 'index'}, 0),
                            expr('range', 100), expr('range', expr('divide', 1, 0)))
        return [(expr('map', list(range(101)), params={'body': static_body}), static_body, 0),
                (expr('map', list(range(101)), params={'body': dynamic_body}), dynamic_body, 1)]

    def test_oversized_projection_stops_before_materializing_result(self):
        for expression, body, allowed_calls in self.oversized_cases():
            with self.subTest(allowed_calls=allowed_calls):
                evaluator = CountingEvaluator(body)
                with self.assertRaisesRegex(ComputationError, 'map projected output exceeds element limit'):
                    evaluator.expression(expression, {})
                self.assertEqual(evaluator.body_calls, allowed_calls)

    @unittest.skipUnless(shutil.which('node'), 'Node required for parity regression')
    def test_javascript_rejects_projection_before_later_body_errors(self):
        answers = js([{'expression': expression} for expression, _, _ in self.oversized_cases()])
        for answer in answers:
            self.assertFalse(answer['ok'], answer)
            self.assertIn('map projected output exceeds element limit', answer['error'])

    def test_rank_and_elementwise_rejected_before_body_evaluation(self):
        for op, body, message in [
            ('map', expr('divide', [[1]], 0), 'map projected output exceeds rank limit'),
            ('elementwise', expr('divide', [1], 0), 'elementwise body must return a scalar'),
        ]:
            expression = expr(op, [1, 2], params={'body': body})
            evaluator = CountingEvaluator(body)
            with self.assertRaisesRegex(ComputationError, message):
                evaluator.expression(expression, {})
            self.assertEqual(evaluator.body_calls, 0)

    def test_valid_limit_empty_and_ragged_maps(self):
        at_limit = expr('map', expr('range', 100), params={'body': expr('range', 100)})
        expected = [list(range(100)) for _ in range(100)]
        self.assertEqual(evaluate_expression(at_limit), expected)
        empty = expr('map', [], params={'body': expr('divide', 1, 0)})
        self.assertEqual(evaluate_expression(empty), [])
        ragged = expr('map', [1, 2], params={'body': expr('range', {'ref': 'item'})})
        with self.assertRaisesRegex(ComputationError, 'map body result shape changed'):
            evaluate_expression(ragged)
        if shutil.which('node'):
            answers = js([{'expression': e} for e in (at_limit, empty, ragged)])
            self.assertTrue(answers[0]['ok'], answers[0])
            self.assertEqual(answers[0]['value'], expected)
            self.assertTrue(answers[1]['ok'], answers[1])
            self.assertEqual(answers[1]['value'], [])
            self.assertFalse(answers[2]['ok'])
            self.assertIn('map body result shape changed', answers[2]['error'])


if __name__ == '__main__':
    unittest.main()
