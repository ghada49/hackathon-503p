"""Bounded OpenRouter compilation and transactional targeted repair."""
from __future__ import annotations

import copy
import importlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from pydantic import ValidationError

from playground.budget import BudgetExceeded, BudgetManager, MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL, call_with_timeout
from playground.trace import TraceLogger
from playground.retrieval import DEFAULT_CONTEXT_CHARS, source_context_payload

ENDPOINT = 'https://openrouter.ai/api/v1/chat/completions'
PROMPTS = Path(__file__).resolve().parent.parent / 'prompts'
# Frozen spec vocabulary, replaceable with Person 2's implemented registry.
CORE_OPERATIONS = tuple('add subtract multiply divide negate pow sqrt exp log log2 abs sin cos clip sum product mean min max argmin argmax dot matmul transpose index slice reshape flatten concat softmax softmax_rows normalize range cumsum difference equal not_equal less less_equal greater greater_equal and or not where map elementwise iterate scan'.split())
CONTROL_TYPES = tuple('slider number checkbox select vector_editor matrix_editor sequence_editor'.split())
VISUAL_TYPES = tuple('formula number table matrix heatmap bar_chart line_chart scatter vector pipeline nodes_edges scene'.split())
SCENE_ELEMENTS = tuple('line arrow circle rect point polyline text axis group'.split())
IR_FIELDS = tuple('schema_version teaching evidence provenance symbols controls computation mechanism_grounding visuals explorations limitation tests invariants'.split())


class IntegrationUnavailable(RuntimeError):
    pass


class OpenRouterError(RuntimeError):
    pass


class GenerationFailure(ValueError):
    def __init__(self, message: str, *, candidate: dict | None = None,
                 failures: list[dict] | None = None, allowed_paths: list[str] | None = None):
        super().__init__(message)
        self.candidate = copy.deepcopy(candidate)
        self.failures = failures or [dict(check='json_parse', severity='serious', path=None,
                                         message=message, repairable=True, allowed_paths=list(IR_FIELDS))]
        self.allowed_paths = allowed_paths if allowed_paths is not None else list(IR_FIELDS)


def shared_ir_model():
    try:
        module = importlib.import_module('playground.models')
    except ModuleNotFoundError as exc:
        if exc.name != 'playground.models':
            raise
        raise IntegrationUnavailable('Person 2 integration missing: playground.models.PaperMechanismIR') from exc
    model = getattr(module, 'PaperMechanismIR', None)
    if model is None:
        raise IntegrationUnavailable('Person 2 must expose PaperMechanismIR with model_validate/model_json_schema')
    return model


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _plain(value):
    if hasattr(value, 'model_dump'):
        return value.model_dump(mode='json')
    return copy.deepcopy(value)


def extract_json(text: str) -> dict:
    """Accept a complete object, optionally fenced; reject ambiguity and nonfinite values."""
    try:
        text = text.strip()
        fenced = re.fullmatch(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.S | re.I)
        if fenced:
            text = fenced.group(1).strip()

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('Duplicate JSON key')
                result[key] = value
            return result

        def reject_constant(value):
            raise ValueError('Nonfinite JSON value')

        result = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
        if not isinstance(result, dict):
            raise ValueError('Expected a JSON object')
        # Overflow such as 1e999 also must not enter the IR.
        _json(result)
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        raise GenerationFailure('Model response is not a valid finite JSON object') from exc


def _registry(operations=None) -> dict:
    return dict(ALLOWED_OPERATIONS=list(CORE_OPERATIONS) if operations is None else _plain(operations),
                ALLOWED_CONTROLS=CONTROL_TYPES, ALLOWED_VISUALS=VISUAL_TYPES,
                ALLOWED_SCENE_ELEMENTS=SCENE_ELEMENTS)


def build_generation_messages(case, evidence, schema: dict, *, operations=None, max_prompt_chars: int | None = None) -> list[dict]:
    system = PROMPTS.joinpath('generate.txt').read_text(encoding='utf-8')
    system += '\nCONTRACT\n' + _json(dict(OUTPUT_SCHEMA=schema, **_registry(operations)))
    # JSON escaping makes source delimiters in source text inert; no source interpolation in system.
    payload = dict(source_url=case.source_url, focus=case.focus, audience=case.audience,
                   **source_context_payload(evidence))
    messages = [dict(role='system', content=system), dict(role='user', content=_json(payload))]
    if max_prompt_chars is not None and sum(len(m['content']) for m in messages) > max_prompt_chars:
        raise GenerationFailure('Generation prompt exceeds configured context budget', allowed_paths=[])
    return messages


