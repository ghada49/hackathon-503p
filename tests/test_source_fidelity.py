from playground.source import Case, SourceDocument, normalize_source, resolve_source
from playground.retrieval import select_source_context
import pytest


def html_document(tmp_path, html):
    path = tmp_path / 'paper.html'
    path.write_text(html, encoding='utf-8')
    document = resolve_source(Case(source_url='citation', focus='convergence', audience='students', source_path=str(path)))
    normalize_source(document)
    return document


def test_uncovered_div_prose_preserved_in_order_and_full_context(tmp_path):
    html = '<h2>Convergence</h2><div>Assume L &gt; 0.</div><p>eta &lt; 2/L guarantees convergence.</p>'
    doc = html_document(tmp_path, html)
    assert [(b.type, b.text) for b in doc.blocks] == [
        ('heading', 'Convergence'), ('paragraph', 'Assume L > 0.'),
        ('paragraph', 'eta < 2/L guarantees convergence.')]
    context = select_source_context(doc, 'convergence', 'students')
    assert context.blocks == doc.blocks
    assert context.coverage['full_source_included']
    assert doc.raw_text == html


def test_nested_div_paragraph_text_is_not_duplicated(tmp_path):
    doc = html_document(tmp_path, '<div>Before <span>inline</span><div><p>Nested paragraph.</p></div>After.</div>')
    assert [b.text for b in doc.blocks] == ['Before inline', 'Nested paragraph.', 'After.']


def test_uncovered_prose_surrounding_equations(tmp_path):
    doc = html_document(tmp_path, '<div>Before.<math><mi>x</mi><mo>=</mo><mn>2</mn></math>After.</div>')
    assert [(b.type, b.text) for b in doc.blocks] == [('paragraph', 'Before.'), ('equation', 'x = 2'), ('paragraph', 'After.')]


def test_lists_tables_captions_and_container_prose_survive(tmp_path):
    doc = html_document(tmp_path, '<div>Assumption.</div><ul><li>First</li><li>Second</li></ul><table><tr><td>eta</td><td>0.1</td></tr></table><figcaption>Figure: curve.</figcaption><div>Conclusion.</div>')
    assert [b.type for b in doc.blocks] == ['paragraph', 'list', 'table', 'caption', 'paragraph']
    text = ' '.join(b.text for b in doc.blocks)
    for expected in ['Assumption.', 'First', 'Second', 'eta', '0.1', 'Figure: curve.', 'Conclusion.']:
        assert text.count(expected) == 1


def test_comments_and_executable_script_are_excluded(tmp_path):
    doc = html_document(tmp_path, '<div>Scientific text.</div><!-- invisible --><script>execute_me()</script><style>style_me</style>')
    assert [b.text for b in doc.blocks] == ['Scientific text.']


@pytest.mark.parametrize('markup,expected', [
    ('<mfrac><mn>1</mn><mn>2</mn></mfrac>', '(1)/(2)'),
    ('<msup><mi>x</mi><mn>2</mn></msup>', 'x^(2)'),
    ('<msub><mi>x</mi><mi>i</mi></msub>', 'x_(i)'),
    ('<msubsup><mi>x</mi><mi>i</mi><mn>2</mn></msubsup>', 'x_(i)^(2)'),
    ('<msqrt><mi>x</mi></msqrt>', 'sqrt(x)'),
    ('<mroot><mi>x</mi><mn>3</mn></mroot>', 'root(x,3)'),
    ('<mfrac><msup><mi>x</mi><mn>2</mn></msup><mi>y</mi></mfrac>', '(x^(2))/(y)'),
    ('<mi>eta</mi><mo>&lt;</mo><mn>2</mn><mo>/</mo><mi>L</mi>', 'eta < 2 / L'),
])
def test_mathml_structural_operators(tmp_path, markup, expected):
    raw = '<h2>Rule</h2><math>' + markup + '</math>'
    doc = html_document(tmp_path, raw)
    assert doc.blocks[1].type == 'equation'
    assert doc.blocks[1].text == expected
    assert doc.raw_source == raw
    assert select_source_context(doc, 'rule', 'students').coverage['full_source_included']


def test_mathml_tex_annotation_preferred_without_duplicate_presentation(tmp_path):
    doc = html_document(tmp_path, '<math><semantics><mfrac><mn>1</mn><mn>2</mn></mfrac>'
        '<annotation encoding="application/x-tex">\\frac{1}{2}</annotation></semantics></math>')
    assert doc.blocks[0].text == r'\frac{1}{2}'


def test_unknown_mathml_fallback_does_not_claim_full_fidelity(tmp_path):
    raw = '<p>Rule</p><math><mystery><mi>x</mi><mi>y</mi></mystery></math>'
    doc = html_document(tmp_path, raw)
    assert doc.raw_source == raw
    assert doc.blocks[-1].text == 'x y'
    assert doc.metadata['extraction_faithful'] is False
    assert not select_source_context(doc, 'rule', 'students').coverage['full_source_included']


def test_mathml_depth_bound_marks_fallback(tmp_path):
    markup = '<msqrt>' * 40 + '<mi>x</mi>' + '</msqrt>' * 40
    doc = html_document(tmp_path, '<math>' + markup + '</math>')
    assert 'x' in doc.blocks[0].text
    assert not doc.metadata['extraction_faithful']


def test_supplied_partial_blocks_with_raw_prose_cannot_claim_full_inclusion():
    raw = '# Rule\nAssume L > 0.\n\neta < 2/L.'
    doc = SourceDocument(source_url='paper', origin='supplied', raw_text=raw, blocks=[
        dict(id='h', type='heading', text='Rule', order=0),
        dict(id='p', type='paragraph', text='eta < 2/L.', order=1),
    ])
    normalize_source(doc)
    assert doc.raw_source == raw
    assert not select_source_context(doc, 'rule', 'students').coverage['full_source_included']


def test_supplied_complete_blocks_and_raw_prose_keep_full_inclusion():
    raw = '# Rule\nAssume L > 0.\n\neta < 2/L.'
    doc = SourceDocument(source_url='paper', origin='supplied', raw_text=raw, blocks=[
        dict(id='h', type='heading', text='Rule', order=0),
        dict(id='p', type='paragraph', text='Assume L > 0.', order=1),
        dict(id='e', type='equation', text='eta < 2/L.', order=2),
    ])
    normalize_source(doc)
    assert select_source_context(doc, 'rule', 'students').coverage['full_source_included']


def test_nested_tex_annotation_applies_only_to_its_subexpression(tmp_path):
    raw = '<math><mfrac><semantics><mi>x</mi><annotation encoding="application/x-tex">x</annotation></semantics><mn>2</mn></mfrac></math>'
    doc = html_document(tmp_path, raw)
    assert doc.blocks[0].text == '(x)/(2)'
    assert doc.raw_source == raw


@pytest.mark.parametrize('tag,base,expected', [
    ('msup', '<mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow>', '(x + y)^(2)'),
    ('msup', '<mfrac><mn>1</mn><mn>2</mn></mfrac>', '((1)/(2))^(2)'),
    ('msub', '<mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow>', '(x + y)_(2)'),
])
def test_composite_mathml_bases_are_grouped(tmp_path, tag, base, expected):
    doc = html_document(tmp_path, f'<math><{tag}>{base}<mn>2</mn></{tag}></math>')
    assert doc.blocks[0].text == expected
