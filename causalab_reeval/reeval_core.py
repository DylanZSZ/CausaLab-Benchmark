from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .context_replay import (
    extract_final_hypothesis,
    extract_legacy_success,
    extract_reactor_outcome,
    extract_task_scorecard,
    load_source_metadata,
    read_json,
    recover_phase1_context,
)
from .metrics import (
    FREQ_NODE,
    compute_directed_shd,
    compute_edge_metrics,
    compute_frequency_weight_metrics,
    evaluate_predicted_formula,
    extract_root_nodes_from_edges,
    extract_true_root_nodes_for_frequency,
    frequency_parent_edges,
    prf,
    true_edges_from_graph_config,
)


SYSTEM_JSON_ONLY = "Return only one strict JSON object. Do not add Markdown or extra text."


def _empty_graph_eval() -> Dict[str, Any]:
    return {"all_edge_metrics": {}, "all_edge_shd": {}, "freq_edge_metrics": {}, "freq_weight_metrics": {}}


def _parse_json_object(text: Any) -> Optional[Dict[str, Any]]:
    if isinstance(text, Mapping):
        return dict(text)
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except Exception:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(stripped[start : end + 1])
        except Exception:
            parsed = None
    if isinstance(parsed, Mapping):
        return dict(parsed)

    decoder = json.JSONDecoder()
    last_obj: Optional[Dict[str, Any]] = None
    idx = 0
    while True:
        start = stripped.find("{", idx)
        if start < 0:
            break
        try:
            candidate, end = decoder.raw_decode(stripped[start:])
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(candidate, Mapping):
            last_obj = dict(candidate)
        idx = start + max(end, 1)
    return last_obj


def build_root_formula_messages(phase1_prompt: str) -> list:
    user_prompt = (
        "You are playing a video game about making scientific discoveries.\n"
        "You are at the Causal Discovery Lab on Planet X.\n\n"
        "You have already explored how crystal properties affect resonance frequency.\n"
        "Keep the same setting, object names, and scientific assumptions as before.\n\n"
        "Below is the exact phase-1 action-generation prompt/context from that exploration.\n\n"
        "<phase1_prompt>\n"
        f"{phase1_prompt or ''}\n"
        "</phase1_prompt>\n\n"
        "=== NEW TASK ===\n"
        "Instead of choosing the next game action, answer this new task:\n"
        "1. List all root nodes that influence resonanceFreq. Root nodes mean nodes with no parents in the causal graph.\n"
        "2. Give one candidate formula that predicts resonanceFreq from those root nodes.\n\n"
        "Rules:\n"
        "- Use canonical property names from the prompt context when possible.\n"
        "- If you are unsure, still provide your best guess.\n"
        "- Output strict JSON only.\n"
        "- Return exactly one JSON object with exactly these two top-level keys: `root_nodes` and `frequency_formula`.\n"
        "- `root_nodes` must be a JSON array of strings.\n"
        "- `frequency_formula` must be parseable by Python expression parsing.\n"
        "- `frequency_formula` must be a single-line string.\n"
        "- Allowed operators: `+`, `-`, `*`, `/`, `**`, and parentheses.\n"
        "- You may return either a bare expression or an equation beginning with `resonanceFreq =`.\n"
        "- Always use explicit multiplication such as `2*density`.\n"
        "- Use `**` for powers, never `^`.\n"
        "- Do not use prose, units, Markdown, or natural-language explanation inside `frequency_formula`.\n\n"
        "JSON schema:\n"
        "{\n"
        '  "root_nodes": ["node1", "node2"],\n'
        '  "frequency_formula": "resonanceFreq = 25 + 1*density + 1*moisture"\n'
        "}"
    )
    return [{"role": "system", "content": SYSTEM_JSON_ONLY}, {"role": "user", "content": user_prompt}]


def build_graph_structure_messages(final_hypothesis: Mapping[str, Any]) -> list:
    hypothesis_text = json.dumps(final_hypothesis or {}, indent=2, ensure_ascii=False)
    user_prompt = (
        "You are playing a video game about making scientific discoveries.\n"
        "You are at the Causal Discovery Lab on Planet X.\n\n"
        "You have already explored how crystal properties affect resonance frequency.\n"
        "Keep the same setting, object names, and scientific assumptions as before.\n\n"
        "Below is your current hypothesis object from that exploration.\n\n"
        "<final_hypothesis>\n"
        f"{hypothesis_text}\n"
        "</final_hypothesis>\n\n"
        "=== NEW TASK ===\n"
        "Instead of choosing the next game action, output the final graph structure you currently believe in.\n\n"
        "Rules:\n"
        "- Preserve edge directions.\n"
        "- Preserve the frequency equation and coefficients if present.\n"
        "- Output strict JSON only.\n"
        "- Return exactly one JSON object with exactly these top-level keys: `edges`, `freq_equation`, and `coefficients`.\n"
        "- `edges` must be a JSON array of objects with string fields `from` and `to`.\n"
        "- `freq_equation` must be a string or null.\n"
        "- `coefficients` must be a JSON object mapping coefficient names to numbers or null.\n\n"
        "JSON schema:\n"
        "{\n"
        '  "edges": [{"from": "density", "to": "resonanceFreq"}],\n'
        '  "freq_equation": "resonanceFreq = ...",\n'
        '  "coefficients": {"base": 0.0, "c_density": 1.0}\n'
        "}"
    )
    return [{"role": "system", "content": SYSTEM_JSON_ONLY}, {"role": "user", "content": user_prompt}]