def generation_prompt_overhead(case, schema: dict, *, operations=None) -> int:
    """Exact content-character overhead outside SOURCE_BLOCKS/SOURCE_CONTEXT JSON."""
    system = PROMPTS.joinpath('generate.txt').read_text(encoding='utf-8')
    system += '\nCONTRACT\n' + _json(dict(OUTPUT_SCHEMA=schema, **_registry(operations)))
    brief = dict(source_url=case.source_url, focus=case.focus, audience=case.audience)
    return len(system) + len(_json(brief)) - 1


class OpenRouterClient:
    def __init__(self, model: str, budget: BudgetManager, trace: TraceLogger, *,
                 session=None, sleep=time.sleep, structured_output: bool = True):
        if not model.strip():
            raise ValueError('A nonempty model ID is required')
        self.model = model
        self.budget = budget
        self.trace = trace
        self.session = session or requests.Session()
        self.sleep = sleep
        self.structured_output = structured_output

    def complete(self, messages: list[dict], *, purpose: str, schema: dict | None = None,
                 max_tokens: int = 15000) -> str:
        key = os.environ.get('OPENROUTER_API_KEY')
        if not key or not key.strip():
            raise OpenRouterError('OPENROUTER_API_KEY is required in the environment')
        semantic = self.budget.start_semantic(purpose)
        payload = dict(model=self.model, messages=messages, temperature=0)
        if schema and self.structured_output:
            payload['response_format'] = dict(type='json_schema', json_schema=dict(name='PaperMechanismIR' if purpose == 'generation' else 'RepairPatch', strict=True, schema=schema))
        self.trace.log(purpose, 'semantic_call', dict(semantic_call_number=semantic, model=self.model))
        for attempt in range(MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL):
            payload['max_tokens'] = self.budget.completion_allowance(max_tokens)
            request_number = self.budget.begin_http_attempt()
            started = self.budget.clock()
            self.trace.log(purpose, 'openrouter_attempt', dict(model=self.model, semantic_call_number=semantic, http_request_number=request_number, attempt=attempt + 1))
            retry_reason = None
            wait = min(2 ** attempt, 8)
            try:
                timeout = min(180, self.budget.remaining_seconds)
                response = call_with_timeout(lambda: self.session.post(ENDPOINT,
                    headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                    json=payload, timeout=timeout, allow_redirects=False), timeout)
            except BudgetExceeded:
                self.budget.record_usage(completion_tokens=None, reserved_tokens=payload['max_tokens'])
                self.trace.log(purpose, 'network_deadline', dict(http_request_number=request_number, reserved_completion_tokens=payload['max_tokens']))
                raise
            except (requests.Timeout, requests.ConnectionError):
                # A disconnected request may still have generated a completion remotely.
                self.budget.record_usage(completion_tokens=None, reserved_tokens=payload['max_tokens'])
                retry_reason = 'transport_error'
            except requests.RequestException as exc:
                self.budget.record_usage(completion_tokens=None, reserved_tokens=payload['max_tokens'])
                raise OpenRouterError('OpenRouter transport failed') from exc
            else:
                status = response.status_code
                try:
                    data = response.json()
                except ValueError:
                    data = None
                if not isinstance(data, dict):
                    if status == 200:
                        self.budget.record_usage(completion_tokens=None, reserved_tokens=payload['max_tokens'])
                        raise OpenRouterError('OpenRouter returned a malformed response envelope')
                    data = {}
                usage = data.get('usage') or {}
                # Log only allowlisted metadata; never response messages or raw errors.
                self.trace.log(purpose, 'openrouter_call', dict(request_id=data.get('id'), model=self.model,
                    prompt_tokens=usage.get('prompt_tokens'), completion_tokens=usage.get('completion_tokens'),
                    total_tokens=usage.get('total_tokens'), elapsed_seconds=round(self.budget.clock() - started, 6),
                    semantic_call_number=semantic, http_request_number=request_number, status=status))
                self.budget.record_usage(prompt_tokens=usage.get('prompt_tokens') or 0,
                    completion_tokens=usage.get('completion_tokens') if status == 200 or usage else 0,
                    reserved_tokens=payload['max_tokens'])
                if status == 200:
                    if data.get('error'):
                        raise OpenRouterError('OpenRouter reported an error in its response')
                    if self.budget.remaining_seconds <= 0:
                        self.budget.check_available()
                    try:
                        choice = data['choices'][0]
                        content = choice['message']['content']
                        if not isinstance(content, str):
                            raise TypeError('Nontext content')
                    except (KeyError, IndexError, TypeError) as exc:
                        raise GenerationFailure('OpenRouter response contains no textual specification') from exc
                    return content
                error = data.get('error', {})
                error_message = str(error.get('message', '')) if isinstance(error, dict) else ''
                # Adaptive retry only for explicit unsupported optional parameters, never auth/format blindly.
                if status in (400, 422) and re.search(r'not supported|unsupported|does not support', error_message, re.I):
                    removed = []
                    for option in ('response_format', 'temperature'):
                        if option in payload and (option in error_message or option == 'response_format' and 'json_schema' in error_message):
                            payload.pop(option)
                            removed.append(option)
                    if removed:
                        retry_reason = 'unsupported_optional_parameter:' + ','.join(removed)
                        wait = 0
                elif status == 429 or 500 <= status <= 599:
                    retry_reason = f'http_{status}'
                    try:
                        wait = min(30, max(wait, float(response.headers.get('Retry-After', 0))))
                    except (ValueError, TypeError):
                        pass
                if retry_reason is None:
                    raise OpenRouterError(f'OpenRouter request rejected (HTTP {status})')
            if attempt + 1 >= MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL:
                raise OpenRouterError('OpenRouter HTTP attempts exhausted')
            self.budget.check_available(wait_seconds=wait)
            self.trace.log(purpose, 'retry', dict(reason=retry_reason, wait_seconds=wait, semantic_call_number=semantic))
            if wait:
                self.sleep(wait)
        raise OpenRouterError('OpenRouter HTTP attempts exhausted')


