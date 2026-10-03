import json

import pytest

from playground.source import SourceDocument, normalize_source, Case, resolve_source
from playground.retrieval import (build_focus_context, select_source_context, source_context_payload)
from playground.generator import build_generation_messages, generation_prompt_overhead


def document(sections):
    items = []
    for number, (title, contents) in enumerate(sections, 1):
        items.append(dict(id=f'input{len(items)}', type='heading', text=title, section_number=str(number), order=len(items)))
        for kind, text, extra in contents:
            items.append(dict(id=f'input{len(items)}', type=kind, text=text, order=len(items), **extra))
    doc = SourceDocument(source_url='paper', origin='supplied', blocks=items)
    normalize_source(doc)
    return doc


def sample_source():
    return document([
        ('Definitions', [('paragraph', 'We define eta as the step size. Let L be the curvature bound.', {})]),
        ('Unrelated experiment', [('paragraph', 'Background experiment. ' * 500, {})]),
        ('Convergence criterion', [
            ('paragraph', 'Stability requires the condition in Eq. (7). See Section 5 for its prerequisite.', {}),
            ('equation', 'eta < 2 / L', {'equation_number': '8'}),
            ('algorithm', 'Algorithm 1: Repeat a bounded update with step eta.', {}),
            ('table', '| eta | convergent |\n| small | yes |', {}),
            ('caption', 'Figure 1: Effect of the convergence bound.', {}),
        ]),
        ('Proof relationship', [('equation', 'L = gradient curvature; see Eq. (9).', {'equation_number': '7'})]),
        ('Prerequisites', [('paragraph', 'Equation 9 requires bounded curvature and smoothness.', {}), ('equation', 'L > 0', {'equation_number': '9'})]),
        ('Assumptions', [('paragraph', 'The toy rule assumes a smooth objective. Experimental results are not reproduced.', {})]),
        ('More experiments', [('paragraph', 'Other unrelated measurements. ' * 500, {})]),
    ])


def test_short_source_bypasses_focus_builder_and_stays_whole(monkeypatch):
    raw = '# Rule\n\nThe complete scientific explanation.\n\n$$x = 2$$'
    doc = SourceDocument(source_url='paper', origin='supplied', raw_text=raw)
    blocks = normalize_source(doc)
    def forbidden(*args, **kwargs):
        pytest.fail('Small source must not retrieve or rank')
    monkeypatch.setattr('playground.retrieval.build_focus_context', forbidden)
    context = select_source_context(doc, 'anything', 'students', max_chars=4000)
    assert context.blocks == blocks
    assert context.mode == 'full'
    assert context.coverage['full_source_included'] is True
    assert doc.raw_text == raw


