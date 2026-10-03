"""Deterministic visual selection; browser renderers live in runtime/visuals.js."""

STANDARD_VISUALS = frozenset({
    "formula", "number", "table", "matrix", "heatmap", "bar_chart",
    "line_chart", "scatter", "vector", "pipeline", "nodes_edges", "scene",
})


def resolve_visual(visual: dict, values: dict) -> dict:
    """Preserve supported requests; degrade to data or the dependency diagram."""
    kind = visual.get("type")
    value = values.get(visual.get("value"))
    if kind in STANDARD_VISUALS:
        return dict(visual)
    if isinstance(value, list) and value:
        kind = "heatmap" if isinstance(value[0], list) else "bar_chart"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        kind = "number"
    else:
        kind = "pipeline"
    return {**visual, "type": kind, "fallback": True}