def _resolve_schema(schema: dict, root: dict) -> dict:
    seen = set()
    while '$ref' in schema and schema['$ref'] not in seen:
        reference = schema['$ref']
        seen.add(reference)
        if not reference.startswith('#/$defs/'):
            return {}
        schema = root.get('$defs', {}).get(reference.split('/')[-1], {})
    return schema


def normalize_repair_path(candidate: dict, location, schema: dict) -> str | None:
    """Walk candidate and contract together, consuming union labels only at unions."""
    def walk(current, fragment, parts, prefix):
        fragment = _resolve_schema(fragment, schema)
        if not parts:
            return prefix
        branches = fragment.get('oneOf', fragment.get('anyOf', []))
        if branches:
            labelled = []
            for branch in branches:
                resolved = _resolve_schema(branch, schema)
                labels = {resolved.get('title')}
                # Callable operand discriminators are omitted from JSON Schema.
                # Their tags correspond to the authoritative operand's required key.
                for key in ('ref', 'const', 'op'):
                    if key in resolved.get('required', []):
                        labels.update((key, key.capitalize()))
                if parts[0] in labels:
                    labelled.append(walk(current, branch, parts[1:], prefix))
            results = labelled or [walk(current, branch, parts, prefix) for branch in branches]
            return max(results, key=len, default=prefix)
        part = str(parts[0])
        proposed = prefix + [part]
        try:
            _parts('.'.join(proposed))
        except GenerationFailure:
            return prefix
        if isinstance(current, dict):
            properties = fragment.get('properties', {})
            if part in properties or part in current:
                child = properties.get(part, fragment.get('additionalProperties', {}))
                child = child if isinstance(child, dict) else {}
                if part not in current:
                    return proposed  # A schema-declared missing field, never a variant label.
                return walk(current[part], child, parts[1:], proposed)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            return walk(current[int(part)], fragment.get('items', {}), parts[1:], proposed)
        return prefix

    parts = walk(candidate, schema, list(location), [])
    return '.'.join(parts) if parts else None