def test_long_source_calls_progressive_builder(monkeypatch):
    doc = sample_source()
    calls = []
    original = build_focus_context
    def capture(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr('playground.retrieval.build_focus_context', capture)
    context = select_source_context(doc, 'stability condition eta L', 'students', max_chars=6500)
    assert calls == [True]
    assert context.mode in ('focused', 'broad')
    assert context.coverage['full_source_included'] is False


def test_coherent_core_section_and_non_prose_survive():
    doc = sample_source()
    context = select_source_context(doc, 'stability condition eta L', 'students', max_chars=6500)
    core = [b for b in doc.blocks if b.section == 'Convergence criterion']
    assert {b.id for b in core}.issubset({b.id for b in context.blocks})
    assert {'equation', 'algorithm', 'table', 'caption'}.issubset({b.type for b in context.blocks})
    assert context.coverage['focus_region_present']
    assert context.coverage['nearby_equations_algorithms_present']


def test_definitions_prerequisites_and_depth_two_reference_closure():
    context = select_source_context(sample_source(), 'stability condition eta L', 'students', max_chars=6500)
    texts = ' '.join(b.text for b in context.blocks)
    assert 'We define eta' in texts
    assert 'bounded curvature and smoothness' in texts
    assert any(b.equation_number == '7' for b in context.blocks)
    assert any(b.equation_number == '9' for b in context.blocks)
    assert context.coverage['referenced_material_resolved']
    assert context.coverage['definitions_found']


def test_outline_contains_original_headings_with_stable_ids():
    doc = sample_source()
    context = select_source_context(doc, 'stability', 'students', max_chars=6500)
    assert [item['title'] for item in context.outline] == [b.text for b in doc.blocks if b.type == 'heading']
    assert all(item['id'] in {b.id for b in doc.blocks} for item in context.outline)


def test_structurally_weak_focus_enters_broad_mode_and_expands():
    doc = document([(f'Region {i}', [('paragraph', f'Original contiguous material {i}. ' * 8, {})]) for i in range(20)])
    context = select_source_context(doc, 'unmatched exotic mechanism', 'students', max_chars=6000)
    assert context.mode == 'broad'
    assert context.coverage['focus_region_present'] is False
    assert len({b.section for b in context.blocks}) >= 4
    assert 'broad_expansion' in context.stages


def test_serialized_context_and_prompt_overhead_respect_budget():
    context = select_source_context(sample_source(), 'stability condition eta L', 'students', max_chars=4000, prompt_overhead_chars=800)
    serialized = json.dumps(source_context_payload(context), ensure_ascii=False, separators=(',', ':'))
    assert len(serialized) + 800 <= 4000
    assert context.coverage['truncation_occurred']
    assert all(b.text == next(original.text for original in sample_source().blocks if original.id == b.id) for b in context.blocks)


def test_raw_source_and_structural_metadata_preserved():
    raw = '# 2 Convergence\n\nRule and original text.\n\n$$eta < 2/L$$'
    doc = resolve_source(Case(source_url='citation', focus='stability', audience='students', excerpt=raw))
    normalize_source(doc)
    assert doc.raw_text == raw
    assert doc.raw_source == raw
    assert doc.blocks
    assert doc.structural_map['sections'][0]['title'] == '2 Convergence'
    assert doc.structural_map['sections'][0]['section_number'] == '2'
    assert doc.structural_map['sections'][0]['block_ids'] == [b.id for b in doc.blocks]


def test_generation_metadata_does_not_extend_ir_schema():
    doc = sample_source()
    context = select_source_context(doc, 'stability', 'students', max_chars=6500)
    schema = {'type': 'object', 'properties': {'schema_version': {'const': '1.0'}}}
    messages = build_generation_messages(Case(source_url='paper', focus='stability', audience='students'), context, schema)
    payload = json.loads(messages[1]['content'])
    assert payload['SOURCE_CONTEXT']['coverage'] == context.coverage
    assert payload['SOURCE_CONTEXT']['outline'] == context.outline
    assert 'evidence_assessment' not in json.loads(messages[0]['content'].split('CONTRACT\n')[1])['OUTPUT_SCHEMA']['properties']


def test_dependency_closure_has_depth_limit():
    doc = document([
        ('Convergence', [('paragraph', 'Stability follows Eq. (1).', {})]),
        ('First relationship', [('equation', 'x = y; see Eq. (2)', {'equation_number': '1'})]),
        ('Second relationship', [('equation', 'y = z; see Eq. (3)', {'equation_number': '2'})]),
        ('Third relationship', [('equation', 'z = 4', {'equation_number': '3'})]),
        ('Long appendix', [('paragraph', 'Unrelated. ' * 3000, {})]),
    ])
    context = build_focus_context(doc, 'stability', 'students', max_chars=3500)
    assert context.metadata['dependency_depth'] <= 2
    assert context.metadata['resolved_references'] >= 2
    assert context.mode == 'broad'
    assert 'broad_expansion' in context.stages
    assert any(b.equation_number == '3' for b in context.blocks)


def test_reference_dependency_can_pull_a_new_symbol_definition():
    doc = document([
        ('Convergence', [('paragraph', 'Stability follows Eq. (1).', {})]),
        ('Equation context', [('equation', 'step < kappa', {'equation_number': '1'})]),
        ('Symbols', [('paragraph', 'Let kappa be the curvature threshold.', {})]),
        ('Measurements', [('paragraph', 'Unrelated. ' * 3000, {})]),
    ])
    context = build_focus_context(doc, 'stability', 'students', max_chars=4000)
    assert any('Let kappa be' in b.text for b in context.blocks)
    assert context.metadata['resolved_definitions'] >= 1


def test_actual_generation_prompt_with_schema_and_registry_is_bounded():
    case = Case(source_url='paper', focus='stability', audience='students')
    schema = {'type': 'object', 'properties': {'schema_version': {'const': '1.0'}}}
    overhead = generation_prompt_overhead(case, schema)
    limit = overhead + 2000
    context = select_source_context(sample_source(), case.focus, case.audience,
                                    max_chars=limit, prompt_overhead_chars=overhead)
    messages = build_generation_messages(case, context, schema, max_prompt_chars=limit)
    assert sum(len(m['content']) for m in messages) <= limit


def test_unrelated_definition_does_not_displace_explicit_equation_reference():
    doc = document([
        ('Core', [('paragraph', 'We prove stability using Eq. (7).', {})]),
        ('Other', [('paragraph', 'We define nonsense as an unrelated symbol. ' + 'Measurement filler. ' * 55, {})]),
        ('Rule', [('equation', 'eta < 2 / L. ' + 'Relevant equation context. ' * 12, {'equation_number': '7'})]),
        ('Appendix', [('paragraph', 'Unrelated. ' * 3000, {})]),
    ])
    context = build_focus_context(doc, 'stability', 'students', max_chars=2200)
    assert any(b.equation_number == '7' for b in context.blocks)
    assert not any('We define nonsense' in b.text for b in context.blocks)
