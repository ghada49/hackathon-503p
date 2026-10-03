"""Person 1 orchestration over the unchanged, frozen Person 2 scientific APIs."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from pydantic import ValidationError

from playground.budget import BudgetExceeded, call_with_timeout
from playground.generator import (BestSoFar, GenerationFailure, OpenRouterError,
    apply_restricted_patch, generate_spec, initial_missing_schema_version, repair_spec)
from playground.models import PaperMechanismIR, SourceBlock, ValidationResult, DerivedPlayground
from playground.validation import validate_spec, derive_playground

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
        assessment = assess_candidate(original if original is not None else {}, evidence.blocks,
                                      trace=client.trace, budget=client.budget)
    except BudgetExceeded as exc:
        return CompilationResult(copy.deepcopy(original), None, None, False, reason=str(exc))
    best = BestSoFar(assessment.spec if assessment.spec is not None else original, assessment.validation)
    best_derived = copy.deepcopy(assessment.derived)

    def retained(reason, *, attempted=False):
        return CompilationResult(copy.deepcopy(best.spec), copy.deepcopy(best.validation),
                                 copy.deepcopy(best_derived), False, attempted, reason)

    if assessment.accepted:
        client.trace.log('science', 'accepted', dict(validation_ok=True, frozen_sha=PERSON2_FROZEN_SHA))
        return CompilationResult(best.spec, best.validation, best_derived, True)
    failures = [failure.model_dump(mode='json') for failure in assessment.validation.failures]
    allowed = sorted({path for failure in assessment.validation.failures if failure.repairable
                      for path in failure.allowed_paths})
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
        return retained('Scientific/schema validation failed; no authorized repair paths')
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
        repaired = assess_candidate(candidate, evidence.blocks, trace=client.trace, budget=client.budget)
        if repaired.accepted:
            best.consider(repaired.spec, repaired.validation, accepted=True)
            best_derived = copy.deepcopy(repaired.derived)
            client.trace.log('repair', 'accepted', dict(validation_ok=True, validation_reused_within_assessment=True))
            return CompilationResult(best.spec, best.validation, best_derived, True, True)
        client.trace.log('repair', 'rejected', dict(validation_ok=False,
            failures=[failure.model_dump(mode='json') for failure in repaired.validation.failures], best_preserved=True))
        return retained('Repaired candidate failed scientific/schema validation', attempted=True)
    except (GenerationFailure, OpenRouterError, BudgetExceeded, ValidationError) as exc:
        client.trace.log('repair', 'rejected', dict(error_type=type(exc).__name__, reason=str(exc), best_preserved=True))
        return retained('Repair failed: ' + str(exc), attempted=client.budget.repairs > before_calls)