def initial_missing_schema_version(candidate: dict, schema: dict) -> bool:
    expected = _resolve_schema(schema.get('properties', {}).get('schema_version', {}), schema)
    return 'schema_version' not in candidate and expected.get('const') == '1.0'


def validate_ir(candidate: dict, ir_model):
    try:
        return ir_model.model_validate(candidate)
    except ValidationError as exc:
        failures = []
        schema = ir_model.model_json_schema()
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            location = error['loc']
            if error['type'] == 'extra_forbidden':
                # Updates cannot delete fields; replace the smallest containing object instead.
                location = location[:-1]
            repair_path = normalize_repair_path(candidate, location, schema)
            allowed = [repair_path] if repair_path else []
            if repair_path == 'schema_version' and not initial_missing_schema_version(candidate, schema):
                allowed = []
            failures.append(dict(check='schema', severity='serious', path=repair_path,
                                 message=error['msg'], repairable=bool(allowed), allowed_paths=allowed))
        allowed = sorted({path for f in failures for path in f['allowed_paths']})
        raise GenerationFailure('PaperMechanismIR schema validation failed', candidate=candidate,
                                failures=failures, allowed_paths=allowed) from exc


def generate_spec(client: OpenRouterClient, evidence, case, *, ir_model=None, operations=None, max_prompt_chars: int | None = None):
    model = ir_model or shared_ir_model()
    schema = model.model_json_schema()
    text = client.complete(build_generation_messages(case, evidence, schema, operations=operations, max_prompt_chars=max_prompt_chars), purpose='generation', schema=schema)
    try:
        candidate = extract_json(text)
        spec = validate_ir(candidate, model)
    except GenerationFailure as exc:
        if exc.candidate is None and exc.allowed_paths:
            # Initial reconstruction follows the caller's actual contract, including test models.
            exc.allowed_paths = list(schema.get('properties', {}))
            for failure in exc.failures:
                failure['allowed_paths'] = list(exc.allowed_paths)
        client.trace.log('generation', 'parse_failure', dict(failures=exc.failures, allowed_paths=exc.allowed_paths))
        raise
    client.trace.log('generation', 'parsed', dict(schema_valid=True))
    return spec


_PATCH_SCHEMA = dict(type='object', properties={'updates': dict(type='array', items=dict(type='object', properties={'path': {'type': 'string'}, 'value': {}}, required=['path', 'value'], additionalProperties=False))}, required=['updates'], additionalProperties=False)


def _schema_at_path(candidate, path: str, schema: dict) -> dict | None:
    """Resolve a real dot path, permitting only schema-declared missing leaves."""
    def visit(current, fragment, parts):
        fragment = _resolve_schema(fragment, schema)
        if not parts:
            return fragment
        branches = fragment.get('oneOf', fragment.get('anyOf', []))
        if branches:
            if isinstance(current, dict):
                tagged = [key for key in ('ref', 'const', 'op') if key in current]
                if len(tagged) == 1:
                    matching = [b for b in branches if tagged[0] in _resolve_schema(b, schema).get('required', [])]
                    if matching:
                        branches = matching
            choices = [visit(current, branch, parts) for branch in branches]
            choices = [choice for choice in choices if choice is not None]
            return choices[0] if choices else None
        part = parts[0]
        if isinstance(current, dict):
            properties = fragment.get('properties', {})
            if part not in current and (part not in properties or len(parts) != 1):
                return None
            child = properties.get(part, fragment.get('additionalProperties', {}))
            return visit(current.get(part, _MISSING), child if isinstance(child, dict) else {}, parts[1:])
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            return visit(current[int(part)], fragment.get('items', {}), parts[1:])
        return None
    return visit(candidate, schema, _parts(path))


