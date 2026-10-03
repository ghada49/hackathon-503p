"""Adaptive full-source or progressive structural context, without semantic summaries."""
from __future__ import annotations

import math
import re
from collections import Counter
import json
from typing import Any, Literal
from pydantic import Field

from playground.source import FocusedEvidence, SourceBlock, SourceDocument, build_structural_map, normalize_source

MAX_DEPENDENCY_DEPTH = 2
DEFAULT_CONTEXT_CHARS = 24000
_DEFINITION = re.compile(r'\b(?:where\s+\S+\s+denotes|we\s+define|let\s+\S+\s+be|is\s+defined\s+as)\b', re.I)
_LIMITATION = re.compile(r'\b(?:assumptions?|limitations?|limitations|caveat|only\s+valid|requires?|under)\b', re.I)
_REFERENCE = re.compile(r'\b(Eq\.?|Equation|Section|Algorithm)\s*\(?([0-9]+(?:\.[0-9]+)*)\)?', re.I)


class FocusContext(FocusedEvidence):
    """Source proposal metadata stays outside the authoritative PaperMechanismIR."""
    mode: Literal['full', 'focused', 'broad'] = 'full'
    outline: list[dict[str, Any]] = Field(default_factory=list)
    coverage: dict[str, bool | None] = Field(default_factory=dict)
    stages: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def source_context_payload(context: FocusedEvidence) -> dict:
    payload = {'SOURCE_BLOCKS': [b.model_dump(mode='json', exclude_none=True) for b in context.blocks]}
    if isinstance(context, FocusContext):
        payload['SOURCE_CONTEXT'] = dict(mode=context.mode, outline=context.outline, coverage=context.coverage)
    return payload


def _size(context: FocusContext) -> int:
    return len(json.dumps(source_context_payload(context), ensure_ascii=False, allow_nan=False, separators=(',', ':')))


def _coverage(**updates) -> dict:
    flags = dict(full_source_included=False, focus_region_present=False, neighboring_context_present=False,
                 nearby_equations_algorithms_present=False, referenced_material_resolved=False,
                 definitions_found=False, limitations_context_found=False, truncation_occurred=False)
    flags.update(updates)
    return flags


def _prepare(document: SourceDocument):
    if not document.blocks:
        normalize_source(document)
    if not document.structural_map:
        document.structural_map = build_structural_map(document.blocks)
    return document.blocks


def select_source_context(document: SourceDocument, focus: str, audience: str, *,
                          max_chars: int = DEFAULT_CONTEXT_CHARS, prompt_overhead_chars: int = 0,
                          comfort_ratio: float = 0.85) -> FocusContext:
    """Bypass ranking entirely when complete serialized source comfortably fits."""
    if not 0 < comfort_ratio <= 1 or max_chars <= prompt_overhead_chars:
        raise ValueError('Prompt context budget must leave room for source data')
    blocks = _prepare(document)
    full = FocusContext(blocks=blocks, focus=focus, audience=audience, mode='full',
        coverage=_coverage(full_source_included=document.metadata.get('extraction_faithful', True), focus_region_present=None,
            neighboring_context_present=None, nearby_equations_algorithms_present=any(b.type in ('equation', 'algorithm') for b in blocks),
            referenced_material_resolved=None, definitions_found=any(_DEFINITION.search(b.text) for b in blocks),
            limitations_context_found=any(_LIMITATION.search(b.text) for b in blocks)), stages=['full_source'])
    if _size(full) <= (max_chars - prompt_overhead_chars) * comfort_ratio:
        return full
    return build_focus_context(document, focus, audience, max_chars=max_chars,
                               prompt_overhead_chars=prompt_overhead_chars)

_GROUPS = (
    {'stability', 'stable', 'convergence', 'converge', 'converges', 'convergent'},
    {'condition', 'conditions', 'criterion', 'criteria', 'bound', 'bounded'},
    {'optimization', 'optimisation', 'minimization', 'minimisation'},
    {'probability', 'probabilities', 'probabilistic'},
)
_STOP = {'a', 'an', 'the', 'of', 'in', 'to', 'and', 'for', 'is', 'on', 'with'}


def _tokens(text: str) -> list[str]:
    return [word for word in re.findall(r'[a-z0-9]+', text.lower()) if word not in _STOP]


