"""Person 3's bounded presentation grammar. Does not validate scientific IR."""
from __future__ import annotations

import math

LAYOUTS = {"split", "stack", "grid", "visual_first", "equation_first", "pipeline", "focus"}
STORIES = {"equation_to_effect", "input_to_output", "build_it_step_by_step",
           "compare_two_cases", "cause_and_effect", "before_and_after",
           "iterate_and_observe", "distribution_story", "spatial_story"}
PRESENTATIONS = {"matrix", "heatmap", "number", "metric", "vector", "table",
                 "bar_chart", "line_chart", "scatter"}
STAGE_LAYOUTS = {"controls_left_visual_right", "controls_left", "controls_right",
                 "side_by_side", "stacked", "visual_first", "equation_first",
                 "comparison", "pipeline", "focus", "dashboard", "spatial"}
SHARED_FIELDS = {"story", "layout", "hero_visual", "calculation_order", "emphasis_nodes", "guided_mode", "annotations"}
SHARED_STORIES = {"equation_to_effect", "input_to_output", "build_step_by_step", "cause_and_effect",
                  "compare_cases", "iterate_and_observe", "distribution_story", "spatial_story"}
SHARED_LAYOUTS = {"visual_first", "equation_first", "controls_left", "controls_right", "comparison", "pipeline", "focus", "dashboard"}
COMPONENT_IDS = {"teaching", "idea", "why", "mental_model", "symbols", "controls", "main_visual",
                 "equation", "intermediates", "what_changed", "explorations", "limitation", "source_grounding"}


class ExperienceError(ValueError):
    pass


def derive_visual_ids(ir: dict) -> list[str]:
    """Person 2's final deterministic visual namespace (presentation only)."""
    reserved = {v.get("id") for v in ir.get("visuals", []) if v.get("id")}
    used, result = set(), []
    for i, visual in enumerate(ir.get("visuals", [])):
        candidate = visual.get("id") or f"visual_{i}"
        base, suffix = candidate, 1
        while candidate in used or (not visual.get("id") and candidate in reserved):
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        result.append(candidate)
    return result


def visual_registry(ir: dict, visual_ids: list[str] | None = None) -> dict:
    """Use resolved shared IDs, or legacy references for local authoring plans."""
    if visual_ids is not None:
        if len(visual_ids) != len(ir.get("visuals", [])) or len(set(visual_ids)) != len(visual_ids):
            raise ExperienceError("Invalid resolved visual IDs")
        return dict(zip(visual_ids, ir.get("visuals", [])))
    result = {}
    for i, visual in enumerate(ir.get("visuals", [])):
        key = visual.get("id") or visual.get("value") or f"{visual.get('type')}_{i}"
        if key in result:
            key = f"{key}_{i}"
        result[key] = visual
    return result


def compile_experience(ir: dict, experience: dict | None = None, *, visual_ids: list[str] | None = None,
                       shared: bool | None = None) -> dict:
    """Invalid/absent experience returns canonical mode; leaves the IR unchanged.

    Shared ExperienceSpec is presentation data; explicit overrides additionally
    support Person-3-local composition. Scientific validation stays upstream.
    """
    raw = experience if experience is not None else ir.get("experience")
    if raw is None:
        return {"mode": "canonical", "reason": "absent"}
    try:
        if shared is None:
            shared = experience is None
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(mode="json")
        if shared:
            visual_ids = visual_ids if visual_ids is not None else derive_visual_ids(ir)
            raw = _shared_experience(ir, raw, visual_ids)
        return {"mode": "directed", "contract": "shared" if shared else "internal",
                "plan": _compile(ir, raw, visual_ids if shared else None)}
    except (ExperienceError, TypeError, KeyError, RecursionError) as exc:
        return {"mode": "canonical", "reason": str(exc)}