def _repair_schema(candidate: dict, allowed_paths: list[str], schema: dict) -> dict:
    def compact(fragment):
        if isinstance(fragment, list):
            return [compact(value) for value in fragment]
        if isinstance(fragment, dict):
            result = {}
            for key, value in fragment.items():
                if key in ('title', 'description', 'examples', 'default', '$defs'):
                    continue
                if key in ('properties', 'patternProperties'):
                    result[key] = {name: compact(child) for name, child in value.items()}
                else:
                    result[key] = compact(value)
            return result
        return fragment

    fields = {}
    for path in allowed_paths:
        fragment = _schema_at_path(candidate, path, schema)
        if fragment is None:
            raise GenerationFailure('Repair scope is not a real candidate/schema path', allowed_paths=[])
        fields[path] = compact(fragment)
    definitions = {}
    def references(value):
        if isinstance(value, dict):
            if '$ref' in value:
                reference = value['$ref']
                if not reference.startswith('#/$defs/'):
                    raise GenerationFailure('Unsupported repair schema reference', allowed_paths=[])
                name = reference.split('/')[-1]
                if name not in definitions:
                    original = schema.get('$defs', {}).get(name)
                    if original is None:
                        raise GenerationFailure('Unresolved repair schema reference', allowed_paths=[])
                    definitions[name] = compact(original)
                    references(definitions[name])
            for child in value.values():
                references(child)
        elif isinstance(value, list):
            for child in value:
                references(child)
    references(fields)
    return dict(fields=fields, **({'$defs': definitions} if definitions else {}))


