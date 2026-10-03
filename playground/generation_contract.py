"""Bound the model's output; the frozen PaperMechanismIR remains authoritative."""
from __future__ import annotations

import copy

from playground.computation import OPERATIONS

LIMITS = dict(controls=5, visuals=4, explorations=2, evidence=4,
              mechanism_grounding=4, symbols=8, tests=2, invariants=2)
MAX_NODES = 16
REPAIR_TOKENS = 4000


def compact_schema(schema: dict) -> dict:
    schema = copy.deepcopy(schema)
    # Injected test models keep their own contract.
    if 'ComputationNode' not in schema.get('$defs', {}):
        return schema
    for name, limit in LIMITS.items():
        schema['properties'][name]['maxItems'] = limit
    schema['properties']['explorations']['minItems'] = 2
    schema['$defs']['ComputationSpec']['properties']['nodes']['maxItems'] = MAX_NODES
    for name in ('Expression', 'ComputationNode'):
        schema['$defs'][name]['properties']['op']['enum'] = list(OPERATIONS)

    def strip(value, mapping=False):
        if isinstance(value, dict):
            return {k: strip(v, k in ('properties', '$defs')) for k, v in value.items()
                    if mapping or k not in ('title', 'default')}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value
    return strip(schema)


def compact_violations(candidate: dict) -> list[str]:
    """Check bounds even when a provider does not enforce response_format."""
    failures = [name for name, limit in LIMITS.items()
                if isinstance(candidate.get(name), list) and len(candidate[name]) > limit]
    if isinstance(candidate.get('explorations'), list) and len(candidate['explorations']) != 2:
        failures.append('explorations')
    computation = candidate.get('computation')
    if isinstance(computation, dict) and isinstance(computation.get('nodes'), list):
        if len(computation['nodes']) > MAX_NODES:
            failures.append('computation.nodes')
    return sorted(set(failures))


def catastrophic(candidate, schema: dict, failures=()) -> bool:
    if candidate is None or compact_violations(candidate):
        return True
    # A single missing field is still an ordinary localized repair.
    missing = set(schema.get('required', [])) - set(candidate)
    return len(missing) > 1
