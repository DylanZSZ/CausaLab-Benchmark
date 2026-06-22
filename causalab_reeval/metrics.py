from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


FREQ_NODE = "resonanceFreq"


def normalize_node_name(name: Any) -> str:
    """Normalize graph node aliases used by the evaluator and visualizations."""
    node = str(name or "").strip()
    compact = node.replace(" ", "").replace("_", "").replace("-", "").lower()
    if compact in {"freq", "resonancefreq", "frequency", "resonancefrequency"}:
        return FREQ_NODE
    return node


def _as_edge_tuple(edge: Any) -> Optional[Tuple[str, str]]:
    if isinstance(edge, Mapping):
        src = edge.get("from")
        dst = edge.get("to")
    elif isinstance(edge, (list, tuple)) and len(edge) == 2:
        src, dst = edge
    else:
        return None
    if src is None or dst is None:
        return None
    return (normalize_node_name(src), normalize_node_name(dst))


def normalize_edges(edges: Iterable[Any]) -> Set[Tuple[str, str]]:
    out: Set[Tuple[str, str]] = set()
    for edge in edges or []:
        pair = _as_edge_tuple(edge)
        if pair and pair[0] and pair[1]:
            out.add(pair)
    return out


def edges_to_dicts(edges: Iterable[Tuple[str, str]]) -> List[Dict[str, str]]:
    return [{"from": src, "to": dst} for src, dst in sorted(edges)]


def prf(predicted: Iterable[Any], true: Iterable[Any]) -> Dict[str, Any]:
    pred_set = set(predicted or [])
    true_set = set(true or [])
    correct = pred_set & true_set
    precision = len(correct) / len(pred_set) if pred_set else (1.0 if not true_set else 0.0)
    recall = len(correct) / len(true_set) if true_set else (1.0 if not pred_set else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "num_predicted": len(pred_set),
        "num_true": len(true_set),
        "num_correct": len(correct),
        "true_positives": sorted(correct),
        "false_positives": sorted(pred_set - true_set),
        "false_negatives": sorted(true_set - pred_set),
    }


def compute_edge_metrics(predicted_edges: Iterable[Any], true_edges: Iterable[Any]) -> Dict[str, Any]:
    pred_set = normalize_edges(predicted_edges)
    true_set = normalize_edges(true_edges)
    metrics = prf(pred_set, true_set)
    for key in ("true_positives", "false_positives", "false_negatives"):
        metrics[key] = edges_to_dicts(metrics[key])
    return metrics


def compute_directed_shd(predicted_edges: Iterable[Any], true_edges: Iterable[Any]) -> Dict[str, Any]:
    """Compute directed structural Hamming distance with reversals counted once."""
    pred_set = normalize_edges(predicted_edges)
    true_set = normalize_edges(true_edges)
    correct = pred_set & true_set
    remaining_pred = pred_set - correct
    remaining_true = true_set - correct

    reversed_edges: Set[Tuple[str, str]] = set()
    used_pred: Set[Tuple[str, str]] = set()
    for true_edge in sorted(remaining_true):
        reverse = (true_edge[1], true_edge[0])
        if reverse in remaining_pred:
            reversed_edges.add(true_edge)
            used_pred.add(reverse)

    missing = remaining_true - reversed_edges
    extra = remaining_pred - used_pred
    shd = len(missing) + len(extra) + len(reversed_edges)
    return {
        "shd": shd,
        "missing": len(missing),
        "extra": len(extra),
        "reversed": len(reversed_edges),
        "status": "ok",
        "missing_edges": edges_to_dicts(missing),
        "extra_edges": edges_to_dicts(extra),
        "reversed_edges": edges_to_dicts(reversed_edges),
        "num_predicted": len(pred_set),
        "num_true": len(true_set),
    }


def true_edges_from_graph_config(graph_config: Mapping[str, Any]) -> List[Dict[str, str]]:
    return edges_to_dicts(normalize_edges(graph_config.get("edges", [])))


