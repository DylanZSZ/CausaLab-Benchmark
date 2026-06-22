from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def iter_json_objects_from_text(text: str) -> Iterable[Any]:
    decoder = json.JSONDecoder()
    idx = 0
    length = len(text)
    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if idx >= length:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            next_obj = text.find("{", idx + 1)
            if next_obj < 0:
                break
            idx = next_obj
            continue
        yield obj
        idx = end


def read_json_stream(path: Path) -> List[Any]:
    try:
        return list(iter_json_objects_from_text(path.read_text(encoding="utf-8", errors="replace")))
    except Exception:
        return []


def _extract_action_payload(obj: Any) -> Optional[Mapping[str, Any]]:
    if not isinstance(obj, Mapping):
        return None
    action = obj.get("action")
    if isinstance(action, Mapping):
        return action
    raw_output = obj.get("raw_output")
    if isinstance(raw_output, str):
        parsed = next(iter_json_objects_from_text(raw_output), None)
        if isinstance(parsed, Mapping):
            return parsed
    return None


def _iter_seed_objects(seed_dir: Path) -> Iterable[Tuple[Path, Any]]:
    patterns = ["*_tracking.jsonl", "*_tracking_simple.jsonl", "raw_io.jsonl"]
    seen = set()
    for pattern in patterns:
        for path in sorted(seed_dir.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            for obj in read_json_stream(path):
                yield path, obj


def recover_phase1_context(seed_dir: Path) -> Dict[str, Any]:
    seed_dir = Path(seed_dir)
    candidates: List[Tuple[str, str, str]] = []
    relaxed: List[Tuple[str, str, str]] = []
    for path, obj in _iter_seed_objects(seed_dir):
        if not isinstance(obj, Mapping):
            continue
        raw_input = obj.get("raw_input")
        if not isinstance(raw_input, str) or not raw_input.strip():
            continue
        source = "tracking_raw_input" if "tracking" in path.name else "raw_io_raw_input"
        text = raw_input
        if "CRYSTAL REACTOR" in text and "PROPERTY MANIPULATOR" not in text:
            continue
        if "PROPERTY MANIPULATOR" in text or "Causal Discovery" in text:
            candidates.append((source, path.name, text))
        if "EXISTING OBSERVATIONS" in text:
            relaxed.append((source, path.name, text))

    if candidates:
        source, filename, text = candidates[-1]
        return {
            "seed_dir": str(seed_dir),
            "status": f"exact_from_{source}",
            "reason": None,
            "source_file": filename,
            "phase1_prompt": text,
            "phase1_prompt_char_count": len(text),
        }
    if relaxed:
        source, filename, text = relaxed[0]
        return {
            "seed_dir": str(seed_dir),
            "status": "relaxed_first_existing_observations_prompt",
            "reason": None,
            "source_file": filename,
            "phase1_prompt": text,
            "phase1_prompt_char_count": len(text),
        }
    return {
        "seed_dir": str(seed_dir),
        "status": "missing",
        "reason": "No raw_input prompt found in tracking/raw_io logs.",
        "source_file": None,
        "phase1_prompt": "",
        "phase1_prompt_char_count": 0,
    }


def extract_final_hypothesis(seed_dir: Path) -> Dict[str, Any]:
    final: Dict[str, Any] = {"edges": [], "freq_equation": None, "coefficients": {}}
    for _, obj in _iter_seed_objects(Path(seed_dir)):
        payload = _extract_action_payload(obj)
        if not isinstance(payload, Mapping):
            continue
        hyp = payload.get("hypothesis")
        if isinstance(hyp, Mapping):
            edges = hyp.get("edges")
            coeffs = hyp.get("coefficients")
            if edges or hyp.get("freq_equation") or coeffs:
                final = {
                    "edges": edges if isinstance(edges, list) else [],
                    "freq_equation": hyp.get("freq_equation"),
                    "coefficients": coeffs if isinstance(coeffs, Mapping) else {},
                }
    return final


def extract_past_data(seed_dir: Path) -> List[Dict[str, Any]]:
    final: List[Dict[str, Any]] = []
    for _, obj in _iter_seed_objects(Path(seed_dir)):
        payload = _extract_action_payload(obj)
        if not isinstance(payload, Mapping):
            continue
        past_data = payload.get("past_data")
        if isinstance(past_data, list) and len(past_data) >= len(final):
            final = [x for x in past_data if isinstance(x, Mapping)]
    return final


def _parse_property_block(text: str) -> Dict[str, float]:
    props: Dict[str, float] = {}
    for name, value in re.findall(r"^\s*-\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(-?\d+(?:\.\d+)?)", text, flags=re.M):
        try:
            props[name] = float(value)
        except ValueError:
            pass
    return props


def _last_float(pattern: str, text: str) -> Optional[float]:
    values = re.findall(pattern, text, flags=re.I | re.M)
    if not values:
        return None
    try:
        return float(values[-1])
    except ValueError:
        return None


def extract_reactor_outcome(seed_dir: Path) -> Dict[str, Any]:
    props: Dict[str, float] = {}
    target: Optional[float] = None
    submitted: Optional[float] = None
    for _, obj in _iter_seed_objects(Path(seed_dir)):
        if not isinstance(obj, Mapping):
            continue
        texts: List[str] = []
        for key in ("raw_input", "raw_output", "lastActionMessage"):
            if isinstance(obj.get(key), str):
                texts.append(obj[key])
        dialog = obj.get("dialog_box")
        if isinstance(dialog, Mapping) and isinstance(dialog.get("dialogIn"), str):
            texts.append(dialog["dialogIn"])
        action = _extract_action_payload(obj)
        if isinstance(action, Mapping):
            if _is_reactor_experiment(action) and "value" in action:
                try:
                    submitted = float(action["value"])
                except (TypeError, ValueError):
                    pass
            experiment = action.get("experiment")
            if isinstance(experiment, Mapping) and _is_reactor_experiment(action):
                try:
                    submitted = float(experiment.get("target_value"))
                except (TypeError, ValueError):
                    pass
        for text in texts:
            if "CRYSTAL REACTOR" in text or "Crystal properties (directly shown)" in text:
                parsed_props = _parse_property_block(text)
                if parsed_props:
                    props = parsed_props
                freq = _last_float(r"Current resonance frequency:\s*(-?\d+(?:\.\d+)?)\s*Hz", text)
                if freq is not None:
                    target = freq
                set_freq = _last_float(r"Frequency set to\s*(-?\d+(?:\.\d+)?)\s*Hz", text)
                if set_freq is not None:
                    submitted = set_freq

    abs_error = abs(submitted - target) if submitted is not None and target is not None else None
    return {
        "reactor_property_values": props,
        "reactor_target_hz": target,
        "reactor_submitted_hz": submitted,
        "reactor_abs_error_hz": abs_error,
    }


def _is_reactor_experiment(action: Mapping[str, Any]) -> bool:
    experiment = action.get("experiment")
    if isinstance(experiment, Mapping):
        target_prop = str(experiment.get("target_prop") or "").lower()
        if "reactor" in target_prop or "frequency" in target_prop:
            return True
    return str(action.get("action") or "").upper() == "SUBMIT"


def extract_legacy_success(seed_dir: Path) -> Optional[str]:
    for path in sorted(Path(seed_dir).glob("*_data.json")):
        data = read_json(path)
        if isinstance(data, Mapping) and data.get("predicted") is not None:
            return str(data.get("predicted"))
    return None


def extract_task_scorecard(seed_dir: Path) -> Dict[str, Any]:
    for path in sorted(Path(seed_dir).glob("*_data.json")):
        data = read_json(path)
        if not isinstance(data, Mapping):
            continue
        scorecard = (data.get("metadata") or {}).get("final_scorecard")
        if isinstance(scorecard, list):
            scorecard = scorecard[0] if scorecard else {}
        if not isinstance(scorecard, Mapping):
            continue
        return {
            "task_completed": bool(scorecard.get("completed")),
            "task_completed_successfully": bool(scorecard.get("completedSuccessfully")),
            "task_score_normalized": scorecard.get("scoreNormalized"),
        }
    return {
        "task_completed": None,
        "task_completed_successfully": None,
        "task_score_normalized": None,
    }


def load_source_metadata(seed_dir: Path) -> Dict[str, Any]:
    seed_dir = Path(seed_dir)
    source_config = read_json(seed_dir / "source_config.json") or {}
    manifest = read_json(seed_dir / "experiment_manifest.json") or {}
    model = None
    if isinstance(source_config, Mapping):
        models = source_config.get("models") or {}
        action = models.get("action") if isinstance(models, Mapping) else {}
        params = (action or {}).get("generator_params") if isinstance(action, Mapping) else {}
        if isinstance(params, Mapping):
            model = params.get("model")
    label = None
    if isinstance(manifest, Mapping):
        label = manifest.get("model_label") or manifest.get("inventory_model") or manifest.get("source_model_label")
    label = label or model
    model_text = str(model or label or "")
    label_text = str(label or model or "")
    if "5.2" in model_text or "5.2" in label_text:
        return {
            "source_model_label": label_text or "GPT-5.2-high",
            "source_model_used": "gpt-5.2",
            "source_reasoning_effort": "high" if "high" in label_text.lower() else "high",
            "source_config": source_config,
            "experiment_manifest": manifest,
        }
    return {
        "source_model_label": label_text or "GPT-5-mini",
        "source_model_used": model_text or "gpt-5-mini",
        "source_reasoning_effort": None,
        "source_config": source_config,
        "experiment_manifest": manifest,
    }
