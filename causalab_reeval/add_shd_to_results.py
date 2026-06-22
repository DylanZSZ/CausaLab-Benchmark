from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

try:
    from .metrics import compute_directed_shd
except ImportError:  # pragma: no cover - supports direct script execution
    from metrics import compute_directed_shd


SHD_FIELDS = (
    "all_edge_shd",
    "all_edge_shd_missing",
    "all_edge_shd_extra",
    "all_edge_shd_reversed",
    "all_edge_shd_status",
    "all_edge_shd_reason",
)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _mean(values: Iterable[Any]) -> Optional[float]:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    return sum(nums) / len(nums) if nums else None


def _load_json_file_with_timeout(path: Path, timeout: float) -> tuple[Optional[Any], Optional[str]]:
    try:
        result = subprocess.run(
            ["/bin/cat", str(path)],
            check=False,
            capture_output=True,
            timeout=timeout,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return None, f"true_graph_read_timeout:{path}"
    except Exception as exc:
        return None, f"could_not_read_true_graph:{exc}"
    if result.returncode != 0:
        return None, f"missing_true_graph:{path}"
    try:
        return json.loads(result.stdout), None
    except Exception as exc:
        return None, f"could_not_parse_true_graph:{exc}"


def _load_true_edges(row: Mapping[str, Any], *, timeout: float) -> tuple[Optional[List[Mapping[str, Any]]], Optional[str]]:
    seed_dir = row.get("seed_dir")
    if not seed_dir:
        return None, "missing_seed_dir"
    graph_config_path = Path(str(seed_dir)) / "graph_config.json"
    graph_config, reason = _load_json_file_with_timeout(graph_config_path, timeout)
    if graph_config is None:
        return None, reason
    edges = graph_config.get("edges") if isinstance(graph_config, Mapping) else None
    if not isinstance(edges, list):
        return None, "true_graph_has_no_edges_list"
    return edges, None


def enrich_seed_rows(rows: List[Mapping[str, Any]], *, graph_read_timeout: float = 2.0) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    enriched: List[Dict[str, Any]] = []
    status_counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        new_row = dict(row)
        for field in SHD_FIELDS:
            new_row.pop(field, None)
        true_edges, reason = _load_true_edges(new_row, timeout=graph_read_timeout)
        predicted_edges = new_row.get("predicted_graph_edges")
        if not isinstance(predicted_edges, list):
            predicted_edges = []
        if true_edges is None:
            new_row.update(
                {
                    "all_edge_shd": None,
                    "all_edge_shd_missing": None,
                    "all_edge_shd_extra": None,
                    "all_edge_shd_reversed": None,
                    "all_edge_shd_status": "missing_true_graph",
                    "all_edge_shd_reason": reason,
                }
            )
            status_counts["missing_true_graph"] += 1
        else:
            shd = compute_directed_shd(predicted_edges, true_edges)
            new_row.update(
                {
                    "all_edge_shd": shd["shd"],
                    "all_edge_shd_missing": shd["missing"],
                    "all_edge_shd_extra": shd["extra"],
                    "all_edge_shd_reversed": shd["reversed"],
                    "all_edge_shd_status": shd["status"],
                    "all_edge_shd_reason": None,
                }
            )
            status_counts["ok"] += 1
        enriched.append(new_row)
    return enriched, dict(status_counts)


def enrich_summary(
    summary: Mapping[str, Mapping[str, Any]],
    rows: List[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("experiment_id"))].append(row)

    enriched = {str(key): dict(value) for key, value in summary.items()}
    for experiment_id, experiment_rows in grouped.items():
        current = enriched.setdefault(experiment_id, {"num_seed_rows": len(experiment_rows)})
        current["mean_all_edge_shd"] = _mean(r.get("all_edge_shd") for r in experiment_rows)
        current["mean_all_edge_shd_missing"] = _mean(r.get("all_edge_shd_missing") for r in experiment_rows)
        current["mean_all_edge_shd_extra"] = _mean(r.get("all_edge_shd_extra") for r in experiment_rows)
        current["mean_all_edge_shd_reversed"] = _mean(r.get("all_edge_shd_reversed") for r in experiment_rows)
        current["num_shd_ok"] = sum(1 for r in experiment_rows if r.get("all_edge_shd_status") == "ok")
        current["num_shd_missing_true_graph"] = sum(
            1 for r in experiment_rows if r.get("all_edge_shd_status") == "missing_true_graph"
        )
    return enriched


def build_sanity_report(rows: List[Mapping[str, Any]], summary: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    targets = [
        "model_comparison_gpt-5-mini_4nodes",
        "model_comparison_gpt-5-mini_6nodes",
        "model_comparison_gpt-5.2-high_4nodes",
        "model_comparison_gpt-5.2-high_6nodes",
        "golden_4_main",
        "golden_6_main",
        "freqparent_4_main",
        "freqparent_6_main",
    ]
    status_counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        status_counts[str(row.get("all_edge_shd_status"))] += 1
    return {
        "total_seed_rows": len(rows),
        "shd_ok": status_counts.get("ok", 0),
        "missing_true_graph": status_counts.get("missing_true_graph", 0),
        "status_counts": dict(sorted(status_counts.items())),
        "key_experiments": {
            key: {
                "present": key in summary,
                "mean_all_edge_shd": (summary.get(key) or {}).get("mean_all_edge_shd"),
                "num_shd_ok": (summary.get(key) or {}).get("num_shd_ok"),
                "num_shd_missing_true_graph": (summary.get(key) or {}).get("num_shd_missing_true_graph"),
            }
            for key in targets
        },
    }


def enrich_pair(
    per_seed_path: Path,
    summary_path: Path,
    *,
    suffix: str = "_with_shd",
    graph_read_timeout: float = 2.0,
) -> Dict[str, Any]:
    rows = _read_json(per_seed_path)
    if not isinstance(rows, list):
        raise TypeError(f"{per_seed_path} must contain a JSON list")
    summary = _read_json(summary_path)
    if not isinstance(summary, Mapping):
        raise TypeError(f"{summary_path} must contain a JSON object")

    enriched_rows, status_counts = enrich_seed_rows(rows, graph_read_timeout=graph_read_timeout)
    enriched_summary = enrich_summary(summary, enriched_rows)

    seed_out = per_seed_path.with_name(per_seed_path.stem + suffix + per_seed_path.suffix)
    summary_out = summary_path.with_name(summary_path.stem + suffix + summary_path.suffix)
    report_out = per_seed_path.with_name(per_seed_path.stem + suffix + "_sanity_report.json")
    report = build_sanity_report(enriched_rows, enriched_summary)
    report["input_per_seed_path"] = str(per_seed_path)
    report["input_summary_path"] = str(summary_path)
    report["output_per_seed_path"] = str(seed_out)
    report["output_summary_path"] = str(summary_out)
    report["status_counts"] = dict(status_counts)

    _write_json(seed_out, enriched_rows)
    _write_json(summary_out, enriched_summary)
    _write_json(report_out, report)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Add directed SHD fields to CausaLab re-eval result JSON files.")
    parser.add_argument("--per-seed", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--suffix", default="_with_shd")
    parser.add_argument("--graph-read-timeout", type=float, default=2.0)
    args = parser.parse_args(argv)
    report = enrich_pair(args.per_seed, args.summary, suffix=args.suffix, graph_read_timeout=args.graph_read_timeout)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