def _client_create(client: Any, messages: list, model_settings: Mapping[str, Any], max_output_tokens: int) -> Dict[str, Any]:
    if hasattr(client, "create"):
        return client.create(messages=messages, max_output_tokens=max_output_tokens, **dict(model_settings))
    if hasattr(client, "responses_create"):
        return client.responses_create(messages=messages, max_output_tokens=max_output_tokens, **dict(model_settings))
    raise TypeError("client must provide create(...) or responses_create(...)")


def _extract_text_from_payload(payload: Mapping[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]
    chunks = []
    for item in payload.get("output") or []:
        if not isinstance(item, Mapping):
            continue
        for content in item.get("content") or []:
            if isinstance(content, Mapping) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    if chunks:
        return "\n".join(chunks)
    choices = payload.get("choices") or []
    if choices and isinstance(choices[0], Mapping):
        msg = choices[0].get("message") or {}
        if isinstance(msg, Mapping) and isinstance(msg.get("content"), str):
            if msg["content"].strip():
                return msg["content"]
            if isinstance(msg.get("reasoning_content"), str):
                return msg["reasoning_content"]
        if isinstance(choices[0].get("text"), str):
            return choices[0]["text"]
    return ""


def _incomplete_reason(payload: Mapping[str, Any]) -> Optional[str]:
    details = payload.get("incomplete_details")
    if isinstance(details, Mapping):
        return details.get("reason")
    return None


def _run_generation(client: Any, messages: list, model_settings: Mapping[str, Any], token_budgets=None) -> Dict[str, Any]:
    if token_budgets is None:
        extra_body = model_settings.get("extra_body") if isinstance(model_settings, Mapping) else {}
        if isinstance(extra_body, Mapping) and extra_body.get("enable_thinking"):
            token_budgets = (2000, 4000, 8000)
        else:
            token_budgets = (1200, 2400, 4000)
    last_payload: Dict[str, Any] = {}
    for budget in token_budgets:
        payload = _client_create(client, messages, model_settings, budget)
        last_payload = payload if isinstance(payload, dict) else dict(payload)
        reason = _incomplete_reason(last_payload)
        if last_payload.get("status") != "incomplete" or reason != "max_output_tokens":
            break
    raw_output = _extract_text_from_payload(last_payload)
    parsed = _parse_json_object(raw_output)
    return {
        "status": "ok" if parsed is not None else "parse_error",
        "reason": None if parsed is not None else "Could not parse model output as JSON object.",
        "raw_output": raw_output,
        "raw_payload": last_payload,
        "parsed_output": parsed,
        "messages": messages,
        "model_settings": dict(model_settings),
        "incomplete_reason": _incomplete_reason(last_payload),
        "used_max_output_tokens": last_payload.get("max_output_tokens"),
    }


def score_root_formula_prediction(
    prediction: Mapping[str, Any],
    graph_config: Mapping[str, Any],
    reactor_outcome: Mapping[str, Any],
) -> Dict[str, Any]:
    true_roots = extract_true_root_nodes_for_frequency(graph_config)
    pred_roots = [str(x) for x in (prediction or {}).get("root_nodes", []) if x is not None]
    formula = (prediction or {}).get("frequency_formula")
    root_metrics = prf(pred_roots, true_roots)
    formula_eval = evaluate_predicted_formula(
        formula,
        pred_roots,
        reactor_outcome.get("reactor_property_values") or {},
        reactor_outcome.get("reactor_target_hz"),
    )
    return {
        "true_root_nodes": true_roots,
        "predicted_root_nodes": pred_roots,
        "root_metrics": root_metrics,
        **formula_eval,
        "reactor_property_values": reactor_outcome.get("reactor_property_values") or {},
        "true_root_value_map": {
            root: (reactor_outcome.get("reactor_property_values") or {}).get(root) for root in true_roots
        },
    }


def score_graph_structure_prediction(
    prediction: Mapping[str, Any],
    graph_config: Mapping[str, Any],
) -> Dict[str, Any]:
    predicted_graph = {
        "edges": (prediction or {}).get("edges") if isinstance((prediction or {}).get("edges"), list) else [],
        "freq_equation": (prediction or {}).get("freq_equation"),
        "coefficients": (prediction or {}).get("coefficients")
        if isinstance((prediction or {}).get("coefficients"), Mapping)
        else {},
    }
    true_edges = true_edges_from_graph_config(graph_config)
    return {
        "predicted_graph": predicted_graph,
        "all_edge_metrics": compute_edge_metrics(predicted_graph["edges"], true_edges),
        "all_edge_shd": compute_directed_shd(predicted_graph["edges"], true_edges),
        "freq_edge_metrics": compute_edge_metrics(
            frequency_parent_edges(predicted_graph["edges"]), frequency_parent_edges(true_edges)
        ),
        "freq_weight_metrics": compute_frequency_weight_metrics(predicted_graph["coefficients"], graph_config),
    }


def _fallback_root_prediction(final_hypothesis: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "root_nodes": extract_root_nodes_from_edges((final_hypothesis or {}).get("edges") or []),
        "frequency_formula": (final_hypothesis or {}).get("freq_equation") or "",
    }


def summarize_seed_for_stage1(seed_dir: Any) -> Dict[str, Any]:
    seed_dir = Path(seed_dir)
    graph_config = read_json(seed_dir / "graph_config.json") or {}
    exact_context = recover_phase1_context(seed_dir)
    final_hypothesis = extract_final_hypothesis(seed_dir)
    reactor_outcome = extract_reactor_outcome(seed_dir)
    task_scorecard = extract_task_scorecard(seed_dir)
    metadata = load_source_metadata(seed_dir)
    legacy_success = extract_legacy_success(seed_dir)

    root_prediction = _fallback_root_prediction(final_hypothesis)
    graph_prediction = final_hypothesis
    if graph_config:
        task1_eval = score_root_formula_prediction(root_prediction, graph_config, reactor_outcome)
        task2_eval = score_graph_structure_prediction(graph_prediction, graph_config)
    else:
        task1_eval = {}
        task2_eval = _empty_graph_eval()

    return {
        "seed_dir": str(seed_dir),
        "case_dir": str(seed_dir.parent),
        "exact_context": exact_context,
        "exact_context_status": exact_context.get("status"),
        "exact_context_reason": exact_context.get("reason"),
        "phase1_prompt_char_count": exact_context.get("phase1_prompt_char_count", 0),
        "source_model_label": metadata.get("source_model_label"),
        "source_model_used": metadata.get("source_model_used"),
        "source_reasoning_effort": metadata.get("source_reasoning_effort"),
        "legacy_success": legacy_success,
        **task_scorecard,
        **reactor_outcome,
        "source_final_hypothesis": final_hypothesis,
        "task1_root_formula_generation": {
            "status": "source_fallback",
            "reason": "No API call requested; scored root/formula from logged final hypothesis.",
            "raw_output": json.dumps(root_prediction, ensure_ascii=False),
            "parsed_output": root_prediction,
            "phase1_prompt_char_count": exact_context.get("phase1_prompt_char_count", 0),
        },
        "task1_root_formula_eval": task1_eval,
        "task2_graph_structure_generation": {
            "status": "source_fallback",
            "reason": "No API call requested; scored logged final hypothesis as graph output.",
            "raw_output": json.dumps(graph_prediction, ensure_ascii=False),
            "parsed_output": graph_prediction,
        },
        "task2_graph_structure_eval": task2_eval,
    }


def _model_settings(stage1: Mapping[str, Any]) -> Dict[str, Any]:
    settings = {"model": stage1.get("source_model_used") or "gpt-5-mini"}
    effort = stage1.get("source_reasoning_effort")
    if effort:
        settings["reasoning_effort"] = effort
    source_config = stage1.get("source_config") or {}
    models = source_config.get("models") if isinstance(source_config, Mapping) else {}
    action = models.get("action") if isinstance(models, Mapping) else {}
    params = action.get("generator_params") if isinstance(action, Mapping) else {}
    if isinstance(params, Mapping):
        extra_body = dict(params.get("extra_body") or {})
        if "qwen_enable_thinking" in params:
            extra_body["enable_thinking"] = bool(params.get("qwen_enable_thinking"))
            if extra_body["enable_thinking"] and "thinking_budget" in extra_body:
                extra_body["thinking_budget"] = int(os.environ.get("QWEN_REEVAL_THINKING_BUDGET", "512"))
        if extra_body:
            settings["extra_body"] = extra_body
        for key in ("temperature", "top_p", "seed"):
            if params.get(key) is not None:
                settings[key] = params.get(key)
    return settings


def summarize_seed_for_reeval(seed_dir: Any, client: Any) -> Dict[str, Any]:
    stage1 = summarize_seed_for_stage1(seed_dir)
    graph_config = read_json(Path(seed_dir) / "graph_config.json") or {}
    model_settings = _model_settings(stage1)

    root_messages = build_root_formula_messages((stage1.get("exact_context") or {}).get("phase1_prompt") or "")
    root_generation = _run_generation(client, root_messages, model_settings)
    root_prediction = root_generation.get("parsed_output") or {}
    root_eval = score_root_formula_prediction(root_prediction, graph_config, stage1)

    graph_messages = build_graph_structure_messages(stage1.get("source_final_hypothesis") or {})
    graph_generation = _run_generation(client, graph_messages, model_settings)
    graph_prediction = graph_generation.get("parsed_output") or {}
    graph_eval = score_graph_structure_prediction(graph_prediction, graph_config)

    stage1.update(
        {
            "task1_root_formula_generation": root_generation,
            "task1_root_formula_eval": root_eval,
            "task2_graph_structure_generation": graph_generation,
            "task2_graph_structure_eval": graph_eval,
        }
    )
    return stage1