def _shared_experience(ir: dict, raw: dict, visual_ids: list[str]) -> dict:
    """Reject upstream extensions; respect the final presentation namespace."""
    if not isinstance(raw, dict) or set(raw) - SHARED_FIELDS:
        raise ExperienceError("Unsupported shared ExperienceSpec fields")
    raw = dict(raw)
    for field, choices in (("story", SHARED_STORIES), ("layout", SHARED_LAYOUTS)):
        if raw.get(field) is None:
            raw.pop(field, None)
        elif not isinstance(raw[field], str) or raw[field] not in choices:
            raise ExperienceError("Unsupported shared presentation choice")
    visuals = visual_registry(ir, visual_ids)
    nodes = {n["id"] for n in ir.get("computation", {}).get("nodes", [])}
    controls = {c["id"] for c in ir.get("controls", [])}
    explicit = [v["id"] for v in ir.get("visuals", []) if v.get("id")]
    if len(explicit) != len(set(explicit)) or set(visuals) & COMPONENT_IDS:
        raise ExperienceError("Ambiguous visual IDs")
    targets = nodes | controls | set(visuals) | COMPONENT_IDS
    ambiguous = (nodes | controls) & (set(visuals) | COMPONENT_IDS)
    focus = raw.get("hero_visual")
    if focus is None:
        raw.pop("hero_visual", None)
    elif not isinstance(focus, str) or focus not in visuals:
        raise ExperienceError("Hero must reference a shared visual ID")
    for field in ("calculation_order", "emphasis_nodes"):
        entries = raw.get(field, [])
        if not isinstance(entries, list) or len(entries) > 256 or any(not isinstance(n, str) or n not in nodes for n in entries) or len(entries) != len(set(entries)):
            raise ExperienceError("Invalid shared node references")
    for field, fields in (("guided_mode", {"target", "instruction"}), ("annotations", {"target", "kind", "text"})):
        entries = raw.get(field, [])
        if not isinstance(entries, list) or len(entries) > 100:
            raise ExperienceError("Invalid shared presentation list")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != fields:
                raise ExperienceError("Invalid shared presentation record")
            target = entry["target"]
            if not isinstance(target, str) or target not in targets or target in ambiguous:
                raise ExperienceError("Unknown or ambiguous shared target")
            text = entry.get("instruction", entry.get("text"))
            if not isinstance(text, str) or not text:
                raise ExperienceError("Invalid shared presentation text")
            if field == "annotations" and entry["kind"] not in {"callout", "hint", "warning", "insight"}:
                raise ExperienceError("Invalid shared annotation kind")
    return raw


