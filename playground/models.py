"""PaperMechanismIR v1.0. Scientific expressions are data, never executable code."""
from __future__ import annotations

import math
from typing import Annotated, Any, Literal, Union

from pydantic import (AliasChoices, BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator,
                      model_validator)

ValueKind = Literal['scalar', 'vector', 'matrix', 'sequence', 'boolean', 'categorical']
ControlType = Literal['slider', 'number', 'checkbox', 'select', 'vector_editor', 'matrix_editor', 'sequence_editor']


def check_literal(value: Any) -> Any:
    """Accept bounded JSON values, rejecting Python objects and nonfinite numbers."""
    count = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if count > 10000 or depth > 32:
            raise ValueError('Literal exceeds size/depth limit')
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif type(item) not in (str, int, float, bool):
            raise ValueError('Values must be numbers, booleans, strings, or arrays')
        elif isinstance(item, (int, float)):
            try:
                finite = math.isfinite(item)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError('Numeric values must be finite')

    visit(value, 0)
    return value


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Case(BaseModel):
    model_config = ConfigDict(extra='allow')
    source_url: str = Field(min_length=1)
    focus: str = Field(min_length=1)
    audience: str = Field(min_length=1)


class SourceBlock(Contract):
    id: str = Field(min_length=1)
    type: Literal['heading', 'paragraph', 'equation', 'algorithm', 'table', 'list', 'caption']
    text: str = Field(min_length=1)
    section: str | None = None
    section_number: str | None = None
    equation_number: str | None = None
    page: int | None = Field(default=None, ge=1)
    order: int


class SourceDocument(Contract):
    source_url: str
    title: str | None = None
    raw_text: str | None = None
    blocks: list[SourceBlock] = Field(default_factory=list)
    origin: Literal['supplied', 'local', 'url']


class FocusedEvidence(Contract):
    blocks: list[SourceBlock]
    focus: str
    audience: str


class TeachingSpec(Contract):
    title: str = Field(min_length=1)
    idea: str = Field(min_length=1)
    why: str = Field(min_length=1)
    mental_model: str = Field(min_length=1)


class EvidenceClaim(Contract):
    id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    blocks: list[str] = Field(min_length=1)


class ProvenanceSpec(Contract):
    simplifications: list[str] = Field(default_factory=list)
    toy_examples: list[str] = Field(default_factory=list)


class SymbolSpec(Contract):
    symbol: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    kind: ValueKind
    units: str | None = None


class ControlSpec(Contract):
    id: str = Field(min_length=1)
    type: ControlType
    label: str = Field(min_length=1)
    help: str | None = None
    value_kind: ValueKind
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = Field(default=None, gt=0)
    options: list[Any] | None = None
    shape: list[int] | None = None

    _literal = field_validator('default')(check_literal)

    @model_validator(mode='after')
    def bounds(self):
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError('min exceeds max')
        if self.shape is not None and (not self.shape or any(n < 1 for n in self.shape)):
            raise ValueError('Shape dimensions must be positive')
        return self


class Reference(Contract):
    ref: str = Field(min_length=1)


class Constant(Contract):
    const: Any
    _literal = field_validator('const')(check_literal)


def operand_tag(value: Any) -> str | None:
    """Pick the operand form by its key so schema errors name one real IR path."""
    if isinstance(value, BaseModel):
        value = value.model_dump()
    if not isinstance(value, dict):
        return None
    return next((key for key in ('op', 'ref', 'const') if key in value), None)


OPERAND_TAGS = ('op', 'ref', 'const')

Operand = Annotated[
    Union[Annotated[Reference, Tag('ref')], Annotated[Constant, Tag('const')], Annotated['Expression', Tag('op')]],
    Discriminator(operand_tag, custom_error_type='invalid_operand',
                  custom_error_message='Operand must be {"ref": id}, {"const": value}, or {"op": name, "inputs": [...]}'),
]


class Expression(Contract):
    op: str = Field(min_length=1)
    inputs: list[Operand] = Field(max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)


class ComputationNode(Expression):
    id: str = Field(min_length=1)
    kind: ValueKind | None = None
    shape: list[int] | None = None
    display: bool = False
    label: str | None = None
    format: str | None = None