def frequency_parent_edges(edges: Iterable[Any], freq_node: str = FREQ_NODE) -> List[Dict[str, str]]:
    return edges_to_dicts((src, dst) for src, dst in normalize_edges(edges) if dst == freq_node)


def extract_true_root_nodes_for_frequency(
    graph_config: Mapping[str, Any], freq_node: str = FREQ_NODE
) -> List[str]:
    edges = normalize_edges(graph_config.get("edges", []))
    parents: Dict[str, Set[str]] = {}
    children: Dict[str, Set[str]] = {}
    nodes = set((graph_config.get("nodes") or {}).keys())
    for src, dst in edges:
        nodes.add(src)
        nodes.add(dst)
        parents.setdefault(dst, set()).add(src)
        children.setdefault(src, set()).add(dst)

    ancestors: Set[str] = set()
    frontier = list(parents.get(freq_node, set()))
    while frontier:
        node = frontier.pop()
        if node in ancestors:
            continue
        ancestors.add(node)
        frontier.extend(parents.get(node, set()))

    return sorted(node for node in ancestors if not parents.get(node))


def extract_root_nodes_from_edges(edges: Iterable[Any], freq_node: str = FREQ_NODE) -> List[str]:
    edge_set = normalize_edges(edges)
    parents: Dict[str, Set[str]] = {}
    for src, dst in edge_set:
        parents.setdefault(dst, set()).add(src)
    ancestors: Set[str] = set()
    frontier = list(parents.get(freq_node, set()))
    while frontier:
        node = frontier.pop()
        if node in ancestors:
            continue
        ancestors.add(node)
        frontier.extend(parents.get(node, set()))
    return sorted(node for node in ancestors if not parents.get(node))


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _find_true_frequency_coefficients(graph_config: Mapping[str, Any]) -> Dict[str, float]:
    params = graph_config.get("params") or {}
    nodes = graph_config.get("nodes") or {}
    freq_computation = str((nodes.get(FREQ_NODE) or {}).get("computation") or "")
    parents = [edge["from"] for edge in frequency_parent_edges(graph_config.get("edges", []))]
    out: Dict[str, float] = {}
    for parent in parents:
        candidates = [
            f"coeff_{parent}_freq",
            f"coeff_{parent}_frequency",
            f"c_{parent}",
            parent,
        ]
        found_name = None
        for name in candidates:
            if name in params:
                found_name = name
                break
        if found_name is None and freq_computation:
            escaped = re.escape(parent)
            patterns = [
                rf"\b([A-Za-z_][A-Za-z0-9_]*)\b\s*\*\s*\b{escaped}\b",
                rf"\b{escaped}\b\s*\*\s*\b([A-Za-z_][A-Za-z0-9_]*)\b",
            ]
            for pattern in patterns:
                match = re.search(pattern, freq_computation)
                if match and match.group(1) in params:
                    found_name = match.group(1)
                    break
        if found_name is not None:
            value = _numeric(params.get(found_name))
            if value is not None:
                out[parent] = value
    return out


def _predicted_coefficient_for_property(coefficients: Mapping[str, Any], prop: str) -> Tuple[Optional[str], Optional[float]]:
    if not isinstance(coefficients, Mapping):
        return None, None
    candidates = [f"c_{prop}", f"coeff_{prop}_freq", f"coeff_{prop}_frequency", prop]
    lower_map = {str(k).lower(): k for k in coefficients.keys()}
    for name in candidates:
        key = name if name in coefficients else lower_map.get(name.lower())
        if key is not None:
            value = _numeric(coefficients.get(key))
            if value is not None:
                return str(key), value
    return None, None