def build_repair_context(candidate, failures, allowed_paths: list[str], focus_context=None,
                         remaining_budget=None, *, case=None, ir_model=None, operations=None,
                         allow_full_regeneration: bool = False, max_prompt_chars: int | None = None) -> list[dict]:
    """Assemble scoped candidate/schema/evidence, checking the final serialized prompt."""
    max_prompt_chars = DEFAULT_CONTEXT_CHARS if max_prompt_chars is None else max_prompt_chars
    original = _plain(candidate)
    for path in allowed_paths:
        _parts(path)
    schema = ir_model.model_json_schema() if ir_model is not None else {}
    fields = []
    for path in allowed_paths:
        value = _get(original, path)
        fields.append(dict(path=path, missing=True) if value is _MISSING else dict(path=path, value=value))
    payload = dict(candidate_fields=fields, failures=[_plain(f) for f in failures],
                   allowed_paths=list(allowed_paths), allow_full_regeneration=allow_full_regeneration,
                   remaining_budget=_plain(remaining_budget or {}))
    if case is not None:
        payload['brief'] = dict(source_url=case.source_url, focus=case.focus, audience=case.audience)
    elif focus_context is not None:
        payload['brief'] = dict(focus=focus_context.focus, audience=focus_context.audience)
    if ir_model is not None:
        payload['REPAIR_SCHEMA'] = _repair_schema(original, allowed_paths, schema)
    else:
        # Without a shared schema only existing leaves or missing direct children are addressable.
        for path in allowed_paths:
            parts = _parts(path)
            parent = _get(original, '.'.join(parts[:-1])) if len(parts) > 1 else original
            if not isinstance(parent, dict) and _get(original, path) is _MISSING:
                raise GenerationFailure('Repair scope is not addressable', allowed_paths=[])
    registry = _registry(operations)
    for root, keys in [('computation', ('ALLOWED_OPERATIONS',)), ('controls', ('ALLOWED_CONTROLS',)),
                       ('visuals', ('ALLOWED_VISUALS', 'ALLOWED_SCENE_ELEMENTS'))]:
        if any(path.split('.')[0] == root for path in allowed_paths):
            payload.update({key: registry[key] for key in keys})
    if any(path.split('.')[0] == 'computation' and (path.endswith('.ref') or '.inputs' in path) for path in allowed_paths):
        controls = original.get('controls')
        computation = original.get('computation')
        nodes = computation.get('nodes') if isinstance(computation, dict) else None
        payload['reference_ids'] = dict(
            controls=[item['id'] for item in controls if isinstance(item, dict) and isinstance(item.get('id'), str)] if isinstance(controls, list) else [],
            nodes=[item['id'] for item in nodes if isinstance(item, dict) and isinstance(item.get('id'), str)] if isinstance(nodes, list) else [])
    template = PROMPTS.joinpath('repair.txt').read_text(encoding='utf-8')

    def messages():
        return [dict(role='system', content=template), dict(role='user', content=_json(payload))]

    def fits():
        return max_prompt_chars is None or sum(len(m['content']) for m in messages()) <= max_prompt_chars

    def require_fit():
        if not fits():
            raise GenerationFailure('Repair prompt exceeds configured context budget', candidate=original, allowed_paths=[])

    def require_evidence_fit():
        # Surrounding sibling values are optional; exact leaves and needed evidence are not.
        if not fits():
            payload.pop('surrounding_fields', None)
        require_fit()

    require_fit()  # Exact failures, candidate leaves and required schema cannot be discarded.
    surrounding = {}
    for path in allowed_paths:
        parts = _parts(path)
        if len(parts) <= 1:
            continue
        parent_path = '.'.join(parts[:-1])
        parent = _get(original, parent_path)
        if parent is _MISSING or parent_path in surrounding:
            continue
        surrounding[parent_path] = parent
        payload['surrounding_fields'] = surrounding
        if not fits():
            surrounding.pop(parent_path)
    if not surrounding:
        payload.pop('surrounding_fields', None)

    grounded_roots = {'evidence', 'mechanism_grounding', 'symbols', 'limitation'}
    source_needed = allow_full_regeneration or any(
        path.split('.')[0] in grounded_roots or
        (path.split('.')[0] in {'computation', 'teaching'} and any(f.get('check') != 'schema' for f in payload['failures']))
        for path in allowed_paths)
    if source_needed and focus_context is not None:
        block_ids = set()
        node_ids = set()
        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == 'blocks' and isinstance(child, list):
                        block_ids.update(item for item in child if isinstance(item, str))
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        for path in allowed_paths:
            parts = _parts(path)
            region_path = '.'.join(parts[:2]) if parts[0] in {'evidence', 'mechanism_grounding', 'symbols'} and len(parts) > 1 else parts[0]
            if parts[0] == 'computation' and len(parts) > 2:
                region_path = '.'.join(parts[:3])
            region = _get(original, region_path)
            if region is not _MISSING:
                collect(region)
                if parts[0] == 'computation' and isinstance(region, dict) and isinstance(region.get('id'), str):
                    node_ids.add(region['id'])
        groundings = original.get('mechanism_grounding')
        for grounding in groundings if isinstance(groundings, list) else []:
            targets = grounding.get('nodes') if isinstance(grounding, dict) else None
            if isinstance(targets, list) and node_ids.intersection(item for item in targets if isinstance(item, str)):
                collect(grounding)
        relevant = [b for b in focus_context.blocks if b.id in block_ids]
        if relevant:
            payload['SOURCE_BLOCKS'] = [b.model_dump(mode='json', exclude_none=True) for b in relevant]
            require_evidence_fit()
        else:
            # Missing/malformed grounding has no usable IDs: propose original focused material.
            candidates = list(focus_context.blocks)
            if not allow_full_regeneration and candidates:
                query = set(re.findall(r'\w+', focus_context.focus.lower()))
                anchor = max(candidates, key=lambda b: (len(query.intersection(re.findall(r'\w+', b.text.lower()))), b.type != 'heading', -b.order))
                candidates = [b for b in candidates if b.section == anchor.section] if anchor.section else [anchor]
            payload['SOURCE_BLOCKS'] = []
            for block in candidates:
                if block.type == 'heading':
                    continue
                payload['SOURCE_BLOCKS'].append(block.model_dump(mode='json', exclude_none=True))
                if not fits():
                    payload.pop('surrounding_fields', None)
                if not fits():
                    payload['SOURCE_BLOCKS'].pop()
            if not payload['SOURCE_BLOCKS']:
                raise GenerationFailure('Required source evidence exceeds repair context budget', candidate=original, allowed_paths=[])
        # Optional neighbors may only come from the same coherent region.
        selected_ids = {b['id'] for b in payload['SOURCE_BLOCKS']}
        for block in focus_context.blocks:
            if block.id in selected_ids:
                continue
            if any(core.section and block.section == core.section and abs(block.order - core.order) == 1 for core in relevant):
                payload['SOURCE_BLOCKS'].append(block.model_dump(mode='json', exclude_none=True))
                if not fits():
                    payload['SOURCE_BLOCKS'].pop()
    require_fit()
    return messages()


