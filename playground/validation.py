"""Observable scientific/interaction checks, not semantic proof of paper claims."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Iterable

import numpy as np
from pydantic import ValidationError

from .computation import ComputationError, derive_dependencies, evaluate, graph_order, validate_control_value
from .models import (AssertionSpec, ControlSpec, DerivedPlayground, ExpectationSpec,
                     ExperienceSpec, PaperMechanismIR, SourceBlock, ValidationFailure, ValidationResult)

VISUAL_TYPES = {'formula', 'number', 'table', 'matrix', 'heatmap', 'bar_chart', 'line_chart',
                'scatter', 'vector', 'pipeline', 'nodes_edges', 'scene'}
NON_TABLE = {'heatmap', 'bar_chart', 'line_chart', 'scatter', 'vector', 'pipeline', 'nodes_edges', 'scene'}
COMPONENT_IDS = frozenset({'teaching', 'idea', 'why', 'mental_model', 'symbols', 'controls',
                           'main_visual', 'equation', 'intermediates', 'what_changed',
                           'explorations', 'limitation', 'source_grounding'})


def derive_visual_ids(spec: PaperMechanismIR) -> list[str]:
    """Stable IDs without changing fixtures; explicit IDs take precedence."""
    reserved = {v.id for v in spec.visuals if v.id}
    used, result = set(), []
    for i, visual in enumerate(spec.visuals):
        candidate = visual.id or f'visual_{i}'
        base, suffix = candidate, 1
        while candidate in used or (visual.id is None and candidate in reserved):
            candidate = f'{base}_{suffix}'
            suffix += 1
        used.add(candidate)
        result.append(candidate)
    return result


def resolve_experience(spec: PaperMechanismIR) -> tuple[ExperienceSpec | None, list[dict]]:
    """Resolve references only. A malformed/ambiguous plan uses canonical layout."""
    issues = list(spec._experience_issues)
    experience = spec.experience
    nodes = {n.id for n in spec.computation.nodes}
    controls = {c.id for c in spec.controls}
    visual_ids = derive_visual_ids(spec)
    explicit = [v.id for v in spec.visuals if v.id]
    duplicate_visual_ids = len(explicit) != len(set(explicit))
    if duplicate_visual_ids:
        issues.append({'path': 'visuals', 'message': 'Duplicate visual IDs were deterministically disambiguated'})
    if experience is None:
        return None, issues
    valid_targets = nodes | controls | set(visual_ids) | COMPONENT_IDS
    ambiguous = (nodes | controls) & (set(visual_ids) | COMPONENT_IDS)
    if duplicate_visual_ids:
        issues.append({'path': 'experience', 'message': 'Experience references are ambiguous because visual IDs repeat'})
    if experience.hero_visual and experience.hero_visual not in visual_ids:
        issues.append({'path': 'experience.hero_visual', 'message': 'Hero must reference an existing visual ID'})
    for field in ('calculation_order', 'emphasis_nodes'):
        values = getattr(experience, field)
        if len(values) != len(set(values)):
            issues.append({'path': f'experience.{field}', 'message': 'Duplicate node references'})
        for i, value in enumerate(values):
            if value not in nodes:
                issues.append({'path': f'experience.{field}.{i}', 'message': f'Unknown computation node: {value}'})
    for field in ('guided_mode', 'annotations'):
        for i, item in enumerate(getattr(experience, field)):
            if item.target not in valid_targets or item.target in ambiguous:
                issues.append({'path': f'experience.{field}.{i}.target', 'message': f'Unknown or ambiguous target: {item.target}'})
    return (None if issues else experience), issues


def _schema_path(location: tuple) -> str:
    """Remove synthetic discriminated-union tags while retaining actual keys."""
    parts = []
    for i, part in enumerate(location):
        if (i >= 2 and isinstance(location[i-1], int) and location[i-2] == 'inputs'
                and part in {'ref', 'const', 'op'}):
            continue
        parts.append(str(part))
    return '.'.join(parts)


def _repair_scopes(check: str, path: str | None, spec: PaperMechanismIR | None) -> list[str]:
    """Offer related repair containers, without opening unrelated valid fields."""
    if not path or path.startswith('schema_version'):
        return []
    parts = path.split('.')
    if parts[0] in {'controls', 'visuals', 'tests', 'invariants', 'explorations', 'evidence', 'symbols'}:
        container = '.'.join(parts[:2]) if len(parts) > 1 and parts[1].isdigit() else parts[0]
    elif parts[:2] == ['computation', 'nodes'] and len(parts) > 2 and parts[2].isdigit():
        container = '.'.join(parts[:3])
    else:
        container = path
    paths = {container}
    if spec is None:
        return sorted(paths)
    target_ids: set[str] = set()
    if len(parts) > 1 and parts[1].isdigit():
        index = int(parts[1])
        if parts[0] == 'controls' and index < len(spec.controls):
            target_ids.add(spec.controls[index].id)
        elif parts[0] == 'tests' and index < len(spec.tests):
            target_ids.update(a.value for a in spec.tests[index].assertions if a.value)
        elif parts[0] == 'invariants' and index < len(spec.invariants):
            target_ids.add(spec.invariants[index].value)
        elif parts[0] == 'explorations' and index < len(spec.explorations):
            exploration = spec.explorations[index]
            target_ids.update(exploration.change.suggested_values)
            if exploration.expectation:
                target_ids.add(exploration.expectation.value)
    if target_ids:
        try:
            dependencies = derive_dependencies(spec)
            related = set(target_ids)
            for target in target_ids:
                related.update(dependencies.get(target, []))
                related.update(source for source, downstream in dependencies.items() if target in downstream)
            for i, node in enumerate(spec.computation.nodes):
                if node.id in related:
                    paths.add(f'computation.nodes.{i}')
        except ComputationError:
            pass
    return sorted(paths)


def visible_nodes(spec: PaperMechanismIR) -> set[str]:
    ids = set(spec.computation.outputs) | {n.id for n in spec.computation.nodes if n.display}
    for visual in spec.visuals:
        if visual.value:
            ids.add(visual.value)
        ids.update(visual.bindings.values())
    return ids


def changed_values(a: dict, b: dict, tolerance: float = 1e-9) -> set[str]:
    changed = set()
    for name in a.keys() & b.keys():
        av, bv = np.asarray(a[name]), np.asarray(b[name])
        if av.shape != bv.shape:
            changed.add(name)
        elif av.dtype.kind in 'iuf' and bv.dtype.kind in 'iuf':
            if not np.allclose(av, bv, atol=tolerance, rtol=tolerance):
                changed.add(name)
        elif not np.array_equal(av, bv):
            changed.add(name)
    return changed


def boundary_values(control: ControlSpec) -> list[Any]:
    """Vary one editor element at a time; avoid invented all-zero vector states."""
    candidates: list[Any] = []
    if control.type == 'checkbox':
        candidates = [False, True]
    elif control.type == 'select':
        candidates = (control.options or [])[:32]
    elif control.value_kind in {'scalar', 'vector', 'matrix', 'sequence'}:
        default = np.asarray(control.default, dtype=float)
        flat = default.reshape(-1)
        for i in range(min(flat.size, 16)):
            v = flat[i]
            delta = control.step or max(abs(float(v)) * 0.1, 0.1)
            choices = [control.min, control.max, float(v) - delta, float(v) + delta]
            for choice in choices:
                if choice is None:
                    continue
                if control.min is not None and choice < control.min:
                    continue
                if control.max is not None and choice > control.max:
                    continue
                candidate = default.copy()
                candidate.reshape(-1)[i] = choice
                candidates.append(candidate.tolist())
    result = [deepcopy(control.default)]
    for value in candidates:
        if value not in result:
            result.append(value)
    return result


def check_assertion(assertion: AssertionSpec, values: dict, value_id: str | None = None) -> bool:
    name = assertion.value or value_id
    if name not in values:
        raise ComputationError(f'Assertion references unknown value: {name}')
    a = np.asarray(values[name])
    op, target, tol = assertion.op, assertion.expected, assertion.tolerance
    if op == 'equals':
        return bool(np.array_equal(a, np.asarray(target)))
    if op == 'shape_equals':
        return list(a.shape) == target
    if a.dtype.kind not in 'iuf':
        raise ComputationError(f'{op}: numeric assertion requires numeric value')
    if op == 'all_finite':
        return bool(np.all(np.isfinite(a)))
    if op == 'nonnegative':
        return bool(np.all(a >= -tol))
    if op == 'approx':
        t = np.asarray(target)
        return a.shape == t.shape and bool(np.allclose(a, t, atol=tol, rtol=0))
    if op in {'greater_than', 'greater_equal', 'less_than', 'less_equal'}:
        t = np.asarray(target)
        if t.ndim and a.shape != t.shape:
            return False
        comparisons = {'greater_than': np.greater, 'greater_equal': np.greater_equal,
                       'less_than': np.less, 'less_equal': np.less_equal}
        return bool(np.all(comparisons[op](a, t)))
    if op == 'sum_to':
        return bool(np.isclose(np.sum(a), target, atol=tol, rtol=0))
    if op == 'rows_sum_to':
        return a.ndim == 2 and bool(np.allclose(np.sum(a, axis=1), target, atol=tol, rtol=0))
    if op == 'range':
        if assertion.min is not None and assertion.max is not None:
            low, high = assertion.min, assertion.max
        elif isinstance(target, list) and len(target) == 2:
            low, high = target
        else:
            raise ComputationError('range assertion needs min/max or expected [min,max]')
        return bool(np.all((a >= low - tol) & (a <= high + tol)))
    if op == 'monotonic':
        if a.ndim != 1:
            return False
        diff = np.diff(a)
        return bool(np.all(diff >= -tol) if assertion.direction == 'increasing' else np.all(diff <= tol))
    if op == 'argmax_equals':
        return a.size > 0 and int(np.argmax(a)) == target
    raise ComputationError(f'Unknown assertion: {op}')


def check_expectation(expectation: ExpectationSpec, baseline: dict, values: dict) -> bool:
    name = expectation.value
    if name not in baseline or name not in values:
        raise ComputationError(f'Unknown expectation value: {name}')
    a, b = np.asarray(baseline[name]), np.asarray(values[name])
    kind, tol = expectation.type, expectation.tolerance
    if kind in {'increases', 'decreases'}:
        if a.shape != b.shape or a.size == 0:
            return False
        return bool(np.all(b > a + tol) if kind == 'increases' else np.all(b < a - tol))
    if kind == 'becomes_uniform':
        return b.size > 0 and bool(np.allclose(b, b.flat[0], atol=tol, rtol=0))
    if kind == 'argmax_changes':
        return a.size > 0 and b.size > 0 and int(np.argmax(a)) != int(np.argmax(b))
    return check_assertion(AssertionSpec(op=kind, value=name, expected=expectation.expected, tolerance=tol), values)


def validate_spec(spec: PaperMechanismIR | dict, source_blocks: Iterable[SourceBlock | dict] | None = None,
                  trace: Callable[[str, str, dict], None] | None = None) -> ValidationResult:
    failures: list[ValidationFailure] = []
    warnings: list[ValidationFailure] = []
    checks: list[dict] = []
    summary = {'scientific': {}, 'teaching': {}, 'visual': {}, 'interaction': {}}
    parsed_spec: PaperMechanismIR | None = None

    def record(check, passed, details=None):
        event = {'check': check, 'passed': bool(passed), 'details': details or {}}
        checks.append(event)
        if trace:
            trace('validation', check, event)

    def issue(check, path, message, severity='serious'):
        allowed_paths = _repair_scopes(check, path, parsed_spec) if severity == 'serious' else []
        repairable = severity == 'serious' and bool(allowed_paths)
        item = ValidationFailure(check=check, severity=severity, path=path, message=message,
                                 repairable=repairable, allowed_paths=allowed_paths)
        (warnings if severity in {'warning', 'recoverable'} else failures).append(item)
        record(check, False, {'path': path, 'message': message, 'severity': severity})

    def result():
        return ValidationResult(ok=not failures, failures=failures, warnings=warnings,
                                rubric_summary=summary, checks=checks)

    try:
        optional_issues = list(spec._experience_issues) if isinstance(spec, PaperMechanismIR) else []
        spec = PaperMechanismIR.model_validate(spec.model_dump() if isinstance(spec, PaperMechanismIR) else spec)
        spec._experience_issues.extend(optional_issues)
        parsed_spec = spec
    except ValidationError as exc:
        for error in exc.errors(include_input=False, include_context=False):
            issue('schema', _schema_path(error['loc']), error['msg'])
        return result()
    record('schema', True)
    resolved_experience, experience_issues = resolve_experience(spec)
    for optional_issue in experience_issues:
        issue('experience_fallback', optional_issue['path'], optional_issue['message'], 'recoverable')
    record('experience_references', not experience_issues,
           {'canonical_layout': resolved_experience is None})
    if len({c.id for c in spec.controls}) != len(spec.controls):
        issue('unique_controls', 'controls', 'Duplicate control IDs')
    if len({e.id for e in spec.evidence}) != len(spec.evidence):
        issue('unique_evidence', 'evidence', 'Duplicate evidence IDs')
    blocks = None
    if source_blocks is not None:
        try:
            source = [SourceBlock.model_validate(b) for b in source_blocks]
            blocks = {b.id for b in source}
            if len(blocks) != len(source):
                issue('source_blocks', None, 'Duplicate source block IDs', 'fatal')
        except ValidationError as exc:
            issue('source_blocks', None, str(exc), 'fatal')
            return result()
    else:
        issue('source_blocks', None, 'Source blocks not supplied; evidence references are not verified', 'warning')
    if not spec.evidence:
        issue('grounding', 'evidence', 'At least one source-supported claim is required')
    for i, claim in enumerate(spec.evidence):
        if blocks is not None and set(claim.blocks) - blocks:
            issue('grounding', f'evidence.{i}', 'Claim references missing source blocks')
    node_ids = {n.id for n in spec.computation.nodes}
    grounded = set()
    if not spec.mechanism_grounding:
        issue('mechanism_grounding', 'mechanism_grounding', 'Executable mechanism must link to source evidence')
    for i, item in enumerate(spec.mechanism_grounding):
        if set(item.nodes) - node_ids or (blocks is not None and set(item.blocks) - blocks):
            issue('mechanism_grounding', f'mechanism_grounding.{i}', 'Grounding references missing nodes or source blocks')
        else:
            grounded.update(item.nodes)
    summary['scientific'].update(grounding_present=bool(spec.evidence), source_references_verified=blocks is not None,
                                 mechanism_grounding_present=bool(spec.mechanism_grounding),
                                 simplifications_labeled=bool(spec.provenance.simplifications or spec.provenance.toy_examples))
    if not spec.symbols:
        issue('symbols', 'symbols', 'Symbols must be defined')
    summary['teaching'].update(idea_present=True, symbols_defined=bool(spec.symbols))
    try:
        _, refs = graph_order(spec.computation, {c.id for c in spec.controls})
        defaults = evaluate(spec)
        dependencies = derive_dependencies(spec)
        record('graph_types_shapes_execution', True)
        summary['scientific']['computation_executes'] = True
    except (ComputationError, ValueError, TypeError) as exc:
        issue('computation', 'computation', str(exc))
        summary['scientific']['computation_executes'] = False
        return result()
    for output in spec.computation.outputs:
        ancestors = {output} | {n for n, downstream in dependencies.items() if output in downstream}
        if not ancestors & grounded:
            issue('mechanism_grounding', 'mechanism_grounding', f'Output {output} has no grounded mechanism path')
    uncovered = node_ids - grounded
    if uncovered:
        issue('grounding_coverage', 'mechanism_grounding', f'Nodes without direct grounding: {sorted(uncovered)}', 'warning')
    known = set(defaults)
    visual_ok = True
    valid_visuals = []
    for i, visual in enumerate(spec.visuals):
        targets = set(visual.bindings.values()) | ({visual.value} if visual.value else set())
        if targets - known:
            issue('visual_bindings', f'visuals.{i}', f'Unknown bindings: {sorted(targets-known)}; use deterministic visual fallback', 'recoverable')
            visual_ok = False
        if visual.type not in VISUAL_TYPES:
            issue('visual_fallback', f'visuals.{i}', f'Unsupported visual {visual.type}; renderer must use dependency diagram + supporting values', 'recoverable')
        if visual.type not in {'formula', 'scene'} and not targets:
            issue('visual_bindings', f'visuals.{i}', 'Visual has no computation binding; use deterministic visual fallback', 'recoverable')
            visual_ok = False
        if targets and not targets - known:
            valid_visuals.append(visual)
    meaningful = any(v.type in NON_TABLE for v in valid_visuals)
    if not meaningful:
        issue('visual_fallback', 'visuals', 'Renderer must add a computation/dependency diagram; table/number/formula alone is insufficient', 'recoverable')
    summary['visual'].update(bindings_valid=visual_ok, meaningful_non_table_visual=meaningful,
                              requested_non_table_visual=meaningful,
                              requires_fallback=not meaningful or not visual_ok or any(v.type not in VISUAL_TYPES for v in spec.visuals))
    visible = visible_nodes(spec) & known
    # An echoed control alone does not establish a working computed mechanism.
    visible_computed = visible & node_ids
    verification_ok = True

    def invariants(values, scenario):
        nonlocal verification_ok
        for i, inv in enumerate(spec.invariants):
            try:
                if inv.assertion.value and inv.assertion.value != inv.value:
                    raise ComputationError('Invariant and assertion targets differ')
                passed = check_assertion(inv.assertion, values, inv.value)
                record('invariant', passed, {'name': inv.name, 'scenario': scenario})
                if not passed:
                    issue('invariant', f'invariants.{i}', f'{inv.name} failed in {scenario}')
                    verification_ok = False
            except (ValueError, TypeError) as exc:
                issue('invariant', f'invariants.{i}', str(exc))
                verification_ok = False

    invariants(defaults, 'defaults')
    for i, test in enumerate(spec.tests):
        try:
            values = evaluate(spec, test.inputs)
            for j, assertion in enumerate(test.assertions):
                passed = check_assertion(assertion, values)
                record('test_case', passed, {'name': test.name, 'assertion': j})
                if not passed:
                    issue('test_case', f'tests.{i}', f'{test.name}: assertion {j} failed')
                    verification_ok = False
            invariants(values, test.name)
        except (ValueError, TypeError) as exc:
            issue('test_case', f'tests.{i}', str(exc))
            verification_ok = False
    all_influence, boundaries_ok = True, True
    if len(spec.controls) < 2:
        issue('control_count', 'controls', 'At least two meaningful controls are required')
        all_influence = False
    for i, control in enumerate(spec.controls):
        affected, changed_visible = set(), set()
        for value in boundary_values(control):
            try:
                values = evaluate(spec, {control.id: value})
                changed = changed_values(defaults, values) & set(dependencies[control.id])
                affected |= changed
                changed_visible |= changed & visible_computed
                invariants(values, f'control {control.id}={value}')
            except (ValueError, TypeError) as exc:
                issue('control_boundary', f'controls.{i}', f'{control.id}={value}: {exc}')
                boundaries_ok = False
        if not affected:
            issue('control_influence', f'controls.{i}', f'{control.id} does not change downstream calculations')
            all_influence = False
        if not changed_visible:
            issue('control_visible_influence', f'controls.{i}', f'{control.id} does not change visible computed values')
            all_influence = False
        record('control_influence', bool(changed_visible), {'control': control.id, 'changed_outputs': sorted(affected),
                                                         'visible_changes': sorted(changed_visible)})
    valid_explorations = 0
    if len(spec.explorations) < 2:
        issue('exploration_count', 'explorations', 'Two guided explorations are required')
    for i, exploration in enumerate(spec.explorations):
        try:
            values = evaluate(spec, exploration.change.suggested_values)
            changes = changed_values(defaults, values) & visible_computed
            if not changes:
                raise ComputationError('Exploration does not change any visible computed value')
            if exploration.expectation and not check_expectation(exploration.expectation, defaults, values):
                raise ComputationError('Structured exploration expectation failed')
            invariants(values, exploration.title)
            valid_explorations += 1
            record('exploration', True, {'title': exploration.title, 'visible_changes': sorted(changes)})
        except (ValueError, TypeError) as exc:
            issue('exploration', f'explorations.{i}', str(exc))
    summary['scientific']['verification_passed'] = verification_ok
    summary['interaction'].update(control_count=len(spec.controls), all_controls_affect_visible_output=all_influence,
                                  boundary_tests_pass=boundaries_ok)
    summary['teaching']['explorations_valid'] = valid_explorations
    record('rubric_summary', not failures, summary)
    return result()


def derive_playground(spec: PaperMechanismIR | dict, source_blocks=None) -> DerivedPlayground:
    spec = spec if isinstance(spec, PaperMechanismIR) else PaperMechanismIR.model_validate(spec)
    # Derivation preserves executable candidates; the orchestrator decides whether
    # the validation report permits success, repair, or best-so-far retention.
    defaults = evaluate(spec)
    validation = validate_spec(spec, source_blocks)
    experience, _ = resolve_experience(spec)
    return DerivedPlayground(spec=spec, dependency_graph=derive_dependencies(spec), evaluated_defaults=defaults,
                             visible_nodes=visible_nodes(spec) & set(defaults), rubric_summary=validation.rubric_summary,
                             validation=validation, visual_ids=derive_visual_ids(spec), resolved_experience=experience)
