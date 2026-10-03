from playground.source import SourceDocument, normalize_source
from playground.retrieval import retrieve_focused_evidence
import pytest
from playground.source import SourceBlock


def test_small_excerpt_kept_whole():
    blocks = normalize_source(SourceDocument(source_url='p', origin='supplied', raw_text='Intro\n\nDetails\n\nOther'))
    result = retrieve_focused_evidence(blocks, 'anything', 'students')
    assert result.blocks == blocks


def test_stability_retrieves_convergence_heading_neighbors_equation():
    parts = [dict(type='paragraph', text='Unrelated material ' * 30, order=i) for i in range(20)]
    parts[8] = dict(type='heading', text='Convergence criterion', order=8)
    parts[9] = dict(type='paragraph', text='The iterative process converges under a bounded step.', order=9)
    parts[10] = dict(type='equation', text='eta < 2 / L', order=10)
    parts[11] = dict(type='paragraph', text='Boundary discussion', order=11)
    for i, part in enumerate(parts):
        part['id'] = f'original{i}'
    blocks = normalize_source(SourceDocument(source_url='p', origin='supplied', blocks=parts))
    result = retrieve_focused_evidence(blocks, 'stability condition', 'students', max_chars=2500)
    orders = [b.order for b in result.blocks]
    assert {8, 9, 10, 11}.issubset(orders)
    assert orders == sorted(orders)
    assert len(orders) < 20


def test_oversized_block_fails_clearly_instead_of_exceeding_budget():
    block = SourceBlock(id='b0', type='paragraph', text='convergence ' + 'x' * 100000, order=0)
    with pytest.raises(ValueError, match='budget'):
        retrieve_focused_evidence([block], 'stability', 'students', max_chars=1000)


def test_large_neighbor_group_does_not_overflow_budget():
    blocks = [SourceBlock(id=f'b{i}', type='paragraph', text='background ' * 60, order=i) for i in range(8)]
    blocks[4] = SourceBlock(id='b4', type='paragraph', text='Convergence criterion', order=4)
    result = retrieve_focused_evidence(blocks, 'stability condition', 'students', max_chars=1000)
    assert any(b.id == 'b4' for b in result.blocks)
    assert sum(len(b.text) for b in result.blocks) <= 1000