def _compile(ir: dict, raw: dict, visual_ids: list[str] | None = None) -> dict:
    def obj(value, allowed):
        if not isinstance(value, dict) or set(value) - set(allowed):
            raise ExperienceError("Unsupported presentation fields")
        return value

    def string(value):
        if not isinstance(value, str) or (visual_ids is None and len(value) > 2000):
            raise ExperienceError("Presentation text must be bounded plain text")
        return value

    def choice(value, allowed):
        if isinstance(value, bool) or not isinstance(value, (str, int)) or value not in allowed:
            raise ExperienceError("Unsupported presentation choice")
        return value

    def items(value, maximum=32):
        if not isinstance(value, list) or len(value) > maximum:
            raise ExperienceError("Presentation list exceeds its bound")
        return value

    controls = {c["id"] for c in ir.get("controls", [])}
    nodes = {n["id"] for n in ir.get("computation", {}).get("nodes", [])}
    values = controls | nodes
    visuals = visual_registry(ir, visual_ids)
    targets = values | set(visuals) | COMPONENT_IDS

    def ref(value, known):
        if not isinstance(value, str) or value not in known:
            raise ExperienceError("Unknown presentation reference")
        return value

    def condition(value):
        obj(value, {"value", "op", "threshold"})
        threshold = value.get("threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
            raise ExperienceError("Annotation threshold must be finite")
        return {"value": ref(value.get("value"), values),
                "op": choice(value.get("op"), {"less_than", "greater_than", "equal"}),
                "threshold": threshold}

    obj(raw, {"story", "hero", "interactive_stage", "calculation_story", "guided_mode",
              "annotations", "presentation", "tree", "layout", "hero_visual",
              "calculation_order", "emphasis_nodes"})
    raw = dict(raw)
    aliases = {"build_step_by_step": "build_it_step_by_step", "compare_cases": "compare_two_cases"}
    raw["story"] = aliases.get(raw.get("story"), raw.get("story", "input_to_output"))
    plan = {"story": choice(raw.get("story", "input_to_output"), STORIES)}
    presentation = obj(raw.get("presentation", {}), {"density", "hero_emphasis", "interaction_style", "comparison_mode"})
    plan["density"] = choice(presentation.get("density", "comfortable"), {"focused", "comfortable", "compact"})
    plan["interaction_style"] = choice(presentation.get("interaction_style", "freeform"), {"freeform", "stepwise"})
    plan["hero_emphasis"] = choice(presentation.get("hero_emphasis", "visual"), {"visual", "relationship", "metric"})
    comparison = presentation.get("comparison_mode", False)
    if not isinstance(comparison, bool):
        raise ExperienceError("Comparison mode must be boolean")
    plan["comparison_mode"] = comparison
    available_focus = [key for key, v in visuals.items() if v.get("type") != "formula"]
    if available_focus:
        hint = raw.get("hero_visual")
        plan["primary_visual"] = hint if isinstance(hint, str) and hint in available_focus else available_focus[0]
    plan["emphasis_nodes"] = [ref(n, nodes) for n in items(raw.get("emphasis_nodes", []), 256)]
    if "calculation_order" in raw:
        if "calculation_story" in raw:
            raise ExperienceError("Use one calculation ordering directive")
        raw["calculation_story"] = [{"node": ref(n, nodes), "presentation": next(
            (v["type"] for v in visuals.values() if v.get("value") == n and v.get("type") in PRESENTATIONS),
            "table" if next(node for node in ir["computation"]["nodes"] if node["id"] == n).get("kind") in {"matrix", "vector", "sequence"} else "number")}
            for n in items(raw["calculation_order"], 256)]
    if "hero" in raw:
        hero = obj(raw["hero"], {"visual", "emphasis"})
        plan["hero"] = {"visual": ref(hero.get("visual"), visuals),
                        "emphasis": choice(hero.get("emphasis", plan["hero_emphasis"]), {"visual", "relationship", "metric"})}

    used_controls = []
    budget = 0
    visual_count = 0

    def tree(node, depth=0):
        nonlocal budget, visual_count
        budget += 1
        if budget > 64 or depth > 6:
            raise ExperienceError("Component tree exceeds its bound")
        obj(node, {"type", "children", "ratio", "columns", "controls", "visual", "value", "title", "text", "when"})
        kind = node.get("type")
        fields = {"type", "title"}
        if kind in LAYOUTS:
            fields.add("children")
            if kind == "split":
                fields.add("ratio")
            if kind == "grid":
                fields.add("columns")
        elif kind == "control_group":
            fields.add("controls")
        elif kind in {"visual", "comparison", "formula", "scene"}:
            fields.add("visual")
        elif kind in PRESENTATIONS:
            fields.add("value")
        elif kind == "callout":
            fields.update({"text", "when"})
        obj(node, fields)
        result = {"type": kind}
        if kind in LAYOUTS:
            children = items(node.get("children"), 12)
            if not children or (kind == "split" and len(children) != 2):
                raise ExperienceError("Layout has an unsupported child count")
            result["children"] = [tree(child, depth + 1) for child in children]
            if kind == "split":
                result["ratio"] = choice(node.get("ratio", "40/60"), {"40/60", "50/50", "60/40"})
            if kind == "grid":
                result["columns"] = choice(node.get("columns", 2), {1, 2, 3})
        elif kind == "control_group":
            result["controls"] = [ref(c, controls) for c in items(node.get("controls"))]
            used_controls.extend(result["controls"])
        elif kind in {"visual", "comparison", "formula", "scene"}:
            result["visual"] = ref(node.get("visual"), visuals)
            if kind in {"formula", "scene"} and visuals[result["visual"]].get("type") != kind:
                raise ExperienceError("Component does not match the referenced visual")
            if visuals[result["visual"]].get("type") not in {"formula", "number", "table"}:
                visual_count += 1
        elif kind in PRESENTATIONS:
            result["value"] = ref(node.get("value"), values)
            if kind not in {"number", "metric", "table"}:
                visual_count += 1
        elif kind in {"dependency_graph", "symbol_legend", "calculation_steps"}:
            if kind in {"dependency_graph", "calculation_steps"}:
                visual_count += 1
        elif kind == "callout":
            result["text"] = string(node.get("text"))
            if "when" in node:
                result["when"] = condition(node["when"])
        else:
            raise ExperienceError("Unsupported component")
        if "title" in node:
            result["title"] = string(node["title"])
        return result

    if "tree" in raw:
        plan["tree"] = tree(raw["tree"])
    else:
        stage = dict(obj(raw.get("interactive_stage", {}), {"layout", "primary_visual", "secondary_visuals"}))
        if "layout" in raw:
            stage["layout"] = raw["layout"]
        available = [key for key, v in visuals.items() if v.get("type") != "formula"]
        if not available:
            raise ExperienceError("Directed stage requires a visual")
        # A missing or invalid focus hint resolves deterministically; invalid
        # structural references still reject the advanced composition.
        focus = raw.get("hero_visual")
        focus_choices = visuals if visual_ids is not None else available
        primary = ref(stage.get("primary_visual", focus if isinstance(focus, str) and focus in focus_choices else available[0]), visuals)
        plan["primary_visual"] = primary
        secondary = [ref(v, visuals) for v in items(stage.get("secondary_visuals", []), 8)]
        if visuals[primary].get("type") in {"number", "table", "formula"} and not any(
                visuals[v].get("type") not in {"number", "table", "formula"} for v in secondary):
            supporting = next((v for v in available if visuals[v].get("type") not in {"number", "table", "formula"}), None)
            if supporting:
                secondary.append(supporting)
        default_layout = {"distribution_story": "visual_first", "equation_to_effect": "equation_first",
                          "before_and_after": "comparison", "compare_two_cases": "comparison",
                          "spatial_story": "spatial", "build_it_step_by_step": "pipeline"}.get(plan["story"], "controls_left_visual_right")
        layout = choice(stage.get("layout", default_layout), STAGE_LAYOUTS)
        group = {"type": "control_group", "controls": [c["id"] for c in ir.get("controls", [])]}
        view = {"type": "stack", "children": [{"type": "visual", "visual": key} for key in [primary, *secondary]]}
        if layout == "comparison":
            view = {"type": "comparison", "visual": primary}
            if secondary:
                view = {"type": "stack", "children": [view, *[
                    {"type": "visual", "visual": key} for key in secondary]]}
        elif comparison:
            view["children"].append({"type": "comparison", "visual": primary})
        if layout in {"controls_right", "visual_first"}:
            children = [view, group]
        else:
            children = [group, view]
        root_type = "split" if layout in {"controls_left_visual_right", "controls_left", "controls_right", "side_by_side", "comparison"} else "stack"
        if layout in {"dashboard", "spatial"}:
            root_type = "grid"
        if layout in {"equation_first", "focus", "pipeline", "visual_first"}:
            root_type = layout
        if layout == "equation_first":
            formula = next((key for key, v in visuals.items() if v.get("type") == "formula"), None)
            if formula:
                children.insert(0, {"type": "formula", "visual": formula})
        plan["tree"] = tree({"type": root_type, "children": children})
    if len(used_controls) != len(set(used_controls)) or set(used_controls) != controls:
        raise ExperienceError("Every control must appear exactly once in the stage")
    if not visual_count:
        raise ExperienceError("Directed stage must retain a meaningful visualization")

    plan["calculation_story"] = []
    seen_nodes = set()
    for step in items(raw.get("calculation_story", []), 256):
        obj(step, {"node", "presentation", "annotation", "meaning"})
        node = ref(step.get("node"), nodes)
        if node in seen_nodes:
            raise ExperienceError("Duplicate calculation story node")
        seen_nodes.add(node)
        plan["calculation_story"].append({"node": node,
            "presentation": choice(step.get("presentation", "number"), PRESENTATIONS),
            "annotation": string(step.get("annotation", "")), "meaning": string(step.get("meaning", ""))})
    plan["guided_mode"] = []
    for step in items(raw.get("guided_mode", []), 100):
        obj(step, {"focus", "message", "target", "instruction", "highlight_dependency_path"})
        highlight = step.get("highlight_dependency_path", False)
        if not isinstance(highlight, bool):
            raise ExperienceError("Guide dependency focus must be boolean")
        plan["guided_mode"].append({"target": ref(step.get("target", step.get("focus")), targets),
                                   "instruction": string(step.get("instruction", step.get("message"))),
                                   "highlight_dependency_path": highlight})
    plan["annotations"] = []
    for note in items(raw.get("annotations", []), 100):
        try:
            obj(note, {"target", "kind", "text", "when"})
            normalized = {"target": ref(note.get("target"), targets),
                          "kind": choice(note.get("kind", "callout"), {"callout", "hint", "insight", "warning"}),
                          "text": string(note.get("text"))}
            if "when" in note:
                normalized["when"] = condition(note["when"])
            plan["annotations"].append(normalized)
        except (ExperienceError, TypeError):
            # Decorative metadata cannot disable an otherwise usable lesson.
            continue
    return plan
