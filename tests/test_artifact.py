import json
from pathlib import Path

import pytest

from playground.artifact import validate_artifact
from playground.renderer import render


def artifact(tmp_path):
    ir = json.loads((Path(__file__).parent / 'fixtures/generic_ir.json').read_text())
    path = tmp_path / 'index.html'
    path.write_text(render(ir, source={'source_url': 'https://example.org/paper'}), encoding='utf-8')
    return path


def test_static_check_allows_user_initiated_citations_and_literal_style_words(tmp_path):
    path = artifact(tmp_path)
    text = path.read_text(encoding='utf-8')
    assert '"url": "https://example.org/paper"' in text
    text = text.replace('Bayesian Update with Odds', 'Literal @import text and url(https://example.org)')
    path.write_text(text, encoding='utf-8')
    assert validate_artifact(path)['self_contained_resources']


@pytest.mark.parametrize('change', [
    lambda html: html.replace('id="controls"', 'id="removed-controls"'),
    lambda html: html.replace('<script>', '<script src="https://example.org/runtime.js">', 1),
    lambda html: html.replace('<style>', '<style>@import "https://example.org/style.css";', 1),
    lambda html: html.replace('id="controls"', 'id="main"'),
    lambda html: html.replace('"ir": {', '"ir": NaN, "unused": {', 1),
])
def test_static_check_rejects_broken_or_remote_packaging(tmp_path, change):
    path = artifact(tmp_path)
    path.write_text(change(path.read_text(encoding='utf-8')), encoding='utf-8')
    with pytest.raises(ValueError):
        validate_artifact(path)
