"""Person 1 orchestration over the unchanged, frozen Person 2 scientific APIs."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from pydantic import ValidationError

from playground.budget import BudgetExceeded, call_with_timeout
from playground.generator import (BestSoFar, GenerationFailure, OpenRouterError,
    apply_restricted_patch, generate_spec, initial_missing_schema_version, operand_grammar_locations, repair_spec)
from playground.models import PaperMechanismIR, SourceBlock, ValidationResult, DerivedPlayground
from playground.validation import validate_spec, derive_playground
from playground.generation_contract import catastrophic, compact_violations

PERSON2_FROZEN_SHA = 'e2de90d6a61d84e9add864d1866891f4444e1ddb'


@dataclass
class Assessment:
    spec: PaperMechanismIR | None
    validation: ValidationResult
    derived: DerivedPlayground | None

    @property
    def accepted(self) -> bool:
        return self.validation.ok and self.derived is not None


@dataclass
class CompilationResult:
    spec: PaperMechanismIR | dict | None
    validation: ValidationResult | None
    derived: DerivedPlayground | None
    accepted: bool
    repair_attempted: bool = False
    reason: str | None = None
    resolution: dict | None = None
    candidates: dict = field(default_factory=dict)

    @property
    def status(self):
        return self.resolution['status'] if self.resolution else 'FULL_SUCCESS' if self.accepted else 'UNUSABLE'


def assess_candidate(candidate, source_blocks, *, trace=None, budget=None) -> Assessment:
    """A fresh report and derivation for one isolated, unchanged spec/source snapshot."""
    if budget is not None:
        budget.check_available()
    source = [SourceBlock.model_validate(block.model_dump() if hasattr(block, 'model_dump') else copy.deepcopy(block))
              for block in source_blocks]

    def event(stage, action, result):
        if budget is not None:
            budget.check_available()
        if trace is not None:
            trace.log(stage, action, result)

    def invoke(function):
        if budget is None:
            return function()
        try:
            return call_with_timeout(function, budget.remaining_seconds)
        except BudgetExceeded as exc:
            raise BudgetExceeded('Scientific assessment deadline reached') from exc

    try:
        spec = PaperMechanismIR.model_validate(copy.deepcopy(candidate))
    except ValidationError:
        report = invoke(lambda: validate_spec(copy.deepcopy(candidate), source, trace=event))
        if budget is not None:
            budget.check_available()
        return Assessment(None, report, None)
    report = invoke(lambda: validate_spec(spec, source, trace=event))
    if budget is not None:
        budget.check_available()
    locations = operand_grammar_locations(spec)
    if locations:
        event('generation', 'operand_grammar', dict(locations=locations, authoritative_acceptance=report.ok))
    try:
        # This report belongs to these exact immutable snapshots. There is no cross-call cache.
        derived = invoke(lambda: derive_playground(spec, source, validation=report))
    except (ValueError, TypeError) as exc:
        if trace:
            trace.log('derivation', 'not_executable', dict(error_type=type(exc).__name__, message=str(exc)))
        derived = None
    if budget is not None:
        budget.check_available()
    return Assessment(spec, report, derived)


def resolve_candidate(candidate, source_blocks, *, trace=None, budget=None):
    from playground.resolution import resolve_assessment
    assessment = assess_candidate(candidate, source_blocks, trace=trace, budget=budget)
    return resolve_assessment(assessment, source_blocks, assess=assess_candidate, trace=trace, budget=budget)


def compile_scientific_spec(client, evidence, case, *, operations=None, max_prompt_chars=None) -> CompilationResult:
    """Generate once, use authoritative diagnostics, repair at most once, retain prior best."""
    original = None
    parse_failure = None
    try:
        original = generate_spec(client, evidence, case, ir_model=PaperMechanismIR,
                                 operations=operations, max_prompt_chars=max_prompt_chars)
    except GenerationFailure as exc:
        parse_failure = exc
        original = exc.candidate
    try:
        resolved = resolve_candidate(original if original is not None else {}, evidence.blocks,
                                     trace=client.trace, budget=client.budget)
        assessment = resolved.assessment
    except BudgetExceeded as exc:
        return CompilationResult(copy.deepcopy(original), None, None, False, reason=str(exc))
    best = BestSoFar(assessment.spec if assessment.spec is not None else original, assessment.validation)
    best_derived = copy.deepcopy(assessment.derived)
    best_resolution = copy.deepcopy(resolved.metadata())
    records = {}

    def record(name, candidate, report, disposition):
        raw = candidate.model_dump(mode='json') if hasattr(candidate, 'model_dump') else candidate
        records[name] = dict(candidate=copy.deepcopy(raw),
            validation=report.model_dump(mode='json') if report is not None else None,
            disposition=disposition)
        client.trace.log('candidates', name, dict(disposition=disposition,
                         validation_ok=report.ok if report is not None else None))

    record('initial', original, resolved.reports[0],
           resolved.status if not resolved.actions else 'SUPERSEDED_BY_VALIDATED_CLEANUP')
    regenerate = parse_failure is not None and catastrophic(
        parse_failure.candidate, PaperMechanismIR.model_json_schema(), parse_failure.failures)
    if resolved.accepted and assessment.spec is not None and not compact_violations(assessment.spec.model_dump()):
        regenerate = False  # Preserve existing safe deterministic cleanup of extras.
    if regenerate:
        best_resolution['status'] = 'UNUSABLE'
    # Cleanup may shift list indices; diagnostics and patching use this same new snapshot.
    original = assessment.spec if assessment.spec is not None else original

    def retained(reason, *, attempted=False):
        record('final', best.spec, best.validation, best_resolution['status'])
        return CompilationResult(copy.deepcopy(best.spec), copy.deepcopy(best.validation),
                                 copy.deepcopy(best_derived), False, attempted, reason, copy.deepcopy(best_resolution), records)

    if resolved.accepted and not regenerate:
        client.trace.log('science', 'accepted', dict(validation_ok=True, frozen_sha=PERSON2_FROZEN_SHA))
        record('final', best.spec, best.validation, 'FULL_SUCCESS')
        return CompilationResult(best.spec, best.validation, best_derived, True, resolution=best_resolution, candidates=records)
    if regenerate:
        client.trace.log('regeneration', 'compact_regeneration', dict(reason=str(parse_failure),
                         previous_candidate_included=False))
        try:
            regenerated = generate_spec(client, evidence, case, ir_model=PaperMechanismIR,
                operations=operations, max_prompt_chars=max_prompt_chars, purpose='regeneration',
                regeneration_reason=str(parse_failure))
            trial = resolve_candidate(regenerated, evidence.blocks, trace=client.trace, budget=client.budget)
            fresh = trial.assessment
            record('regenerated', fresh.spec, fresh.validation, trial.status)
            if trial.accepted or trial.status == 'USABLE_PARTIAL':
                best = BestSoFar(fresh.spec, fresh.validation)
                best_derived, best_resolution = copy.deepcopy(fresh.derived), copy.deepcopy(trial.metadata())
                client.trace.log('regeneration', 'promoted', dict(status=trial.status))
            else:
                client.trace.log('regeneration', 'rejected', dict(status=trial.status, best_preserved=True))
            if trial.accepted:
                record('final', best.spec, best.validation, 'FULL_SUCCESS')
                return CompilationResult(best.spec, best.validation, best_derived, True, True,
                                         resolution=best_resolution, candidates=records)
            return retained('Compact regeneration failed scientific/schema or rubric quality requirements', attempted=True)
        except (GenerationFailure, OpenRouterError, BudgetExceeded, ValidationError) as exc:
            if isinstance(exc, GenerationFailure):
                records['regenerated'] = dict(candidate=exc.candidate, validation=dict(ok=False, failures=exc.failures),
                                              disposition='UNUSABLE')
            client.trace.log('regeneration', 'rejected', dict(error_type=type(exc).__name__, reason=str(exc), best_preserved=True))
            return retained('Compact regeneration failed: ' + str(exc), attempted=client.budget.repairs > 0)
    failures = [failure.model_dump(mode='json') for failure in assessment.validation.failures] + resolved.repair_requests
    allowed = sorted({path for failure in assessment.validation.failures if failure.repairable
                      for path in failure.allowed_paths})
    allowed = sorted(set(allowed) | {path for request in resolved.repair_requests for path in request['allowed_paths']})
    empty_candidate = original is None
    if empty_candidate and parse_failure is not None:
        failures = copy.deepcopy(parse_failure.failures)
        allowed = list(parse_failure.allowed_paths)
    else:
        raw = original.model_dump(mode='json') if hasattr(original, 'model_dump') else original or {}
        if initial_missing_schema_version(raw, PaperMechanismIR.model_json_schema()):
            for failure in failures:
                if failure['path'] == 'schema_version':
                    failure.update(repairable=True, allowed_paths=['schema_version'])
                    allowed = sorted(set(allowed) | {'schema_version'})
                    client.trace.log('repair', 'initial_version_scope', dict(expected_version='1.0'))
    if not allowed:
        client.trace.log('repair', 'repair_skipped', dict(reason='no_authorized_scientific_paths'))
        return retained('Scientific/schema or rubric quality requirements remain unmet; no authorized repair paths')
    before_calls = client.budget.repairs
    try:
        client.budget.check_available()
        patch = repair_spec(client, original or {}, failures, allowed, evidence=evidence, case=case,
                            ir_model=PaperMechanismIR, operations=operations,
                            allow_full_regeneration=empty_candidate, max_prompt_chars=max_prompt_chars)
        raw = original.model_dump(mode='json') if hasattr(original, 'model_dump') else original or {}
        candidate = apply_restricted_patch(raw, patch, allowed,
            protected_paths=('source_url', 'audience') if empty_candidate else ('schema_version', 'source_url', 'audience'),
            allow_initial_missing_version=not empty_candidate and 'schema_version' in allowed and
                initial_missing_schema_version(raw, PaperMechanismIR.model_json_schema()), ir_model=PaperMechanismIR)
        # Every changed candidate gets schema validation, a NEW scientific report, and new derivation.
        repaired_resolution = resolve_candidate(candidate, evidence.blocks, trace=client.trace, budget=client.budget)
        repaired = repaired_resolution.assessment
        record('repair', repaired.spec if repaired.spec is not None else candidate, repaired.validation, repaired_resolution.status)
        if compact_violations(candidate):
            client.trace.log('repair', 'rejected', dict(reason='compact_contract', paths=compact_violations(candidate)))
            return retained('Repaired candidate exceeds compact generation bounds', attempted=True)
        if repaired_resolution.accepted:
            best.consider(repaired.spec, repaired.validation, accepted=True)
            best_derived = copy.deepcopy(repaired.derived)
            client.trace.log('repair', 'accepted', dict(validation_ok=True, validation_reused_within_assessment=True))
            record('final', best.spec, best.validation, 'FULL_SUCCESS')
            return CompilationResult(best.spec, best.validation, best_derived, True, True,
                                     resolution=repaired_resolution.metadata(), candidates=records)
        # A usable partial is retained only as an improvement over an unusable original.
        if best_resolution['status'] == 'UNUSABLE' and repaired_resolution.status == 'USABLE_PARTIAL':
            best = BestSoFar(repaired.spec, repaired.validation)
            best_derived = copy.deepcopy(repaired.derived)
            best_resolution = copy.deepcopy(repaired_resolution.metadata())
            client.trace.log('repair', 'partial_retained', dict(status='USABLE_PARTIAL', scientific_acceptance=False))
        client.trace.log('repair', 'rejected', dict(validation_ok=repaired.validation.ok, status=repaired_resolution.status,
            failures=[failure.model_dump(mode='json') for failure in repaired.validation.failures], best_preserved=True))
        return retained('Repaired candidate failed scientific/schema or rubric quality requirements', attempted=True)
    except (GenerationFailure, OpenRouterError, BudgetExceeded, ValidationError) as exc:
        if 'repair' not in records:
            records['repair'] = dict(candidate=getattr(exc, 'candidate', None),
                validation=dict(ok=False, failures=getattr(exc, 'failures', [])),
                disposition='REJECTED', error_type=type(exc).__name__)
        if isinstance(exc, GenerationFailure) and any(f.get('check') == 'repair_interface' for f in exc.failures):
            client.trace.log('repair', 'interface_rejected', dict(failures=exc.failures, best_preserved=True))
        client.trace.log('repair', 'rejected', dict(error_type=type(exc).__name__, reason=str(exc), best_preserved=True))
        return retained('Repair failed: ' + str(exc), attempted=client.budget.repairs > before_calls)