def build_focus_context(document: SourceDocument, focus: str, audience: str, *,
                        max_chars: int = DEFAULT_CONTEXT_CHARS, prompt_overhead_chars: int = 0,
                        max_dependency_depth: int = MAX_DEPENDENCY_DEPTH) -> FocusContext:
    """Rank regions, then progressively close structural dependencies within budget.

    All included text is original. Coverage describes structural cues, never
    scientific completeness or semantic entailment. No fixed top-N block rule.
    """
    available = max_chars - prompt_overhead_chars
    if available <= 0:
        raise ValueError('Prompt context budget must leave room for source data')
    blocks = _prepare(document)
    if not blocks:
        raise ValueError('No source blocks to retrieve')
    indices = {b.id: i for i, b in enumerate(blocks)}
    regions = document.structural_map['sections']
    region_blocks = [[indices[block_id] for block_id in region['block_ids']] for region in regions]
    region_for = {i: r for r, group in enumerate(region_blocks) for i in group}
    query = set(_tokens(focus))
    for group in _GROUPS:
        if query & group:
            query |= group
    counts = [Counter(_tokens(' '.join(blocks[i].text for i in group))) for group in region_blocks]
    df = Counter(token for count in counts for token in count)
    matches = [query & set(count) for count in counts]
    scores = [sum((1 + math.log(c[t])) * math.log(1 + len(regions) / df[t]) for t in query if c[t])
              + 4 * len(query & set(_tokens(region['title'])))
              + (min(2, sum(blocks[i].type in ('equation', 'algorithm') for i in group)) * 0.5 if matches[r] else 0)
              for r, (region, group, c) in enumerate(zip(regions, region_blocks, counts))]
    ranked = sorted(range(len(regions)), key=lambda r: (-scores[r], r))
    primary = ranked[0]
    selected: set[int] = set()
    outline = []
    stages = ['orientation', 'core_regions']

    def proposal(picks, proposed_outline=None):
        return FocusContext(blocks=[blocks[i] for i in sorted(picks)], focus=focus, audience=audience,
            mode='focused', outline=outline if proposed_outline is None else proposed_outline, coverage=_coverage())

    def add_group(group, *, limit=None):
        combined = selected | set(group)
        if _size(proposal(combined)) <= (available if limit is None else limit):
            selected.update(group)
            return True
        return False

    # The outline contains verbatim headings. Its own bounded allocation leaves room for science.
    for block in blocks:
        if block.type != 'heading':
            continue
        item = dict(id=block.id, title=block.text)
        if block.section_number:
            item['section_number'] = block.section_number
        trial = outline + [item]
        outline_cost = len(json.dumps(trial, ensure_ascii=False, separators=(',', ':')))
        if outline_cost <= available * 0.15 and _size(proposal(set(), trial)) < available * 0.45:
            outline = trial

    core_regions = []
    for r in ranked:
        if r != primary and (not matches[r] or scores[r] < scores[primary] * 0.55):
            continue
        group = region_blocks[r]
        if add_group(group, limit=available * 0.65):
            core_regions.append(r)
            continue
        if r != primary:
            continue
        # For an oversized section, retain a coherent region around its best lexical anchor.
        anchor = max(group, key=lambda i: (len(query & set(_tokens(blocks[i].text))), blocks[i].type != 'heading', -i))
        heading = group[0] if blocks[group[0]].type == 'heading' else None
        if not add_group([anchor]):
            continue
        if heading is not None:
            add_group([heading])
        core_regions.append(r)
        for i in group:
            if blocks[i].type in ('equation', 'algorithm') and abs(i - anchor) <= 5:
                add_group([i], limit=available * 0.8)

    core_picks = set(selected)
    if selected:
        # Cheap prerequisite/definition cues are followed only when linked to core vocabulary.
        vocabulary = query | set(_tokens(' '.join(blocks[i].text for i in core_picks)))
        definition_ids = {block_id for symbol, block_ids in document.structural_map.get('definitions', {}).items()
                          if symbol in vocabulary for block_id in block_ids}
        for i, block in enumerate(blocks):
            if block.id in definition_ids:
                r = region_for[i]
                if not add_group(region_blocks[r]):
                    add_group([region_blocks[r][0], i])
        if any(_DEFINITION.search(blocks[i].text) for i in selected):
            stages.append('definitions_prerequisites')

    reference_index = {}
    for number, block_id in document.structural_map['equations'].items():
        reference_index[('equation', number)] = [indices[block_id]]
    for number, block_id in document.structural_map['algorithms'].items():
        reference_index[('algorithm', number)] = [indices[block_id]]
    for r, region in enumerate(regions):
        if region['section_number']:
            reference_index[('section', region['section_number'])] = region_blocks[r]

    def refs(picks):
        return {('equation' if kind.lower().startswith('eq') else kind.lower(), number)
                for i in picks for kind, number in _REFERENCE.findall(blocks[i].text)}

    depth = 0
    seen_refs = set()
    seen_symbols = set()
    resolved_definitions = set()
    unresolved = set()
    frontier = set(selected)
    for level in range(min(MAX_DEPENDENCY_DEPTH, max(0, max_dependency_depth))):
        detected = refs(frontier) - seen_refs
        symbols = set(_tokens(' '.join(blocks[i].text for i in frontier))) & set(document.structural_map.get('definitions', {}))
        symbols -= seen_symbols
        if not detected and not symbols:
            break
        if detected and 'cross_reference_closure' not in stages:
            stages.append('cross_reference_closure')
        seen_refs.update(detected)
        seen_symbols.update(symbols)
        previous = set(selected)
        for symbol in sorted(symbols):
            target = [indices[block_id] for block_id in document.structural_map['definitions'][symbol]]
            for i in target:
                r = region_for[i]
                if not add_group(region_blocks[r]):
                    add_group([region_blocks[r][0], i])
            if set(target).issubset(selected):
                resolved_definitions.add(symbol)
                if 'definitions_prerequisites' not in stages:
                    stages.append('definitions_prerequisites')
        for reference in sorted(detected):
            target = reference_index.get(reference)
            if not target:
                unresolved.add(reference)
                continue
            r = region_for[target[0]]
            if not add_group(region_blocks[r]):
                add_group([region_blocks[r][0], *target])
            if not set(target).issubset(selected):
                unresolved.add(reference)
        frontier = selected - previous
        depth = level + 1

    partial_core = any(not set(region_blocks[r]).issubset(selected) for r in core_regions)
    if partial_core or unresolved or core_picks and not any(blocks[i].type == 'paragraph' for i in core_picks):
        stages.append('structural_neighbors')
        for i in sorted(core_picks):
            for distance in (1, 2):
                for neighbor in (i - distance, i + distance):
                    if 0 <= neighbor < len(blocks):
                        add_group([neighbor])

    if _LIMITATION.search(focus) or any(_LIMITATION.search(blocks[i].text) for i in core_picks):
        for r, region in enumerate(regions):
            if _LIMITATION.search(region['title']):
                if add_group(region_blocks[r]):
                    if 'limitations_assumptions' not in stages:
                        stages.append('limitations_assumptions')

    focus_present = bool(core_regions and any(matches[r] for r in core_regions))
    # New cues may appear on the final depth frontier or in conditional packs.
    # Depth bounds recursive following, not the subsequent coherent broad expansion.
    detected_now = refs(selected)
    unresolved_now = {reference for reference in detected_now if reference not in reference_index or
                      not set(reference_index[reference]).issubset(selected)}
    broad = not focus_present or bool(unresolved_now) or partial_core
    if broad:
        stages.append('broad_expansion')
        # Spend remaining budget on coherent sections ordered by proximity to the proposed core.
        for r in sorted(range(len(regions)), key=lambda r: (abs(r - primary), -scores[r], r)):
            if add_group(region_blocks[r]):
                continue
            # Expand contiguous prefixes/windows rather than selecting unrelated global paragraphs.
            group = region_blocks[r]
            if not group:
                continue
            if blocks[group[0]].type == 'heading':
                start = [group[0]]
            else:
                start = []
            for i in group:
                trial = start + [i]
                if not add_group(trial):
                    break
                start = trial

    if not selected:
        raise ValueError('No complete source block fits the retrieval context budget; supply a smaller excerpt')
    all_detected = refs(selected)
    resolved = {reference for reference in all_detected if reference in reference_index and set(reference_index[reference]).issubset(selected)}
    coverage = _coverage(full_source_included=len(selected) == len(blocks) and document.metadata.get('extraction_faithful', True), focus_region_present=focus_present,
        neighboring_context_present=focus_present and bool(core_picks) and all(any(j in selected for j in (i - 1, i + 1)) for i in core_picks),
        nearby_equations_algorithms_present=any(blocks[i].type in ('equation', 'algorithm') and
            any(region_for[i] == region_for[j] or abs(i - j) <= 2 for j in core_picks) for i in selected),
        referenced_material_resolved=all_detected.issubset(resolved), definitions_found=any(_DEFINITION.search(blocks[i].text) for i in selected),
        limitations_context_found=any(_LIMITATION.search(blocks[i].text) for i in selected), truncation_occurred=len(selected) < len(blocks))
    context = FocusContext(blocks=[blocks[i] for i in sorted(selected)], focus=focus, audience=audience,
        mode='broad' if broad else 'focused', outline=outline, coverage=coverage, stages=stages,
        metadata=dict(dependency_depth=depth, resolved_references=len(resolved), unresolved_references=len(all_detected - resolved),
                      resolved_definitions=len(resolved_definitions),
                      outline_complete=len(outline) == sum(b.type == 'heading' for b in blocks)))
    if _size(context) > available:
        raise ValueError('Source metadata exceeds prompt context budget')
    return context


def retrieve_focused_evidence(blocks: list[SourceBlock], focus: str, audience: str,
                              *, max_chars: int = DEFAULT_CONTEXT_CHARS) -> FocusContext:
    """Compatibility entry point; full-source bypass uses the same adaptive strategy."""
    if not blocks:
        raise ValueError('No source blocks to retrieve')
    document = SourceDocument(source_url='', origin='supplied', blocks=blocks,
                              structural_map=build_structural_map(blocks))
    return select_source_context(document, focus, audience, max_chars=max_chars)
