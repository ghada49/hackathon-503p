"""Interactive Explanation Renderer: compile one standalone scientific artifact."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

from .experience import compile_experience, derive_visual_ids

ROOT = Path(__file__).resolve().parents[1]


def _mapping(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if not isinstance(value, dict):
        raise TypeError("Expected an IR dictionary or a Pydantic model")
    return value


def safe_json(value: Any) -> str:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False)
            .replace("&", "\\u0026").replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def render(ir: Any, evaluated_values: dict | None = None, *,
           evaluator_js: str | None = None, source: dict | None = None,
           experience: dict | None = None, dependency_graph: dict | None = None) -> str:
    """Return HTML. evaluator_js must be trusted application code, never LLM output.

    The embedded, unmodified Person 2 runtime is the default evaluator. Trusted
    custom adapters may set PlaygroundEvaluator.evaluate(ir, controls) -> values.
    """
    spec = _mapping(ir)
    visual_ids = None
    resolved = False
    if "spec" in spec and "evaluated_defaults" in spec:
        dependency_graph = dependency_graph if dependency_graph is not None else spec.get("dependency_graph")
        evaluated_values = evaluated_values if evaluated_values is not None else spec["evaluated_defaults"]
        visual_ids = spec.get("visual_ids") or None
        if experience is None and "resolved_experience" in spec:
            # Person 2's None is an authoritative canonical fallback, even when
            # the raw spec still contains a structurally invalid experience.
            resolved = True
            resolved_experience = spec["resolved_experience"]
        resolved_visuals = spec.get("resolved_visuals")
        spec = dict(_mapping(spec["spec"]))
        if resolved_visuals:
            # Recovery resolves presentation against this list and its parallel
            # visual_ids; the scientific spec and its validation stay unchanged.
            spec["visuals"] = resolved_visuals
    if evaluated_values is not None and hasattr(evaluated_values, "model_dump"):
        evaluated_values = evaluated_values.model_dump(mode="json")
    if isinstance(evaluated_values, dict) and "evaluated_defaults" in evaluated_values:
        evaluated_values = evaluated_values["evaluated_defaults"]
    visual_ids = visual_ids if visual_ids is not None else derive_visual_ids(spec)
    if resolved:
        presentation = ({"mode": "canonical", "reason": "upstream resolved_experience is None"}
                        if resolved_experience is None else
                        compile_experience(spec, resolved_experience, visual_ids=visual_ids, shared=True))
    else:
        # Explicit overrides are Person-3-local test/authoring plans. Only the
        # official seven fields are accepted from spec.experience.
        presentation = compile_experience(spec, experience, visual_ids=visual_ids,
                                          shared=experience is None)
    # Strip the uncompiled extension: invalid presentation data must not prevent
    # serializing the independently usable scientific IR (e.g. NaN in a threshold).
    science = {key: value for key, value in spec.items() if key != "experience"}
    source = dict(source or {})
    if not source.get("url") and source.get("source_url"):
        source["url"] = source["source_url"]
    payload = safe_json({"ir": science, "values": evaluated_values or {},
                         "source": source, "experience": presentation,
                         "dependencies": dependency_graph, "visual_ids": visual_ids})
    replacements = {
        "TITLE": html.escape(spec.get("teaching", {}).get("title", "Learn and explore")),
        "STYLE": ((ROOT / "templates/artifact.css").read_text(encoding="utf-8") + "\n" +
                  (ROOT / "templates/experience.css").read_text(encoding="utf-8") + "\n" +
                  (ROOT / "templates/notebook.css").read_text(encoding="utf-8")),
        "PAYLOAD": payload,
        "VISUALS": (ROOT / "runtime/visuals.js").read_text(encoding="utf-8"),
        "SCIENCE": (ROOT / "runtime/computation.js").read_text(encoding="utf-8"),
        "EXPERIENCE": (ROOT / "runtime/experience-runtime.js").read_text(encoding="utf-8"),
        "EVALUATOR": evaluator_js or "",
        "RUNTIME": (ROOT / "runtime/playground-runtime.js").read_text(encoding="utf-8"),
    }
    # A single substitution pass prevents user text containing a template marker
    # from being interpreted as a second template instruction.
    import re
    template = (ROOT / "templates/learn_explore.html").read_text(encoding="utf-8")
    return re.sub(r"\[\[([A-Z]+)\]\]", lambda m: replacements[m.group(1)], template)


def render_to_file(ir: Any, output: str | Path, **kwargs: Any) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(ir, **kwargs), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render validated IR or DerivedPlayground as standalone HTML")
    parser.add_argument("--input", "--fixture", dest="input", required=True,
                        help="JSON file containing validated IR or DerivedPlayground")
    parser.add_argument("--output", default="out/index.html")
    parser.add_argument("--values", help="JSON file of evaluated values from Person 2")
    parser.add_argument("--evaluator", help="Trusted JS file implementing PlaygroundEvaluator")
    parser.add_argument("--experience", help="Optional frontend experience JSON; does not change the science fixture")
    parser.add_argument("--source", help="Optional source metadata/SourceBlock JSON")
    parser.add_argument("--dependencies", help="Optional Person 2 transitive dependency graph JSON")
    args = parser.parse_args()
    fixture = json.loads(Path(args.input).read_text(encoding="utf-8"))
    evaluator = Path(args.evaluator).read_text(encoding="utf-8") if args.evaluator else None
    values = json.loads(Path(args.values).read_text(encoding="utf-8")) if args.values else None
    experience = json.loads(Path(args.experience).read_text(encoding="utf-8")) if args.experience else None
    source = json.loads(Path(args.source).read_text(encoding="utf-8")) if args.source else None
    dependencies = json.loads(Path(args.dependencies).read_text(encoding="utf-8")) if args.dependencies else None
    result = render_to_file(fixture, args.output, evaluator_js=evaluator,
                            evaluated_values=values, experience=experience, source=source,
                            dependency_graph=dependencies)
    print(result.resolve())


if __name__ == "__main__":
    main()
