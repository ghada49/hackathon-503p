"""Person 1 entry point: case → source evidence → schema-validated scientific IR."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from pydantic import ValidationError

from playground.budget import BudgetManager
from playground.generator import (GenerationFailure, OpenRouterClient, apply_restricted_patch,
                                  generate_spec, generation_prompt_overhead, repair_spec, shared_ir_model, validate_ir)
from playground.retrieval import DEFAULT_CONTEXT_CHARS, select_source_context
from playground.source import load_case, normalize_source, resolve_source
from playground.trace import TraceLogger

_OUTPUTS = ('spec.json', 'source_blocks.json', 'source_document.json', 'trace.jsonl')


def prepare_output_dir(path: str | Path) -> Path:
    output = Path(path).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in _OUTPUTS:
        target = output / name
        if target.is_symlink() or target.resolve().parent != output:
            raise ValueError('Output artifact must stay inside output directory')
        if target.exists() and not target.is_file():
            raise ValueError('Output artifact path is not a file')
    # Remove only this stage's generated outputs, preserving unrelated user files.
    for name in _OUTPUTS:
        (output / name).unlink(missing_ok=True)
    return output


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + '\n', encoding='utf-8')


def run(input_path: str | Path, output_path: str | Path, model: str, *,
        session=None, ir_model=None, operations=None, allow_url: bool = False,
        context_max_chars: int = DEFAULT_CONTEXT_CHARS) -> int:
    budget = BudgetManager()
    trace = None
    success = False
    reason = None
    output = None
    try:
        case = load_case(input_path)
        output = prepare_output_dir(output_path)
        trace = TraceLogger(output / 'trace.jsonl', started=budget.started)
        trace.log('input', 'load_case', dict(success=True, extra_fields=list((case.model_extra or {}).keys())))
        trace.log('output', 'prepare_output_dir', dict(success=True))
        budget.check_available()
        document = resolve_source(case, base_dir=Path(input_path).resolve().parent,
                                  allow_url=allow_url, timeout=min(20, budget.remaining_seconds))
        trace.log('source', 'resolve_source', dict(origin=document.origin))
        blocks = normalize_source(document)
        trace.log('source', 'normalize_source', dict(block_count=len(blocks)))
        shared = ir_model or shared_ir_model()
        context_max_chars = int(context_max_chars)
        overhead = generation_prompt_overhead(case, shared.model_json_schema(), operations=operations)
        evidence = select_source_context(document, case.focus, case.audience,
                                        max_chars=context_max_chars, prompt_overhead_chars=overhead)
        trace.log('retrieval', 'select_source_context', dict(mode=evidence.mode, coverage=evidence.coverage,
            stages=evidence.stages, metadata=evidence.metadata, max_prompt_chars=context_max_chars,
            prompt_overhead_chars=overhead, block_count=len(evidence.blocks), block_ids=[b.id for b in evidence.blocks]))
        client = OpenRouterClient(model, budget, trace, session=session)
        try:
            spec = generate_spec(client, evidence, case, ir_model=shared, operations=operations, max_prompt_chars=context_max_chars)
        except GenerationFailure as failure:
            if not failure.allowed_paths:
                raise
            budget.check_available()
            empty_candidate = failure.candidate is None
            patch = repair_spec(client, failure.candidate or {}, failure.failures, failure.allowed_paths,
                                evidence=evidence, case=case, ir_model=shared, operations=operations,
                                allow_full_regeneration=empty_candidate, max_prompt_chars=context_max_chars)
            candidate = apply_restricted_patch(failure.candidate or {}, patch, failure.allowed_paths,
                                              protected_paths=('source_url', 'audience') if empty_candidate else ('schema_version', 'source_url', 'audience'))
            spec = validate_ir(candidate, shared)
            trace.log('repair', 'accepted', dict(schema_valid=True))
        # This is the Person 1 handoff, not scientific/artifact validation.
        if budget.remaining_seconds <= 0:
            budget.check_available()
        _write_json(output / 'source_blocks.json', dict(source_url=case.source_url, focus=case.focus,
                    audience=case.audience, blocks=[b.model_dump(mode='json') for b in blocks]))
        _write_json(output / 'source_document.json', document.model_dump(mode='json'))
        _write_json(output / 'spec.json', spec.model_dump(mode='json'))
        trace.log('output', 'write_ir', dict(schema_valid=True, artifact='spec.json'))
        success = True
    except Exception as exc:
        # Error text may include source/credentials; redact known secrets before stderr.
        if isinstance(exc, ValidationError):
            # Pydantic's printable exception includes raw input dictionaries.
            # Report locations only, so unknown case credentials/source text cannot leak.
            locations = ['.'.join(str(part) for part in error['loc']) or 'root'
                         for error in exc.errors(include_input=False, include_context=False, include_url=False)]
            reason = 'Input validation failed at: ' + ', '.join(locations)
        else:
            reason = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__
        if trace is None:
            try:
                output = prepare_output_dir(output_path)
                trace = TraceLogger(output / 'trace.jsonl', started=budget.started)
                trace.log('input', 'startup_failure', dict(error_type=type(exc).__name__))
            except (OSError, ValueError):
                pass
        if trace:
            trace.log('failure', 'failed', dict(error_type=type(exc).__name__, reason=reason))
            reason = trace.sanitize(reason)
        else:
            key = os.environ.get('OPENROUTER_API_KEY')
            if key:
                reason = reason.replace(key, '[REDACTED]')
        print(f'Generation failed: {reason}', file=sys.stderr)
    finally:
        if trace:
            try:
                trace.log('finalize', 'complete', dict(success=success, reason=reason, **budget.totals()))
            finally:
                trace.close()
    return 0 if success else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Compile scientific source into PaperMechanismIR (Person 1 stage)')
    parser.add_argument('--input', required=True, help='UTF-8 case JSON file')
    parser.add_argument('--output', required=True, help='Output directory')
    parser.add_argument('--model', required=True, help='Exact OpenRouter model ID')
    args = parser.parse_args(argv)
    return run(args.input, args.output, args.model,
               allow_url=os.environ.get('PAPER_PLAYGROUND_ALLOW_URL', '').lower() in ('1', 'true'),
               context_max_chars=os.environ.get('PAPER_PLAYGROUND_CONTEXT_CHARS', DEFAULT_CONTEXT_CHARS))


if __name__ == '__main__':
    raise SystemExit(main())
