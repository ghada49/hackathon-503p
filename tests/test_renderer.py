import json
import unittest
from pathlib import Path

from playground.renderer import render, safe_json
from playground.visuals import resolve_visual


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.ir = json.loads(Path('tests/fixtures/attention_ir.json').read_text(encoding='utf-8'))

    def test_all_shared_fixtures_package_offline(self):
        for name in ('attention', 'entropy', 'generic'):
            ir = json.loads(Path(f'tests/fixtures/{name}_ir.json').read_text(encoding='utf-8'))
            result = render(ir)
            self.assertIn(ir['teaching']['title'], result)
            self.assertNotIn('<script src=', result)
            self.assertNotIn('<link ', result)
            self.assertIn('id="source"', result)
            self.assertNotIn('[[RUNTIME]]', result)

    def test_source_cannot_terminate_json_script(self):
        attack = '</script><script>alert(1)</script>&\u2028'
        self.ir['teaching']['title'] = attack
        result = render(self.ir)
        self.assertNotIn(attack, result)
        self.assertEqual(json.loads(safe_json({'text': attack}))['text'], attack)

    def test_template_markers_in_user_text_stay_text(self):
        self.ir['teaching']['title'] = '[[RUNTIME]]'
        result = render(self.ir)
        self.assertIn('<title>[[RUNTIME]]</title>', result)

    def test_nonfinite_reference_values_rejected(self):
        with self.assertRaises(ValueError):
            render(self.ir, {'bad': float('nan')})

    def test_unknown_visual_has_meaningful_fallback(self):
        self.assertEqual(resolve_visual({'type': 'unknown', 'value': 'v'}, {'v': [1, 2]})['type'], 'bar_chart')
        self.assertEqual(resolve_visual({'type': 'unknown'}, {})['type'], 'pipeline')


if __name__ == '__main__':
    unittest.main()
