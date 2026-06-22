from __future__ import annotations

import argparse
import csv
import json
import os
import random
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

try:
    from .reeval_core import summarize_seed_for_reeval, summarize_seed_for_stage1
except ImportError:  # pragma: no cover - supports direct script execution
    from reeval_core import summarize_seed_for_reeval, summarize_seed_for_stage1


class SimpleOpenAIClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        *,
        timeout: int = 180,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = (
            base_url
            or os.environ.get("OPENAI_API_BASE")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for API-backed re-eval.")

    def create(self, *, messages: list, max_output_tokens: int, model: str, reasoning_effort: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        extra_body = kwargs.pop("extra_body", None)
        optional_params = {k: v for k, v in kwargs.items() if v is not None}
        payload: Dict[str, Any] = {
            "model": model,
            "input": messages,
            "max_output_tokens": max_output_tokens,
        }
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        payload.update(optional_params)
        if isinstance(extra_body, Mapping):
            payload.update(extra_body)
        try:
            return self._post_json(f"{self.base_url}/responses", payload)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise
        chat_payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_output_tokens,
        }
        if reasoning_effort:
            chat_payload["reasoning_effort"] = reasoning_effort
        chat_payload.update(optional_params)
        if isinstance(extra_body, Mapping):
            chat_payload.update(extra_body)
        result = self._post_json(f"{self.base_url}/chat/completions", chat_payload)
        if "output_text" not in result:
            choices = result.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                result["output_text"] = msg.get("content", "")
        return result

    def _post_json(self, url: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt + 1 >= self.max_retries:
                    raise
                retry_after = exc.headers.get("Retry-After")
                if retry_after:
                    try:
                        sleep_for = float(retry_after)
                    except ValueError:
                        sleep_for = 0.0
                else:
                    sleep_for = min(60.0, 4.0 * (2 ** attempt)) + random.uniform(0.0, 2.0)
                time.sleep(sleep_for)
                continue
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= self.max_retries:
                    break
                time.sleep(2 ** attempt)
        raise RuntimeError(f"OpenAI-compatible request failed: {last_error}")


def _nested_get(row: Mapping[str, Any], path: Iterable[str], default: Any = None) -> Any:
    cur: Any = row
    for key in path:
        if not isinstance(cur, Mapping):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def flatten_seed_result(task: Mapping[str, Any], seed_result: Mapping[str, Any]) -> Dict[str, Any]:
    task1_eval = seed_result.get("task1_root_formula_eval") or {}
    task2_eval = seed_result.get("task2_graph_structure_eval") or {}
    task1_gen = seed_result.get("task1_root_formula_generation") or {}
    task2_gen = seed_result.get("task2_graph_structure_generation") or {}
    predicted_graph = task2_eval.get("predicted_graph") or {}
    row = {
        "group_id": task.get("group_id"),
        "experiment_id": task.get("experiment_id"),
        "experiment_label": task.get("experiment_label"),
        "source_model_label": seed_result.get("source_model_label") or task.get("inventory_model"),
        "source_model_used": seed_result.get("source_model_used"),
        "source_reasoning_effort": seed_result.get("source_reasoning_effort"),
        "seed_dir": str(task.get("seed_dir") or seed_result.get("seed_dir") or ""),
        "case_dir": seed_result.get("case_dir"),
        "exact_context_status": seed_result.get("exact_context_status"),
        "exact_context_reason": seed_result.get("exact_context_reason"),
        "phase1_prompt_char_count": seed_result.get("phase1_prompt_char_count"),
        "task1_generation_status": task1_gen.get("status"),
        "task1_generation_reason": task1_gen.get("reason"),
        "task2_generation_status": task2_gen.get("status"),
        "task2_generation_reason": task2_gen.get("reason"),
        "legacy_success": seed_result.get("legacy_success"),
        "task_completed": seed_result.get("task_completed"),
        "task_completed_successfully": seed_result.get("task_completed_successfully"),
        "task_score_normalized": seed_result.get("task_score_normalized"),
        "reactor_target_hz": seed_result.get("reactor_target_hz"),
        "reactor_submitted_hz": seed_result.get("reactor_submitted_hz"),
        "reactor_abs_error_hz": seed_result.get("reactor_abs_error_hz"),
        "true_root_nodes": task1_eval.get("true_root_nodes"),
        "predicted_root_nodes": task1_eval.get("predicted_root_nodes"),
        "root_precision": _nested_get(task1_eval, ["root_metrics", "precision"]),
        "root_recall": _nested_get(task1_eval, ["root_metrics", "recall"]),
        "root_f1": _nested_get(task1_eval, ["root_metrics", "f1"]),
        "formula_text": task1_eval.get("formula_text"),
        "formula_parse_success": task1_eval.get("formula_parse_success"),
        "formula_uses_only_predicted_roots": task1_eval.get("formula_uses_only_predicted_roots"),
        "formula_symbols": task1_eval.get("formula_symbols"),
        "formula_predicted_frequency": task1_eval.get("formula_predicted_frequency"),
        "formula_abs_error_hz": task1_eval.get("formula_abs_error_hz"),
        "formula_hits_pm5hz": task1_eval.get("formula_hits_pm5hz"),
        "formula_missing_variable_values": task1_eval.get("formula_missing_variable_values"),
        "reactor_property_values": task1_eval.get("reactor_property_values") or seed_result.get("reactor_property_values"),
        "predicted_graph_edges": predicted_graph.get("edges"),
        "predicted_graph_freq_equation": predicted_graph.get("freq_equation"),
        "predicted_graph_coefficients": predicted_graph.get("coefficients"),
        "all_edge_precision": _nested_get(task2_eval, ["all_edge_metrics", "precision"]),
        "all_edge_recall": _nested_get(task2_eval, ["all_edge_metrics", "recall"]),
        "all_edge_f1": _nested_get(task2_eval, ["all_edge_metrics", "f1"]),
        "all_edge_shd": _nested_get(task2_eval, ["all_edge_shd", "shd"]),
        "all_edge_shd_missing": _nested_get(task2_eval, ["all_edge_shd", "missing"]),
        "all_edge_shd_extra": _nested_get(task2_eval, ["all_edge_shd", "extra"]),
        "all_edge_shd_reversed": _nested_get(task2_eval, ["all_edge_shd", "reversed"]),
        "all_edge_shd_status": _nested_get(task2_eval, ["all_edge_shd", "status"]),
        "freq_edge_precision": _nested_get(task2_eval, ["freq_edge_metrics", "precision"]),
        "freq_edge_recall": _nested_get(task2_eval, ["freq_edge_metrics", "recall"]),
        "freq_edge_f1": _nested_get(task2_eval, ["freq_edge_metrics", "f1"]),
        "freq_weight_precision": _nested_get(task2_eval, ["freq_weight_metrics", "weight_precision"]),
        "freq_weight_recall": _nested_get(task2_eval, ["freq_weight_metrics", "weight_recall"]),
        "freq_weight_f1": _nested_get(task2_eval, ["freq_weight_metrics", "weight_f1"]),
        "source_final_hypothesis": seed_result.get("source_final_hypothesis"),
    }
    return row


def _mean(values: Iterable[Any]) -> Optional[float]:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    return sum(nums) / len(nums) if nums else None


def summarize_experiments(flat_rows: List[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for row in flat_rows:
        grouped.setdefault(str(row.get("experiment_id")), []).append(row)
    summaries: Dict[str, Dict[str, Any]] = {}
    for experiment_id, rows in sorted(grouped.items()):
        first = rows[0]
        summaries[experiment_id] = {
            "group_id": first.get("group_id"),
            "experiment_label": first.get("experiment_label"),
            "source_model_label": first.get("source_model_label"),
            "source_model_used": first.get("source_model_used"),
            "source_reasoning_effort": first.get("source_reasoning_effort"),
            "num_seed_rows": len(rows),
            "num_task1_generation_ok": sum(1 for r in rows if r.get("task1_generation_status") in ("ok", "source_fallback")),
            "num_task2_generation_ok": sum(1 for r in rows if r.get("task2_generation_status") in ("ok", "source_fallback")),
            "mean_task_accuracy": _mean(bool(r.get("task_completed_successfully")) for r in rows if r.get("task_completed_successfully") is not None),
            "mean_task_score_normalized": _mean(r.get("task_score_normalized") for r in rows),
            "mean_root_f1": _mean(r.get("root_f1") for r in rows),
            "mean_formula_abs_error_hz": _mean(r.get("formula_abs_error_hz") for r in rows),
            "formula_hit_rate_pm5hz": _mean(bool(r.get("formula_hits_pm5hz")) for r in rows if r.get("formula_hits_pm5hz") is not None),
            "mean_all_edge_precision": _mean(r.get("all_edge_precision") for r in rows),
            "mean_all_edge_recall": _mean(r.get("all_edge_recall") for r in rows),
            "mean_all_edge_f1": _mean(r.get("all_edge_f1") for r in rows),
            "mean_all_edge_shd": _mean(r.get("all_edge_shd") for r in rows),
            "mean_all_edge_shd_missing": _mean(r.get("all_edge_shd_missing") for r in rows),
            "mean_all_edge_shd_extra": _mean(r.get("all_edge_shd_extra") for r in rows),
            "mean_all_edge_shd_reversed": _mean(r.get("all_edge_shd_reversed") for r in rows),
            "num_shd_ok": sum(1 for r in rows if r.get("all_edge_shd_status") == "ok"),
            "num_shd_missing_true_graph": sum(1 for r in rows if r.get("all_edge_shd_status") == "missing_true_graph"),
            "mean_freq_edge_f1": _mean(r.get("freq_edge_f1") for r in rows),
            "mean_freq_weight_f1": _mean(r.get("freq_weight_f1") for r in rows),
            "mean_reactor_abs_error_hz": _mean(r.get("reactor_abs_error_hz") for r in rows),
        }
    return summaries


def render_summary_markdown(config: Mapping[str, Any], experiment_summary: Mapping[str, Mapping[str, Any]]) -> str:
    lines = [
        "# Re-eval Summary",
        "",
        f"- run_name: {config.get('run_name', '')}",
        f"- task_count: {config.get('task_count', '')}",
        f"- parallelism: {config.get('parallelism', '')}",
        "",
        "| experiment | rows | task_acc | root_f1 | all_edge_f1 | all_edge_shd | freq_edge_f1 | freq_weight_f1 | reactor_abs_error |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for experiment_id, row in experiment_summary.items():
        lines.append(
            "| {experiment} | {rows} | {task_acc:.4g} | {root:.4g} | {all_edge:.4g} | {shd:.4g} | {freq_edge:.4g} | {freq_weight:.4g} | {reactor:.4g} |".format(
                experiment=experiment_id,
                rows=row.get("num_seed_rows", 0),
                task_acc=row.get("mean_task_accuracy") or 0.0,
                root=row.get("mean_root_f1") or 0.0,
                all_edge=row.get("mean_all_edge_f1") or 0.0,
                shd=row.get("mean_all_edge_shd") or 0.0,
                freq_edge=row.get("mean_freq_edge_f1") or 0.0,
                freq_weight=row.get("mean_freq_weight_f1") or 0.0,
                reactor=row.get("mean_reactor_abs_error_hz") or 0.0,
            )
        )
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: List[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def _collect_seed_dirs(paths: List[str], limit: Optional[int]) -> List[Path]:
    seeds: List[Path] = []
    for item in paths:
        path = Path(item).expanduser().resolve()
        if path.is_dir() and path.name.startswith("seed_"):
            seeds.append(path)
        elif path.is_dir():
            seeds.extend(sorted(p for p in path.glob("**/seed_*") if p.is_dir()))
    return seeds[:limit] if limit else seeds


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run lightweight CausaLab re-eval on seed directories.")
    parser.add_argument("paths", nargs="+", help="Seed dirs or roots containing seed_* dirs.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--parallelism", type=int, default=1)
    parser.add_argument("--source-only", action="store_true", help="Do not call the API; score logged source hypothesis only.")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    args = parser.parse_args(argv)

    seed_dirs = _collect_seed_dirs(args.paths, args.limit)
    output_dir = Path(args.output_dir).expanduser().resolve()
    raw_dir = output_dir / "raw_generation_outputs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "run_name": output_dir.name,
        "task_count": len(seed_dirs),
        "parallelism": args.parallelism,
        "source_only": args.source_only,
        "api_base": args.api_base if not args.source_only else None,
    }
    _write_json(output_dir / "config.json", config)
    _write_json(output_dir / "selected_tasks.json", [{"seed_dir": str(p), "experiment_id": p.parent.name} for p in seed_dirs])

    client = None if args.source_only else SimpleOpenAIClient(api_key=args.api_key, base_url=args.api_base)

    nested = []
    flat = []
    with ThreadPoolExecutor(max_workers=args.parallelism) as executor:
        future_map = {}
        for seed_dir in seed_dirs:
            task = {
                "group_id": "lightweight",
                "experiment_id": seed_dir.parent.name,
                "experiment_label": seed_dir.parent.name,
                "seed_dir": seed_dir,
            }
            fn = summarize_seed_for_stage1 if args.source_only else summarize_seed_for_reeval
            future = executor.submit(fn, seed_dir) if args.source_only else executor.submit(fn, seed_dir, client)
            future_map[future] = task
        for future in as_completed(future_map):
            task = future_map[future]
            seed_result = future.result()
            task_for_json = {**task, "seed_dir": str(task["seed_dir"])}
            nested.append({"task": task_for_json, "seed_result": seed_result})
            flat.append(flatten_seed_result(task, seed_result))
            safe_name = f"{task['experiment_id']}__{Path(task['seed_dir']).name}.json"
            _write_json(
                raw_dir / safe_name,
                {
                    "task": task_for_json,
                    "source_final_hypothesis": seed_result.get("source_final_hypothesis"),
                    "task1_root_formula_generation": seed_result.get("task1_root_formula_generation"),
                    "task1_root_formula_eval": seed_result.get("task1_root_formula_eval"),
                    "task2_graph_structure_generation": seed_result.get("task2_graph_structure_generation"),
                    "task2_graph_structure_eval": seed_result.get("task2_graph_structure_eval"),
                },
            )

    summary = summarize_experiments(flat)
    _write_json(output_dir / "nested_results.json", nested)
    _write_json(output_dir / "per_seed_results.json", flat)
    _write_csv(output_dir / "per_seed_results.csv", flat)
    _write_json(output_dir / "per_experiment_summary.json", summary)
    (output_dir / "summary.md").write_text(render_summary_markdown(config, summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
