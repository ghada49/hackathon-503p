from playground.source import SourceDocument, normalize_source
from playground.retrieval import build_focus_context, select_source_context


def test_numbered_heading_inherits_supplied_canonical_section_and_keeps_equation():
    doc = SourceDocument(source_url='paper', origin='supplied', blocks=[
        dict(id='h', type='heading', text='2 Method', section='Method', order=0),
        dict(id='p', type='paragraph', text='The stability method uses eta.', order=1),
        dict(id='q', type='paragraph', text='Let L be the curvature bound.', section='2 Method', order=2),
        dict(id='e', type='equation', text='eta < 2/L', order=3),
        dict(id='a', type='heading', text='3 Appendix', order=4),
        dict(id='f', type='paragraph', text='Unrelated filler. ' * 400, order=5),
    ])
    blocks = normalize_source(doc)
    assert {b.section for b in blocks[:4]} == {'Method'}
    assert len(doc.structural_map['sections']) == 2
    assert doc.structural_map['sections'][0]['block_ids'] == [b.id for b in blocks[:4]]
    context = build_focus_context(doc, 'stability method eta', 'students', max_chars=2300)
    assert {b.id for b in blocks[:4]} <= {b.id for b in context.blocks}
    assert blocks[0].text == '2 Method'


def test_markdown_heading_without_blank_line_terminates_large_intro():
    raw = '# Intro\n' + 'Large unrelated introduction. ' * 400 + '\n## Convergence\nStability requires eta < 2/L.\n### Limits\nAssume L > 0.'
    doc = SourceDocument(source_url='paper', origin='supplied', raw_text=raw)
    blocks = normalize_source(doc)
    assert [b.text for b in blocks if b.type == 'heading'] == ['Intro', 'Convergence', 'Limits']
    assert [b.section for b in blocks] == ['Intro', 'Intro', 'Convergence', 'Convergence', 'Limits', 'Limits']
    context = build_focus_context(doc, 'stability convergence', 'students', max_chars=2000)
    assert any('Stability requires' in b.text for b in context.blocks)
    assert doc.raw_source == raw


def test_fence_heading_like_text_is_algorithm_and_sections_resume():
    raw = '# Method\n```python\n# not a heading\nx = 2\n```\n## Results\nObserved convergence.'
    doc = SourceDocument(source_url='paper', origin='supplied', raw_text=raw)
    blocks = normalize_source(doc)
    assert [b.type for b in blocks] == ['heading', 'algorithm', 'heading', 'paragraph']
    assert '# not a heading' in blocks[1].text
    assert blocks[1].section == 'Method'
    assert blocks[3].section == 'Results'


def test_neighborhood_is_not_true_without_any_matched_core():
    doc = SourceDocument(source_url='paper', origin='supplied', raw_text='# Intro\nUnrelated text.\n## Other\nMore material.')
    normalize_source(doc)
    context = build_focus_context(doc, 'unmatched mechanism', 'students', max_chars=2000)
    assert not context.coverage['focus_region_present']
    assert not context.coverage['neighboring_context_present']


def test_full_bypass_does_not_assert_unassessed_core_neighborhood():
    doc = SourceDocument(source_url='paper', origin='supplied', raw_text='# Intro\nUnrelated text.')
    context = select_source_context(doc, 'unmatched mechanism', 'students', max_chars=2000)
    assert context.mode == 'full'
    assert context.coverage['focus_region_present'] is None
    assert context.coverage['neighboring_context_present'] is None