class ComputationSpec(Contract):
    nodes: list[ComputationNode] = Field(min_length=1, max_length=256)
    outputs: list[str] = Field(min_length=1)


class MechanismGrounding(Contract):
    nodes: list[str] = Field(min_length=1)
    blocks: list[str] = Field(min_length=1)
    relationship: str = Field(min_length=1)


class VisualSpec(Contract):
    # Unknown types are retained so Person 3 can resolve a deterministic fallback.
    type: str = Field(min_length=1)
    title: str | None = None
    value: str | None = None
    bindings: dict[str, str] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class ExplorationChange(Contract):
    instructions: str = Field(min_length=1)
    suggested_values: dict[str, Any]


class ExpectationSpec(Contract):
    type: Literal['increases', 'decreases', 'approx', 'greater_than', 'greater_equal',
                  'less_than', 'less_equal', 'becomes_uniform', 'argmax_changes',
                  'sum_to', 'rows_sum_to', 'nonnegative']
    value: str
    expected: Any = None
    tolerance: float = Field(default=1e-6, ge=0)


class ExplorationSpec(Contract):
    title: str = Field(min_length=1)
    change: ExplorationChange
    observe: str = Field(min_length=1)
    why: str = Field(min_length=1)
    expectation: ExpectationSpec | None = None


class LimitationSpec(Contract):
    kind: Literal['assumption', 'limitation', 'misconception', 'simplification']
    text: str = Field(min_length=1)


class AssertionSpec(Contract):
    op: Literal['equals', 'approx', 'greater_than', 'greater_equal', 'less_than',
                  'less_equal', 'all_finite', 'nonnegative', 'sum_to', 'rows_sum_to',
                  'shape_equals', 'range', 'monotonic', 'argmax_equals'] = Field(validation_alias=AliasChoices('op', 'type'))
    value: str | None = None
    expected: Any = None
    tolerance: float = Field(default=1e-6, ge=0)
    min: float | None = None
    max: float | None = None
    direction: Literal['increasing', 'decreasing'] = 'increasing'

    @field_validator('tolerance', mode='before')
    @classmethod
    def default_tolerance(cls, value):
        return 1e-6 if value is None else value


class TestCaseSpec(Contract):
    name: str = Field(min_length=1)
    inputs: dict[str, Any]
    assertions: list[AssertionSpec] = Field(min_length=1)


class InvariantSpec(Contract):
    name: str = Field(min_length=1)
    value: str
    assertion: AssertionSpec


class PaperMechanismIR(Contract):
    schema_version: Literal['1.0']
    teaching: TeachingSpec
    evidence: list[EvidenceClaim]
    provenance: ProvenanceSpec
    symbols: list[SymbolSpec]
    controls: list[ControlSpec] = Field(max_length=32)
    computation: ComputationSpec
    mechanism_grounding: list[MechanismGrounding]
    visuals: list[VisualSpec]
    explorations: list[ExplorationSpec]
    limitation: LimitationSpec
    tests: list[TestCaseSpec] = Field(default_factory=list, max_length=100)
    invariants: list[InvariantSpec] = Field(default_factory=list, max_length=100)


class ValidationFailure(Contract):
    check: str
    severity: Literal['fatal', 'serious', 'recoverable', 'warning']
    path: str | None = None
    message: str
    repairable: bool
    allowed_paths: list[str] = Field(default_factory=list)


class ValidationResult(Contract):
    ok: bool
    failures: list[ValidationFailure] = Field(default_factory=list)
    warnings: list[ValidationFailure] = Field(default_factory=list)
    rubric_summary: dict[str, Any] = Field(default_factory=dict)
    checks: list[dict[str, Any]] = Field(default_factory=list)


class DerivedPlayground(Contract):
    spec: PaperMechanismIR
    dependency_graph: dict[str, list[str]]
    evaluated_defaults: dict[str, Any]
    visible_nodes: set[str]
    resolved_visuals: list[Any] = Field(default_factory=list)
    rubric_summary: dict[str, Any] = Field(default_factory=dict)


Expression.model_rebuild()
ComputationNode.model_rebuild()
