"""Bounded scientific AST interpreter. No eval, generated code, or paper dispatch."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from .models import ComputationSpec, ControlSpec, PaperMechanismIR, check_literal

MAX_ITERATIONS = 100
MAX_ELEMENTS = 10000
MAX_STEPS = 20000
MAX_DEPTH = 32
LOCAL_NAMES = {'state', 'item', 'index'}


class ComputationError(ValueError):
    """Invalid graph, type, shape, numerical domain, or execution budget."""


@dataclass(frozen=True)
class OperationSpec:
    arity: tuple[int, int]
    params: tuple[str, ...] = ()


OPERATIONS: dict[str, OperationSpec] = {}


def _register(names: str, arity: int | tuple[int, int], params: tuple[str, ...] = ()):
    for name in names.split():
        OPERATIONS[name] = OperationSpec((arity, arity) if isinstance(arity, int) else arity, params)


_register('add subtract multiply divide pow dot matmul equal not_equal less less_equal greater greater_equal and or', 2)
_register('negate sqrt exp log log2 abs sin cos not transpose flatten', 1)
_register('sum product mean min max argmin argmax softmax softmax_rows normalize cumsum difference', 1, ('axis',))
_register('clip where', 3)
_register('index', 2)
_register('slice', 1, ('start', 'stop', 'step', 'end_ref'))
_register('reshape', 1, ('shape',))
_register('concat', (1, 100), ('axis', 'promote_scalars'))
_register('range', (1, 3))
_register('map elementwise', 1, ('body',))
_register('iterate scan', 2, ('body',))


def _dict(value: Any) -> dict:
    return value.model_dump() if hasattr(value, 'model_dump') else value


def _array(value: Any) -> np.ndarray:
    try:
        result = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ComputationError('Arrays must be rectangular') from exc
    if result.size > MAX_ELEMENTS or result.ndim > 2:
        raise ComputationError('Value exceeds array size/rank limit')
    return result


def _numeric(value: Any) -> np.ndarray:
    result = _array(value)
    if result.dtype.kind not in 'iuf' or any(type(x) is bool for x in np.asarray(value, dtype=object).reshape(-1)):
        raise ComputationError('Expected numeric value')
    return result.astype(float)


def _boolean(value: Any) -> np.ndarray:
    result = _array(value)
    if result.dtype.kind != 'b':
        raise ComputationError('Expected boolean value')
    return result


def _finite(value: Any) -> None:
    result = _array(value)
    if result.dtype.kind in 'iuf' and not np.all(np.isfinite(result)):
        raise ComputationError('Nonfinite calculation result')


def _json(value: Any) -> Any:
    return value.tolist() if isinstance(value, np.ndarray) else value.item() if isinstance(value, np.generic) else value


def _broadcast(*args: np.ndarray) -> None:
    shapes = {a.shape for a in args if a.ndim}
    if len(shapes) > 1:
        raise ComputationError('Only scalar broadcasting or identical array shapes are allowed')


def _integer(value: Any, label: str) -> int:
    a = _numeric(value)
    if a.ndim or not np.isfinite(a) or float(a) != int(a):
        raise ComputationError(f'{label} must be an integer scalar')
    return int(a)


def _sum_sequence(values) -> float:
    """Neumaier sum in a fixed traversal order, shared with the JS runtime."""
    total, correction = 0.0, 0.0
    for value in values:
        value = float(value)
        updated = total + value
        correction += (total - updated) + value if abs(total) >= abs(value) else (value - updated) + total
        total = updated
    return total + correction


def _sum_array(value: np.ndarray, axis: int | None = None, keepdims: bool = False):
    result = _sum_sequence(value.reshape(-1)) if axis is None else np.apply_along_axis(_sum_sequence, axis, value)
    if keepdims:
        return np.asarray(result).reshape((1,) * value.ndim) if axis is None else np.expand_dims(result, axis)
    return result


def _cumsum_sequence(values) -> np.ndarray:
    total, correction, result = 0.0, 0.0, []
    for value in values:
        value = float(value)
        updated = total + value
        correction += (total - updated) + value if abs(total) >= abs(value) else (value - updated) + total
        total = updated
        result.append(total + correction)
    return np.asarray(result)


def _slice_params(params: dict) -> dict:
    """Normalize integer-valued floats; reject fractional or nonnumeric bounds."""
    normalized = dict(params)
    for key in ('start', 'stop', 'step'):
        if key in normalized:
            normalized[key] = _integer(normalized[key], key)
    if normalized.get('step') == 0:
        raise ComputationError('slice step cannot be zero')
    return normalized


def value_type(value: Any) -> dict[str, Any]:
    a = _array(value)
    kind = 'matrix' if a.ndim == 2 else 'vector' if a.ndim == 1 else 'boolean' if a.dtype.kind == 'b' else 'categorical' if a.dtype.kind in 'US' else 'scalar'
    return {'kind': kind, 'shape': list(a.shape)}


def validate_control_value(control: ControlSpec, value: Any) -> None:
    try:
        check_literal(value)
    except ValueError as exc:
        raise ComputationError(str(exc)) from exc
    actual = value_type(value)
    expected_kind = 'vector' if control.value_kind == 'sequence' else control.value_kind
    if actual['kind'] != expected_kind and not (control.type == 'select' and control.value_kind == 'categorical' and actual['kind'] in {'scalar', 'boolean'}):
        raise ComputationError(f'Control {control.id}: expected {control.value_kind}, got {actual["kind"]}')
    if control.shape is not None and actual['shape'] != control.shape:
        raise ComputationError(f'Control {control.id}: shape mismatch')
    expected = {'slider': {'scalar'}, 'number': {'scalar'}, 'checkbox': {'boolean'},
                'select': {'scalar', 'categorical', 'boolean'}, 'vector_editor': {'vector'},
                'matrix_editor': {'matrix'}, 'sequence_editor': {'sequence'}}
    if control.value_kind not in expected[control.type]:
        raise ComputationError(f'Control {control.id}: incompatible editor and value kind')
    if control.type == 'select':
        if not control.options or not any(type(value) is type(option) and value == option or type(value) in (int, float) and type(option) in (int, float) and value == option for option in control.options):
            raise ComputationError(f'Control {control.id}: value is not an option')
    a = _array(value)
    if control.value_kind in {'vector', 'matrix', 'sequence'}:
        _numeric(value)
    if a.dtype.kind in 'iuf':
        if control.min is not None and np.any(a < control.min):
            raise ComputationError(f'Control {control.id}: below minimum')
        if control.max is not None and np.any(a > control.max):
            raise ComputationError(f'Control {control.id}: above maximum')


def _refs(expr: Any, local: set[str] | None = None, depth: int = 0) -> set[str]:
    """Validate expressions and collect global references, respecting body scope."""
    if depth > MAX_DEPTH:
        raise ComputationError('Expression depth limit exceeded')
    expr = _dict(expr)
    if not isinstance(expr, dict):
        raise ComputationError('Operand must be a reference, constant, or operation')
    if set(expr) == {'ref'}:
        if not isinstance(expr['ref'], str):
            raise ComputationError('Reference must be a string')
        return set() if expr['ref'] in (local or set()) else {expr['ref']}
    if set(expr) == {'const'}:
        try:
            check_literal(expr['const'])
        except ValueError as exc:
            raise ComputationError(str(exc)) from exc
        _array(expr['const'])
        return set()
    op = expr.get('op')
    if op not in OPERATIONS:
        raise ComputationError(f'Unknown operation: {op}')
    inputs = expr.get('inputs')
    rule = OPERATIONS[op]
    if not isinstance(inputs, list) or not rule.arity[0] <= len(inputs) <= rule.arity[1]:
        raise ComputationError(f'{op}: invalid arity')
    params = expr.get('params', {})
    if not isinstance(params, dict) or set(params) - set(rule.params):
        raise ComputationError(f'{op}: unsupported parameters')
    if set(expr) - {'op', 'inputs', 'params', 'id', 'kind', 'shape', 'display', 'label', 'format'}:
        raise ComputationError('Unknown expression fields')
    refs: set[str] = set()
    for child in inputs:
        refs |= _refs(child, local, depth + 1)
    if op == 'slice' and 'end_ref' in params:
        if 'stop' in params or not isinstance(params['end_ref'], str):
            raise ComputationError('slice: end_ref must be a reference and cannot coexist with stop')
        refs |= _refs({'ref': params['end_ref']}, local, depth + 1)
    if op in {'map', 'elementwise', 'iterate', 'scan'}:
        if 'body' not in params:
            raise ComputationError(f'{op}: body is required')
        scope = {'item', 'index'} if op in {'map', 'elementwise'} else {'state', 'index'} if op == 'iterate' else LOCAL_NAMES
        refs |= _refs(params['body'], (local or set()) | scope, depth + 1)
    return refs


def graph_order(computation: ComputationSpec, control_ids: set[str]) -> tuple[list[str], dict[str, set[str]]]:
    nodes = {n.id: n for n in computation.nodes}
    if len(nodes) != len(computation.nodes) or set(nodes) & control_ids:
        raise ComputationError('Node IDs must be unique and distinct from controls')
    if set(nodes) & LOCAL_NAMES or control_ids & LOCAL_NAMES:
        raise ComputationError('state, item, and index are reserved local names')
    refs = {name: _refs(node) for name, node in nodes.items()}
    known = set(nodes) | control_ids
    for name, deps in refs.items():
        if deps - known:
            raise ComputationError(f'{name}: unknown references {sorted(deps - known)}')
    if set(computation.outputs) - known:
        raise ComputationError('Unknown output reference')
    order: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str):
        if name in control_ids or name in visited:
            return
        if name in visiting:
            raise ComputationError('Cyclic computation graph')
        visiting.add(name)
        for dep in sorted(refs[name]):
            visit(dep)
        visiting.remove(name)
        visited.add(name)
        order.append(name)

    for name in nodes:
        visit(name)
    return order, refs


def derive_dependencies(spec: PaperMechanismIR) -> dict[str, list[str]]:
    """For every control/node, return its transitive downstream node IDs."""
    controls = {c.id for c in spec.controls}
    _, refs = graph_order(spec.computation, controls)
    result = {}
    for source in sorted(controls | set(refs)):
        affected: set[str] = set()
        changed = True
        while changed:
            changed = False
            for node, deps in refs.items():
                if node not in affected and (source in deps or affected & deps):
                    affected.add(node)
                    changed = True
        result[source] = sorted(affected)
    return result


@dataclass(frozen=True)
class TypeShape:
    dtype: str
    shape: tuple[int | None, ...]

    @property
    def kind(self):
        return 'matrix' if len(self.shape) == 2 else 'vector' if self.shape else 'boolean' if self.dtype == 'boolean' else 'categorical' if self.dtype == 'categorical' else 'scalar'


def _literal_type(value: Any) -> TypeShape:
    a = _array(value)
    dtype = 'boolean' if a.dtype.kind == 'b' else 'categorical' if a.dtype.kind in 'US' else 'numeric'
    if dtype == 'numeric':
        _numeric(value)
    return TypeShape(dtype, a.shape)


def _shape_compatible(a: tuple, b: tuple) -> bool:
    return len(a) == len(b) and all(x is None or y is None or x == y for x, y in zip(a, b))


def _shape_merge(*types: TypeShape) -> tuple:
    shapes = [t.shape for t in types if t.shape]
    if not shapes:
        return ()
    result = shapes[0]
    for shape in shapes[1:]:
        if not _shape_compatible(result, shape):
            raise ComputationError('Static shape mismatch: scalar broadcasting only')
        result = tuple(x if x is not None else y for x, y in zip(result, shape))
    return result


def _check_map_projection(op: str, count: int, body_shape: tuple[int | None, ...]) -> None:
    """Check output rank/capacity before evaluating further bodies or stacking."""
    if op == 'elementwise':
        if body_shape:
            raise ComputationError('elementwise body must return a scalar')
        projected = count
    else:
        if len(body_shape) + 1 > 2:
            raise ComputationError('map projected output exceeds rank limit')
        if any(dimension is None for dimension in body_shape):
            return  # Check the first bounded body result before constructing output.
        projected = count
        for dimension in body_shape:
            projected *= dimension
    if projected > MAX_ELEMENTS:
        raise ComputationError(f'{op} projected output exceeds element limit')


def _infer_expression(expression: Any, types: dict[str, TypeShape], depth=0) -> TypeShape:
    if depth > MAX_DEPTH:
        raise ComputationError('Type inference depth exceeded')
    e = _dict(expression)
    if 'ref' in e:
        return types[e['ref']]
    if 'const' in e:
        return _literal_type(e['const'])
    op, p = e['op'], e.get('params', {})
    args = [_infer_expression(x, types, depth + 1) for x in e['inputs']]

    def numeric(*values):
        if any(t.dtype != 'numeric' for t in values):
            raise ComputationError(f'{op}: numeric operands required')

    def axis(default=None):
        value = p.get('axis', default)
        if value is None:
            return None
        if type(value) is not int or not -len(args[0].shape) <= value < len(args[0].shape):
            raise ComputationError(f'{op}: invalid axis')
        return value % len(args[0].shape)

    if op in {'map', 'elementwise', 'iterate', 'scan'}:
        first = args[0]
        scope = dict(types)
        scope['index'] = TypeShape('numeric', ())
        if op in {'map', 'elementwise'}:
            if not first.shape:
                raise ComputationError(f'{op}: array required')
            scope['item'] = TypeShape(first.dtype, () if op == 'elementwise' else first.shape[1:])
        else:
            scope['state'] = first
            if op == 'iterate':
                numeric(args[1])
                if args[1].shape:
                    raise ComputationError('iterate count must be scalar')
            else:
                if len(args[1].shape) != 1:
                    raise ComputationError('scan requires a vector')
                scope['item'] = TypeShape(args[1].dtype, ())
        body = _infer_expression(p['body'], scope, depth + 1)
        if op in {'iterate', 'scan'}:
            if body.dtype != first.dtype or not _shape_compatible(body.shape, first.shape):
                raise ComputationError('Iteration body changes state type/shape')
            result = first if op == 'iterate' else TypeShape(first.dtype, (args[1].shape[0], *first.shape))
        elif op == 'elementwise':
            if body.shape:
                raise ComputationError('elementwise body must return scalar')
            result = TypeShape(body.dtype, first.shape)
        else:
            result = TypeShape(body.dtype, (first.shape[0], *body.shape))
        if len(result.shape) > 2:
            raise ComputationError('Operation output rank exceeds 2')
        return result
    if op == 'where':
        if args[0].dtype != 'boolean' or args[1].dtype != args[2].dtype:
            raise ComputationError('where needs a boolean condition and matching branch types')
        return TypeShape(args[1].dtype, _shape_merge(*args))
    if op in {'equal', 'not_equal'}:
        if args[0].dtype != args[1].dtype:
            raise ComputationError('Comparison operand types differ')
        return TypeShape('boolean', _shape_merge(*args))
    if op in {'and', 'or', 'not'}:
        if any(a.dtype != 'boolean' for a in args):
            raise ComputationError('Logic requires boolean operands')
        return TypeShape('boolean', _shape_merge(*args))
    if op in {'less', 'less_equal', 'greater', 'greater_equal'}:
        numeric(*args)
        return TypeShape('boolean', _shape_merge(*args))
    if op in {'add', 'subtract', 'multiply', 'divide', 'pow', 'clip'}:
        numeric(*args)
        return TypeShape('numeric', _shape_merge(*args))
    if op in {'negate', 'sqrt', 'exp', 'log', 'log2', 'abs', 'sin', 'cos'}:
        numeric(*args)
        return args[0]
    if op in {'dot', 'matmul', 'transpose'}:
        numeric(*args)
        a = args[0].shape
        if op == 'transpose':
            if len(a) != 2:
                raise ComputationError('transpose requires matrix')
            return TypeShape('numeric', (a[1], a[0]))
        b = args[1].shape
        if op == 'dot':
            if len(a) != 1 or not _shape_compatible(a, b):
                raise ComputationError('dot requires compatible vectors')
            return TypeShape('numeric', ())
        if len(a) != 2 or len(b) != 2 or not _shape_compatible((a[1],), (b[0],)):
            raise ComputationError('matmul requires compatible matrices')
        return TypeShape('numeric', (a[0], b[1]))
    if op == 'index':
        numeric(args[1])
        if not args[0].shape or args[1].shape:
            raise ComputationError('index requires array and scalar index')
        return TypeShape(args[0].dtype, args[0].shape[1:])
    if op == 'flatten':
        dims = args[0].shape
        n = None if None in dims else int(np.prod(dims))
        return TypeShape(args[0].dtype, (n,))
    if op == 'reshape':
        shape = p.get('shape')
        if not isinstance(shape, list) or not 1 <= len(shape) <= 2 or any(type(n) is not int or n < 1 for n in shape):
            raise ComputationError('Invalid reshape dimensions')
        if None not in args[0].shape and np.prod(args[0].shape) != np.prod(shape):
            raise ComputationError('reshape size mismatch')
        return TypeShape(args[0].dtype, tuple(shape))
    if op == 'slice':
        if not args[0].shape:
            raise ComputationError('slice requires array')
        if 'end_ref' in p:
            numeric(types[p['end_ref']])
            if types[p['end_ref']].shape:
                raise ComputationError('Slice endpoint must be scalar')
        n = args[0].shape[0]
        length = None
        if n is not None and 'end_ref' not in p:
            normalized = _slice_params(p)
            start, stop, step = slice(normalized.get('start'), normalized.get('stop'), normalized.get('step')).indices(n)
            length = len(range(start, stop, step))
        return TypeShape(args[0].dtype, (length, *args[0].shape[1:]))
    if op == 'concat':
        dims = [a.shape or (1,) if p.get('promote_scalars') else a.shape for a in args]
        if not dims[0] or any(len(s) != len(dims[0]) for s in dims):
            raise ComputationError('concat requires arrays of equal rank')
        if any(a.dtype != args[0].dtype for a in args):
            raise ComputationError('concat operand types differ')
        ax = p.get('axis', 0)
        if type(ax) is not int or not -len(dims[0]) <= ax < len(dims[0]):
            raise ComputationError('concat axis invalid')
        ax %= len(dims[0])
        for s in dims[1:]:
            if not _shape_compatible(dims[0][:ax] + dims[0][ax+1:], s[:ax] + s[ax+1:]):
                raise ComputationError('concat shape mismatch')
        total = None if any(s[ax] is None for s in dims) else sum(s[ax] for s in dims)
        return TypeShape(args[0].dtype, (*dims[0][:ax], total, *dims[0][ax+1:]))
    numeric(*args)
    if op == 'range':
        if any(a.shape for a in args):
            raise ComputationError('range requires scalar arguments')
        return TypeShape('numeric', (None,))
    ax = axis()
    dims = args[0].shape
    if op in {'sum', 'product', 'mean', 'min', 'max', 'argmin', 'argmax'}:
        return TypeShape('numeric', () if ax is None else dims[:ax] + dims[ax+1:])
    if op == 'softmax_rows' and len(dims) != 2:
        raise ComputationError('softmax_rows requires matrix')
    if op in {'softmax', 'softmax_rows', 'normalize'}:
        return args[0]
    if op in {'cumsum', 'difference'}:
        out = list(dims if ax is not None else (None if None in dims else int(np.prod(dims)),))
        if op == 'difference':
            dim = ax if ax is not None else 0
            if out[dim] is not None:
                out[dim] = max(out[dim] - 1, 0)
        return TypeShape('numeric', tuple(out))
    raise ComputationError(f'Cannot infer operation {op}')


def validate_types_shapes(spec: PaperMechanismIR) -> dict[str, TypeShape]:
    """Static propagation checks both conditional branches, without executing math."""
    order, _ = graph_order(spec.computation, {c.id for c in spec.controls})
    types = {c.id: _literal_type(c.default) for c in spec.controls}
    nodes = {n.id: n for n in spec.computation.nodes}
    for name in order:
        node = nodes[name]
        inferred = _infer_expression(node, types)
        if node.kind and ('vector' if node.kind == 'sequence' else node.kind) != inferred.kind:
            raise ComputationError(f'{name}: static declared kind mismatch')
        if node.shape is not None and not _shape_compatible(tuple(node.shape), inferred.shape):
            raise ComputationError(f'{name}: static declared shape mismatch')
        types[name] = inferred
    return types


class Evaluator:
    def __init__(self):
        self.steps = 0

    def expression(self, expr: Any, values: Mapping[str, Any], mask: Any = None, depth: int = 0) -> Any:
        self.steps += 1
        if self.steps > MAX_STEPS or depth > MAX_DEPTH:
            raise ComputationError('Execution step/depth limit exceeded')
        e = _dict(expr)
        if 'ref' in e:
            if e['ref'] not in values:
                raise ComputationError(f'Unknown reference: {e["ref"]}')
            return values[e['ref']]
        if 'const' in e:
            return e['const']
        op, inputs, params = e['op'], e['inputs'], e.get('params', {})
        if op == 'where':
            condition = _boolean(self.expression(inputs[0], values, mask, depth + 1))
            if condition.ndim == 0:
                return self.expression(inputs[1 if bool(condition) else 2], values, mask, depth + 1)
            active = np.ones(condition.shape, dtype=bool) if mask is None else np.broadcast_to(mask, condition.shape)
            # Only active elements have to satisfy a branch's numerical domain.
            a = self.expression(inputs[1], values, active & condition, depth + 1) if np.any(active & condition) else None
            b = self.expression(inputs[2], values, active & ~condition, depth + 1) if np.any(active & ~condition) else None
            # Reuse the selected value for an entirely inactive branch. A numeric
            # zero placeholder would promote boolean arrays to integers in where.
            if a is None:
                a = b if b is not None else 0
            if b is None:
                b = a
            _broadcast(condition, _array(a), _array(b))
            return _json(np.where(condition, a, b))
        args = [self.expression(x, values, mask, depth + 1) for x in inputs]
        if op == 'slice' and 'end_ref' in params:
            params = {**params, 'stop': self.expression({'ref': params['end_ref']}, values, depth=depth + 1)}
        if op in {'map', 'elementwise', 'iterate', 'scan'}:
            return self._bounded(op, args, params, values, depth)
        try:
            with np.errstate(all='ignore'):
                result = self._operation(op, args, params, mask)
        except ComputationError:
            raise
        except (ValueError, TypeError, IndexError, OverflowError) as exc:
            raise ComputationError(f'{op}: {exc}') from exc
        _finite(result)
        return _json(result)

    def _bounded(self, op, args, params, values, depth):
        if op in {'map', 'elementwise'}:
            a = _array(args[0])
            if a.ndim == 0:
                raise ComputationError(f'{op}: array required')
            items = a.reshape(-1) if op == 'elementwise' else a
            # Reject statically known oversized results before executing any body.
            scope = {name: _literal_type(value) for name, value in values.items()}
            scope['item'] = TypeShape(_literal_type(args[0]).dtype, () if op == 'elementwise' else a.shape[1:])
            scope['index'] = TypeShape('numeric', ())
            inferred = _infer_expression(params['body'], scope)
            _check_map_projection(op, len(items), inferred.shape)
            if not len(items):
                return _json(a.copy()) if op == 'elementwise' else []
            out, body_shape = [], None
            for i, item in enumerate(items):
                candidate = self.expression(params['body'], {**values, 'item': _json(item), 'index': i}, depth=depth + 1)
                candidate_shape = _array(candidate).shape
                # Dynamic dimensions become concrete after one bounded body.
                # Project before retaining it; later bodies must stay rectangular.
                _check_map_projection(op, len(items), candidate_shape)
                if body_shape is not None and candidate_shape != body_shape:
                    raise ComputationError('map body result shape changed')
                body_shape = candidate_shape
                out.append(candidate)
            result = _array(out)
            if op == 'elementwise':
                if result.size != a.size:
                    raise ComputationError('elementwise body must return a scalar')
                result = result.reshape(a.shape)
            _finite(result)
            return _json(result)
        initial, count_or_items = args
        if op == 'iterate':
            count = _integer(count_or_items, 'iteration count')
            items = range(count)
        else:
            sequence = _array(count_or_items)
            if sequence.ndim != 1:
                raise ComputationError('scan requires a vector')
            count = len(sequence)
            items = sequence
        if not 0 <= count <= MAX_ITERATIONS:
            raise ComputationError('Iteration count must be between 0 and 100')
        state, history = initial, []
        for i, item in enumerate(items):
            local = {**values, 'state': state, 'index': i}
            if op == 'scan':
                local['item'] = _json(item)
            candidate = self.expression(params['body'], local, depth=depth + 1)
            if value_type(candidate) != value_type(initial):
                raise ComputationError('Iteration state type/shape changed')
            _finite(candidate)
            state = candidate
            history.append(state)
        return state if op == 'iterate' else _json(_array(history))

    def _operation(self, op: str, args: list, p: dict, mask: Any) -> Any:
        binary = {'add': np.add, 'subtract': np.subtract, 'multiply': np.multiply,
                  'divide': np.divide, 'pow': np.power, 'equal': np.equal, 'not_equal': np.not_equal,
                  'less': np.less, 'less_equal': np.less_equal, 'greater': np.greater, 'greater_equal': np.greater_equal,
                  'and': np.logical_and, 'or': np.logical_or}
        unary = {'negate': np.negative, 'sqrt': np.sqrt, 'exp': np.exp, 'log': np.log,
                 'log2': np.log2, 'abs': np.abs, 'sin': np.sin, 'cos': np.cos, 'not': np.logical_not}
        if op in binary:
            if op in {'and', 'or'}:
                a, b = map(_boolean, args)
            elif op in {'equal', 'not_equal'}:
                a, b = map(_array, args)
                if a.dtype.kind != b.dtype.kind and not (a.dtype.kind in 'iuf' and b.dtype.kind in 'iuf'):
                    raise ComputationError('Comparison types differ')
            else:
                a, b = map(_numeric, args)
            _broadcast(a, b)
            if mask is not None and op in {'divide', 'pow'}:
                a, b = np.where(mask, a, 1), np.where(mask, b, 1)
            if op == 'divide' and np.any(b == 0):
                raise ComputationError('Division by zero')
            return binary[op](a, b)
        if op in unary:
            a = _boolean(args[0]) if op == 'not' else _numeric(args[0])
            if mask is not None and op in {'log', 'log2', 'sqrt', 'exp'}:
                a = np.where(mask, a, 1)
            if op in {'log', 'log2'} and np.any(a <= 0):
                raise ComputationError('Logarithm requires positive input; guard zero with where')
            if op == 'sqrt' and np.any(a < 0):
                raise ComputationError('Square root requires nonnegative input')
            return unary[op](a)
        if op == 'clip':
            a, low, high = map(_numeric, args)
            _broadcast(a, low, high)
            if np.any(low > high):
                raise ComputationError('Clip bounds are reversed')
            return np.minimum(np.maximum(a, low), high)
        if op in {'dot', 'matmul', 'transpose'}:
            a = _numeric(args[0])
            if op == 'transpose':
                if a.ndim != 2:
                    raise ComputationError('transpose requires a matrix')
                return a.T
            b = _numeric(args[1])
            if op == 'dot':
                if a.ndim != 1 or b.ndim != 1 or a.shape != b.shape:
                    raise ComputationError('dot requires equal-length vectors')
                return _sum_sequence(a * b)
            if a.ndim != 2 or b.ndim != 2 or a.shape[1] != b.shape[0]:
                raise ComputationError('matmul requires compatible matrices')
            if a.shape[0] * b.shape[1] > MAX_ELEMENTS:
                raise ComputationError('Matrix output exceeds size limit')
            return np.asarray([[_sum_sequence(row * column) for column in b.T] for row in a])
        if op == 'range':
            vals = [_integer(x, 'range argument') for x in args]
            start, stop, step = (0, vals[0], 1) if len(vals) == 1 else (vals[0], vals[1], vals[2] if len(vals) == 3 else 1)
            if step == 0:
                raise ComputationError('range step cannot be zero')
            r = range(start, stop, step)
            if len(r) > MAX_ELEMENTS:
                raise ComputationError('range exceeds size limit')
            return list(r)
        if op == 'concat':
            arrays = [_array(a) for a in args]
            if p.get('promote_scalars', False):
                arrays = [a.reshape(1) if a.ndim == 0 else a for a in arrays]
            axis = self._axis(p, arrays[0], default=0)
            return np.concatenate(arrays, axis=axis)
        a = _array(args[0])
        if op == 'index':
            index = _integer(args[1], 'index')
            if a.ndim == 0 or not -len(a) <= index < len(a):
                raise ComputationError('Index out of bounds')
            return a[index]
        if op == 'slice':
            if a.ndim == 0:
                raise ComputationError('slice requires an array')
            p = _slice_params(p)
            return a[slice(p.get('start'), p.get('stop'), p.get('step'))]
        if op == 'flatten':
            return a.reshape(-1)
        if op == 'reshape':
            shape = p.get('shape')
            if not isinstance(shape, list) or not 1 <= len(shape) <= 2 or any(type(n) is not int or n < 1 for n in shape):
                raise ComputationError('reshape requires positive integer shape of rank 1 or 2')
            return a.reshape(shape)
        a = _numeric(args[0])
        if a.size == 0:
            raise ComputationError(f'{op}: empty input')
        axis = self._axis(p, a, default=None)
        if op == 'sum':
            return _sum_array(a, axis)
        if op == 'mean':
            return _sum_array(a, axis) / (a.size if axis is None else a.shape[axis])
        reductions = {'product': np.prod, 'min': np.min, 'max': np.max,
                      'argmin': np.argmin, 'argmax': np.argmax}
        if op in reductions:
            return reductions[op](a, axis=axis)
        if op == 'cumsum':
            return _cumsum_sequence(a.reshape(-1)) if axis is None else np.apply_along_axis(_cumsum_sequence, axis, a)
        if op == 'difference':
            return np.diff(a.reshape(-1) if axis is None else a, axis=0 if axis is None else axis)
        if op == 'softmax_rows':
            if a.ndim != 2:
                raise ComputationError('softmax_rows requires a matrix')
            axis = 1
        if op in {'softmax', 'softmax_rows'}:
            exps = np.exp(a - np.max(a, axis=axis, keepdims=True))
            return exps / _sum_array(exps, axis=axis, keepdims=True)
        if op == 'normalize':
            total = _sum_array(a, axis=axis, keepdims=True)
            if np.any(total == 0):
                raise ComputationError('Cannot normalize zero-total input')
            return a / total
        raise ComputationError(f'Unknown operation: {op}')

    @staticmethod
    def _axis(p: dict, a: np.ndarray, default: int | None):
        axis = p.get('axis', default)
        if axis is not None:
            if type(axis) is not int or not -a.ndim <= axis < a.ndim:
                raise ComputationError('Invalid axis')
            axis %= a.ndim
        return axis


def evaluate(spec: PaperMechanismIR | dict, inputs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return all control and node values as JSON-compatible native values."""
    spec = spec if isinstance(spec, PaperMechanismIR) else PaperMechanismIR.model_validate(spec)
    controls = {c.id: c for c in spec.controls}
    if len(controls) != len(spec.controls):
        raise ComputationError('Duplicate control IDs')
    if set(inputs or {}) - set(controls):
        raise ComputationError('Unknown input control')
    values = {c.id: (inputs or {}).get(c.id, c.default) for c in spec.controls}
    for name, c in controls.items():
        validate_control_value(c, values[name])
    order, _ = graph_order(spec.computation, set(controls))
    validate_types_shapes(spec)
    nodes = {n.id: n for n in spec.computation.nodes}
    engine = Evaluator()
    for name in order:
        node = nodes[name]
        result = engine.expression(node, values)
        _finite(result)
        actual = value_type(result)
        if node.kind and actual['kind'] != ('vector' if node.kind == 'sequence' else node.kind):
            raise ComputationError(f'{name}: declared kind does not match result')
        if node.shape is not None and node.shape != actual['shape']:
            raise ComputationError(f'{name}: declared shape does not match result')
        values[name] = result
    return values


def infer_types_shapes(spec: PaperMechanismIR, inputs: Mapping[str, Any] | None = None) -> dict[str, dict]:
    """Infer checked concrete types/shapes at a supplied state (defaults otherwise)."""
    return {name: value_type(value) for name, value in evaluate(spec, inputs).items()}


def evaluate_expression(expr: dict, values: Mapping[str, Any] | None = None) -> Any:
    _refs(expr)
    return Evaluator().expression(expr, values or {})
