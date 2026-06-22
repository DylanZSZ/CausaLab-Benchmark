#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from causalab_reeval.reeval_core import (  # noqa: E402
    summarize_seed_for_reeval,
    summarize_seed_for_stage1,
)
from causalab_reeval.run_lightweight_reeval import (  # noqa: E402
    SimpleOpenAIClient,
    flatten_seed_result,
    render_summary_markdown,
    summarize_experiments,
)


@dataclass(frozen=True)
class SuiteSpec:
    name: str
    root: Path
    case_prefix: str
    expected_cases: int = 50
    model_label: str = "gpt-5-mini"


def now() -> datetime:
    return datetime.now().astimezone()


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def write_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_case_id(case_dir_name: str, case_prefix: str) -> Optional[int]:
    match = re.match(rf"^{re.escape(case_prefix)}_(\d+)_", case_dir_name)
    if not match:
        return None
    return int(match.group(1))


def best_completed_seed_in_case(case_dir: Path) -> Optional[Tuple[Path, float, str]]:
    # Prefer explicit completion markers; fallback to materialized tracking logs
    # to support merged directories where *_complete.txt was not copied.
    best: Optional[Tuple[int, Path, float, str]] = None
    for seed_dir in sorted(case_dir.glob("seed_*")):
        if not seed_dir.is_dir():
            continue
        complete_files = sorted(seed_dir.glob("*_complete.txt"))
        if not complete_files:
            tracking_files = sorted(seed_dir.glob("*_tracking_simple.jsonl")) or sorted(seed_dir.glob("*_tracking.jsonl"))
            if not tracking_files:
                continue
            newest = max(tracking_files, key=lambda p: p.stat().st_mtime)
            candidate = (1, seed_dir.resolve(), newest.stat().st_mtime, str(case_dir.resolve()))
        else:
            newest = max(complete_files, key=lambda p: p.stat().st_mtime)
            candidate = (2, seed_dir.resolve(), newest.stat().st_mtime, str(case_dir.resolve()))

        if best is None or candidate[0] > best[0] or (candidate[0] == best[0] and candidate[2] > best[2]):
            best = candidate
    if best is None:
        return None
    return (best[1], best[2], best[3])


def collect_suite_case_coverage(spec: SuiteSpec) -> Dict[str, object]:
    case_best: Dict[int, Tuple[Path, float, str]] = {}
    if spec.root.exists():
        for case_dir in spec.root.glob(f"**/{spec.case_prefix}_*_*calls"):
            if not case_dir.is_dir():
                continue
            case_id = parse_case_id(case_dir.name, spec.case_prefix)
            if case_id is None:
                continue
            if case_id < 0 or case_id >= spec.expected_cases:
                continue
            best_seed = best_completed_seed_in_case(case_dir)
            if best_seed is None:
                continue
            prev = case_best.get(case_id)
            if prev is None or best_seed[1] > prev[1]:
                case_best[case_id] = best_seed

    missing_ids = [i for i in range(spec.expected_cases) if i not in case_best]
    selected_seed_map = {
        str(case_id): {
            "seed_dir": str(seed_info[0]),
            "case_dir": seed_info[2],
            "complete_marker_mtime": seed_info[1],
        }
        for case_id, seed_info in sorted(case_best.items())
    }
    return {
        "suite": spec.name,
        "root": str(spec.root),
        "expected_cases": spec.expected_cases,
        "completed_cases": len(case_best),
        "missing_case_ids": missing_ids,
        "done": len(missing_ids) == 0,
        "selected_seed_map": selected_seed_map,
    }