def repair_spec(client: OpenRouterClient, existing_spec, failures, allowed_paths: list[str], *,
                evidence=None, case=None, ir_model=None, operations=None, allow_full_regeneration: bool = False,
                max_prompt_chars: int | None = None) -> dict:
    if not allowed_paths:
        raise GenerationFailure('No authorized repair paths', allowed_paths=[])
    max_prompt_chars = DEFAULT_CONTEXT_CHARS if max_prompt_chars is None else max_prompt_chars
    try:
        messages = build_repair_context(existing_spec, failures, allowed_paths, evidence,
            dict(seconds=client.budget.remaining_seconds, completion_tokens=client.budget.remaining_tokens),
            case=case, ir_model=ir_model, operations=operations, allow_full_regeneration=allow_full_regeneration,
            max_prompt_chars=max_prompt_chars)
    except GenerationFailure as exc:
        client.trace.log('repair', 'repair_skipped', dict(reason='context_budget' if 'context budget' in str(exc) else 'invalid_scope',
            max_prompt_chars=max_prompt_chars))
        raise
    client.trace.log('repair', 'repair_attempt', dict(allowed_paths=list(allowed_paths),
        prompt_chars=sum(len(m['content']) for m in messages), max_prompt_chars=max_prompt_chars))
    return extract_json(client.complete(messages, purpose='repair', schema=_PATCH_SCHEMA, max_tokens=10000))


def _parts(path: str) -> list[str]:
    if not isinstance(path, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.(?:[A-Za-z][A-Za-z0-9_]*|0|[1-9][0-9]*))*', path):
        raise GenerationFailure('Invalid repair path', allowed_paths=[])
    return path.split('.')


_MISSING = object()


def _get(spec, path):
    current = spec
    for part in _parts(path):
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


def apply_restricted_patch(existing_spec, patch: dict, allowed_paths: list[str], *,
                           protected_paths=('schema_version', 'source_url', 'audience'),
                           allow_initial_missing_version: bool = False, ir_model=None) -> dict:
    original = _plain(existing_spec)
    candidate = copy.deepcopy(original)
    if allow_initial_missing_version:
        if (ir_model is None or 'schema_version' not in allowed_paths or
                not initial_missing_schema_version(original, ir_model.model_json_schema())):
            raise GenerationFailure('Initial schema version repair is not authorized', allowed_paths=[])
        protected_paths = tuple(path for path in protected_paths if path != 'schema_version')
    if set(patch) != {'updates'} or not isinstance(patch['updates'], list):
        raise GenerationFailure('Malformed repair patch', allowed_paths=[])
    for allowed in allowed_paths:
        _parts(allowed)
    for update in patch['updates']:
        if not isinstance(update, dict) or set(update) != {'path', 'value'}:
            raise GenerationFailure('Malformed repair update', allowed_paths=[])
        path = update['path']
        parts = _parts(path)
        if not any(path == allowed or path.startswith(allowed + '.') for allowed in allowed_paths):
            raise GenerationFailure('Repair path is not allowed', allowed_paths=[])
        parent = candidate
        for part in parts[:-1]:
            if isinstance(parent, list) and part.isdigit() and int(part) < len(parent):
                parent = parent[int(part)]
            elif isinstance(parent, dict) and part in parent:
                parent = parent[part]
            else:
                raise GenerationFailure('Repair parent does not exist', allowed_paths=[])
        last = parts[-1]
        if isinstance(parent, list) and last.isdigit() and int(last) < len(parent):
            parent[int(last)] = copy.deepcopy(update['value'])
        elif isinstance(parent, dict):
            parent[last] = copy.deepcopy(update['value'])
        else:
            raise GenerationFailure('Repair target is invalid', allowed_paths=[])
    for path in protected_paths:
        if _get(original, path) != _get(candidate, path):
            raise GenerationFailure('Repair modified a protected field', allowed_paths=[])
    if allow_initial_missing_version and candidate.get('schema_version') != '1.0':
        raise GenerationFailure('Repair did not supply the authoritative schema version', allowed_paths=[])
    _json(candidate)
    return candidate


class BestSoFar:
    """Acceptance is supplied by Person 2; this helper owns snapshots, never scoring."""
    def __init__(self, spec, validation=None, html: str | None = None):
        self.spec = copy.deepcopy(spec)
        self.validation = copy.deepcopy(validation)
        self.html = html

    def consider(self, candidate, validation, html: str | None = None, *, accepted: bool) -> bool:
        if not accepted:
            return False
        self.spec = copy.deepcopy(candidate)
        self.validation = copy.deepcopy(validation)
        self.html = html
        return True