def compute_frequency_weight_metrics(
    predicted_coefficients: Mapping[str, Any],
    graph_config: Mapping[str, Any],
    *,
    tolerance: float = 1e-6,
) -> Dict[str, Any]:
    true_coeffs = _find_true_frequency_coefficients(graph_config)
    details: List[Dict[str, Any]] = []
    correct = 0
    predicted_weight_names = set()
    for prop, true_value in true_coeffs.items():
        pred_name, pred_value = _predicted_coefficient_for_property(predicted_coefficients, prop)
        if pred_name is not None:
            predicted_weight_names.add(pred_name)
        is_correct = pred_value is not None and math.isclose(pred_value, true_value, abs_tol=tolerance, rel_tol=0)
        correct += int(is_correct)
        details.append(
            {
                "property": prop,
                "true_value": true_value,
                "predicted_name": pred_name,
                "predicted_value": pred_value,
                "correct": is_correct,
            }
        )

    predicted_freq_weights = [
        key
        for key in (predicted_coefficients or {}).keys()
        if str(key).startswith("c_") or str(key).startswith("coeff_")
    ]
    num_pred = max(len(predicted_weight_names), len(predicted_freq_weights))
    num_true = len(true_coeffs)
    precision = correct / num_pred if num_pred else (1.0 if not num_true else 0.0)
    recall = correct / num_true if num_true else (1.0 if not num_pred else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "weight_precision": precision,
        "weight_recall": recall,
        "weight_f1": f1,
        "num_predicted_weights": num_pred,
        "num_true_weights": num_true,
        "num_correct_weights": correct,
        "weight_details": details,
    }


_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _rhs_expression(formula: str) -> str:
    text = str(formula or "").strip()
    if "=" in text:
        text = text.split("=", 1)[1].strip()
    return text


def _names_in_ast(node: ast.AST) -> List[str]:
    return sorted({n.id for n in ast.walk(node) if isinstance(n, ast.Name)})


def _eval_ast(node: ast.AST, values: Mapping[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body, values)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if hasattr(ast, "Num") and isinstance(node, ast.Num):
        return float(node.n)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise KeyError(node.id)
        return float(values[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_eval_ast(node.left, values), _eval_ast(node.right, values))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_eval_ast(node.operand, values))
    raise ValueError(f"Unsupported formula expression: {ast.dump(node)}")


def evaluate_predicted_formula(
    formula: Any,
    predicted_root_nodes: Sequence[str],
    property_values: Mapping[str, Any],
    target_frequency: Optional[float],
    *,
    tolerance_hz: float = 5.0,
) -> Dict[str, Any]:
    formula_text = "" if formula is None else str(formula)
    result: Dict[str, Any] = {
        "formula_text": formula_text,
        "formula_parse_success": False,
        "formula_uses_only_predicted_roots": False,
        "formula_symbols": [],
        "formula_predicted_frequency": None,
        "formula_abs_error_hz": None,
        "formula_hits_pm5hz": None,
        "formula_missing_variable_values": [],
    }
    try:
        tree = ast.parse(_rhs_expression(formula_text), mode="eval")
        symbols = _names_in_ast(tree)
        result["formula_parse_success"] = True
        result["formula_symbols"] = symbols
        root_set = set(str(x) for x in predicted_root_nodes or [])
        result["formula_uses_only_predicted_roots"] = set(symbols).issubset(root_set)
        values: Dict[str, float] = {}
        missing: List[str] = []
        for symbol in symbols:
            value = _numeric((property_values or {}).get(symbol))
            if value is None:
                missing.append(symbol)
            else:
                values[symbol] = value
        result["formula_missing_variable_values"] = missing
        if missing:
            return result
        predicted = float(_eval_ast(tree, values))
        result["formula_predicted_frequency"] = predicted
        if target_frequency is not None:
            error = abs(predicted - float(target_frequency))
            result["formula_abs_error_hz"] = error
            result["formula_hits_pm5hz"] = error <= tolerance_hz
    except Exception as exc:
        result["formula_error"] = str(exc)
    return result