def render_monitor_markdown(payload: Dict[str, object]) -> str:
    lines = [
        "# Oracle Completion Monitor",
        "",
        f"- checked_at: {payload['checked_at']}",
        f"- next_check_at: {payload.get('next_check_at') or ''}",
        f"- interval_seconds: {payload['interval_seconds']}",
        f"- all_done: {payload['all_done']}",
        f"- reeval_started: {payload.get('reeval_started', False)}",
        f"- reeval_output_dir: {payload.get('reeval_output_dir') or ''}",
        "",
        "| suite | completed | expected | done | missing_ids |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for suite in payload["suites"]:
        missing = ",".join(str(x) for x in suite["missing_case_ids"])
        lines.append(
            f"| {suite['suite']} | {suite['completed_cases']} | {suite['expected_cases']} | {suite['done']} | {missing} |"
        )
    lines.append("")
    return "\n".join(lines)


def run_full_reeval(
    *,
    full_suites: List[SuiteSpec],
    output_root: Path,
    parallelism: int,
    api_key: str,
    api_base: str,
) -> Path:
    timestamp = now().strftime("%Y%m%d-%H%M%S")
    run_name = f"full_new_suites_{timestamp}"
    output_dir = (output_root / run_name).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw_generation_outputs"
    raw_dir.mkdir(parents=True, exist_ok=True)

    suite_coverages: Dict[str, Dict[str, object]] = {}
    tasks: List[Dict[str, object]] = []
    for suite in full_suites:
        coverage = collect_suite_case_coverage(suite)
        suite_coverages[suite.name] = coverage
        missing = coverage["missing_case_ids"]
        if missing:
            raise RuntimeError(
                f"Suite {suite.name} is incomplete ({len(missing)} missing), cannot start full re-eval."
            )
        for case_id_str, seed_payload in coverage["selected_seed_map"].items():
            seed_dir = Path(seed_payload["seed_dir"])
            tasks.append(
                {
                    "group_id": "new_suites_full",
                    "experiment_id": suite.name,
                    "experiment_label": suite.name,
                    "inventory_model": suite.model_label,
                    "seed_dir": seed_dir,
                    "case_id": int(case_id_str),
                }
            )

    config = {
        "run_name": run_name,
        "timestamp": now().strftime("%Y%m%d-%H%M%S"),
        "selected_groups": ["new_suites_full"],
        "selected_experiment_count": len(full_suites),
        "max_seeds_per_experiment": 50,
        "parallelism": parallelism,
        "task_count": len(tasks),
        "api_base": api_base,
    }
    write_json(output_dir / "config.json", config)
    write_json(
        output_dir / "selected_tasks.json",
        [
            {
                "group_id": task["group_id"],
                "experiment_id": task["experiment_id"],
                "experiment_label": task["experiment_label"],
                "inventory_model": task["inventory_model"],
                "seed_dir": str(task["seed_dir"]),
                "case_id": task["case_id"],
            }
            for task in tasks
        ],
    )
    write_json(output_dir / "suite_case_sources.json", suite_coverages)

    client = SimpleOpenAIClient(api_key=api_key, base_url=api_base)

    nested_results = []
    flat_rows = []
    completed = 0
    total = len(tasks)

    with ThreadPoolExecutor(max_workers=parallelism) as executor:
        future_map = {
            executor.submit(summarize_seed_for_reeval, task["seed_dir"], client): task
            for task in tasks
        }
        for future in as_completed(future_map):
            task = future_map[future]
            try:
                seed_result = future.result()
            except Exception as exc:
                seed_result = summarize_seed_for_stage1(task["seed_dir"])
                seed_result["task1_root_formula_generation"] = {"status": "exception", "reason": str(exc)}
                seed_result["task1_root_formula_eval"] = {}
                seed_result["task2_graph_structure_generation"] = {"status": "exception", "reason": str(exc)}
                seed_result["task2_graph_structure_eval"] = {
                    "all_edge_metrics": {},
                    "freq_edge_metrics": {},
                    "freq_weight_metrics": {},
                }

            completed += 1
            nested_results.append({"task": {**task, "seed_dir": str(task["seed_dir"])}, "seed_result": seed_result})
            flat_rows.append(flatten_seed_result(task, seed_result))

            safe_name = f"{task['experiment_id']}__case{task['case_id']:02d}__{task['seed_dir'].name}.json"
            write_json(
                raw_dir / safe_name,
                {
                    "task": {**task, "seed_dir": str(task["seed_dir"])},
                    "source_final_hypothesis": seed_result.get("source_final_hypothesis"),
                    "task1_root_formula_generation": seed_result.get("task1_root_formula_generation"),
                    "task1_root_formula_eval": seed_result.get("task1_root_formula_eval"),
                    "task2_graph_structure_generation": seed_result.get("task2_graph_structure_generation"),
                    "task2_graph_structure_eval": seed_result.get("task2_graph_structure_eval"),
                },
            )
            print(
                f"[{completed}/{total}] re-eval {task['experiment_id']} case={task['case_id']} seed={task['seed_dir']}",
                flush=True,
            )

    flat_rows = sorted(flat_rows, key=lambda row: (row["experiment_id"], row["case_dir"]))
    experiment_summary = summarize_experiments(flat_rows)

    write_json(output_dir / "nested_results.json", {"results": nested_results})
    write_json(output_dir / "per_seed_results.json", flat_rows)
    write_json(output_dir / "per_experiment_summary.json", experiment_summary)

    if flat_rows:
        with (output_dir / "per_seed_results.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(flat_rows[0].keys()))
            writer.writeheader()
            writer.writerows(flat_rows)

    (output_dir / "summary.md").write_text(
        render_summary_markdown(config, experiment_summary),
        encoding="utf-8",
    )
    return output_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Poll oracle completion status and auto-start full re-eval for new suites when complete."
    )
    parser.add_argument("--interval-seconds", type=int, default=1800)
    parser.add_argument(
        "--monitor-dir",
        default="output_dir/analysis/oracle_completion_then_reeval",
        help="Directory for monitor status artifacts",
    )
    parser.add_argument(
        "--reeval-output-root",
        default="output_dir/reeval_runs",
        help="Output root for full re-eval run",
    )
    parser.add_argument("--parallelism", type=int, default=12)
    parser.add_argument(
        "--api-base",
        default=os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        help="OpenAI-compatible base URL",
    )
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    monitor_dir = (REPO_ROOT / args.monitor_dir).resolve()
    monitor_dir.mkdir(parents=True, exist_ok=True)
    status_json = monitor_dir / "status.json"
    status_md = monitor_dir / "status.md"

    monitor_suites = [
        SuiteSpec(
            name="oracle_4_main",
            root=REPO_ROOT / "output_dir/react_simple-mem/obs_CausalOracle_gpt-5-mini/4nodes_main",
            case_prefix="4nodes",
        ),
        SuiteSpec(
            name="oracle_6_main",
            root=REPO_ROOT / "output_dir/react_simple-mem/obs_CausalOracle_gpt-5-mini/6nodes_main",
            case_prefix="6nodes",
        ),
        SuiteSpec(
            name="oracle_4_scaling_3o0i",
            root=REPO_ROOT / "output_dir/react_simple-mem/obs_CausalOracle_gpt-5-mini/4nodes/scaling/3o0i",
            case_prefix="4nodes",
        ),
    ]

    full_suites = [
        *monitor_suites,
        SuiteSpec(
            name="freqparent_4_main",
            root=REPO_ROOT / "output_dir/react_simple-mem/obs_CausalFreqParent_gpt-5-mini/4nodes_main",
            case_prefix="4nodes",
        ),
        SuiteSpec(
            name="freqparent_6_main",
            root=REPO_ROOT / "output_dir/react_simple-mem/obs_CausalFreqParent_gpt-5-mini/6nodes_main",
            case_prefix="6nodes",
        ),
        SuiteSpec(
            name="hidden_freqnode_n1",
            root=REPO_ROOT
            / "output_dir/react_simple-mem/obs_CausalHiddenFreqNode_gpt-5-mini/4nodes_hidden_freq_node_priority/4nodes_hidden_freqnode_n1",
            case_prefix="4nodes",
        ),
        SuiteSpec(
            name="hidden_freqnode_n2",
            root=REPO_ROOT
            / "output_dir/react_simple-mem/obs_CausalHiddenFreqNode_gpt-5-mini/4nodes_hidden_freq_node_priority/4nodes_hidden_freqnode_n2",
            case_prefix="4nodes",
        ),
        SuiteSpec(
            name="hidden_freqnode_n3",
            root=REPO_ROOT
            / "output_dir/react_simple-mem/obs_CausalHiddenFreqNode_gpt-5-mini/4nodes_hidden_freq_node_priority/4nodes_hidden_freqnode_n3",
            case_prefix="4nodes",
        ),
        SuiteSpec(
            name="golden_4_main",
            root=REPO_ROOT / "output_dir/react_simple-mem/obs_CausalGolden_gpt-5-mini/4nodes_main",
            case_prefix="4nodes",
        ),
        SuiteSpec(
            name="golden_6_main",
            root=REPO_ROOT / "output_dir/react_simple-mem/obs_CausalGolden_gpt-5-mini/6nodes_main",
            case_prefix="6nodes",
        ),
    ]

    while True:
        checked_at = now()
        suite_coverages = [collect_suite_case_coverage(spec) for spec in monitor_suites]
        all_done = all(item["done"] for item in suite_coverages)
        next_check = None if all_done or args.once else checked_at + timedelta(seconds=args.interval_seconds)

        payload = {
            "checked_at": checked_at.isoformat(timespec="seconds"),
            "next_check_at": next_check.isoformat(timespec="seconds") if next_check else None,
            "interval_seconds": args.interval_seconds,
            "all_done": all_done,
            "reeval_started": False,
            "reeval_output_dir": None,
            "suites": suite_coverages,
        }

        if all_done:
            api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
            if not api_key:
                payload["reeval_started"] = False
                payload["reeval_error"] = "OPENAI_API_KEY is missing in environment; cannot start full re-eval."
                write_json(status_json, payload)
                status_md.write_text(render_monitor_markdown(payload), encoding="utf-8")
                print(payload["reeval_error"], flush=True)
                return 2

            try:
                output_dir = run_full_reeval(
                    full_suites=full_suites,
                    output_root=(REPO_ROOT / args.reeval_output_root),
                    parallelism=args.parallelism,
                    api_key=api_key,
                    api_base=args.api_base,
                )
                payload["reeval_started"] = True
                payload["reeval_output_dir"] = str(output_dir)
            except Exception as exc:
                payload["reeval_started"] = False
                payload["reeval_error"] = str(exc)
                write_json(status_json, payload)
                status_md.write_text(render_monitor_markdown(payload), encoding="utf-8")
                print(f"Failed to run full re-eval: {exc}", flush=True)
                return 3

            write_json(status_json, payload)
            status_md.write_text(render_monitor_markdown(payload), encoding="utf-8")
            print(f"Full re-eval completed: {payload['reeval_output_dir']}", flush=True)
            return 0

        write_json(status_json, payload)
        status_md.write_text(render_monitor_markdown(payload), encoding="utf-8")
        print(
            f"[{payload['checked_at']}] waiting for oracle completion; next check at {payload['next_check_at']}",
            flush=True,
        )

        if args.once:
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
