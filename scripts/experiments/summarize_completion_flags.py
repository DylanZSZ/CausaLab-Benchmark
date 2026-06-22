#!/usr/bin/env python3
"""Summarize CausaLab main-experiment completion flags.

Each Recoma seed directory writes one ``*_complete.txt`` file. The file contains
``1`` when the final task scorecard reports ``completedSuccessfully`` and ``0``
otherwise. This script recursively scans a run root and reports aggregate task
accuracy.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


CASE_RE = re.compile(r"^(?P<prefix>.+?)_(?P<case_id>\d+)_\d+calls$")


def read_flag(path: Path) -> tuple[Optional[int], str]:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception as exc:  # pragma: no cover - filesystem-specific
        return None, f"read_error:{exc}"
    token = text.split()[0] if text.split() else ""
    if token == "1":
        return 1, "ok"
    if token == "0":
        return 0, "ok"
    return None, f"invalid_flag:{token or '<empty>'}"


def infer_case_fields(flag_path: Path, root: Path) -> Dict[str, Any]:
    seed_dir = flag_path.parent
    case_dir = seed_dir.parent
    case_match = CASE_RE.match(case_dir.name)
    try:
        rel_seed_dir = str(seed_dir.relative_to(root))
    except ValueError:
        rel_seed_dir = str(seed_dir)
    return {
        "flag_file": str(flag_path),
        "seed_dir": str(seed_dir),
        "relative_seed_dir": rel_seed_dir,
        "case_dir": str(case_dir),
        "case_name": case_dir.name,
        "case_prefix": case_match.group("prefix") if case_match else None,
        "case_id": int(case_match.group("case_id")) if case_match else None,
        "seed_name": seed_dir.name,
    }


def collect_rows(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for flag_path in sorted(root.glob("**/*_complete.txt")):
        value, status = read_flag(flag_path)
        row = infer_case_fields(flag_path, root)
        row.update(
            {
                "completion_flag": value,
                "status": status,
                "success": value == 1,
            }
        )
        rows.append(row)
    return rows


def summarize_rows(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(rows)
    total = len(rows)
    success = sum(1 for row in rows if row.get("completion_flag") == 1)
    failure = sum(1 for row in rows if row.get("completion_flag") == 0)
    invalid = total - success - failure
    valid = success + failure
    return {
        "total_flags": total,
        "valid_flags": valid,
        "success": success,
        "failure": failure,
        "invalid": invalid,
        "success_rate": (success / valid) if valid else None,
    }


def summarize_by_case_prefix(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get("case_prefix") or "unknown")
        grouped[key].append(row)
    return {key: summarize_rows(value) for key, value in sorted(grouped.items())}


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: List[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "completion_flag",
        "success",
        "status",
        "case_prefix",
        "case_id",
        "case_name",
        "seed_name",
        "relative_seed_dir",
        "flag_file",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def render_summary(root: Path, summary: Mapping[str, Any], by_case_prefix: Mapping[str, Mapping[str, Any]]) -> str:
    rate = summary.get("success_rate")
    rate_text = "n/a" if rate is None else f"{100.0 * float(rate):.2f}%"
    lines = [
        f"Run root: {root}",
        f"Total completion flags: {summary['total_flags']}",
        f"Valid flags: {summary['valid_flags']}",
        f"Success (1): {summary['success']}",
        f"Failure (0): {summary['failure']}",
        f"Invalid/missing-value flags: {summary['invalid']}",
        f"Success rate: {rate_text}",
    ]
    if by_case_prefix:
        lines.extend(["", "By case prefix:"])
        for prefix, row in by_case_prefix.items():
            prefix_rate = row.get("success_rate")
            prefix_rate_text = "n/a" if prefix_rate is None else f"{100.0 * float(prefix_rate):.2f}%"
            lines.append(
                f"  {prefix}: {row['success']}/{row['valid_flags']} successful "
                f"({prefix_rate_text}), invalid={row['invalid']}"
            )
    return "\n".join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        type=Path,
        help="Run root to scan recursively, e.g. output_dir/.../20260618-155735_dsl",
    )
    parser.add_argument("--json-out", type=Path, help="Optional JSON summary output path.")
    parser.add_argument("--csv-out", type=Path, help="Optional per-seed CSV output path.")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Exit successfully even if no *_complete.txt files are found.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    if not root.exists():
        raise SystemExit(f"ERROR: run root does not exist: {root}")
    rows = collect_rows(root)
    if not rows and not args.allow_empty:
        raise SystemExit(f"ERROR: no *_complete.txt files found under {root}")

    summary = summarize_rows(rows)
    by_case_prefix = summarize_by_case_prefix(rows)
    payload = {
        "root": str(root),
        "summary": summary,
        "by_case_prefix": by_case_prefix,
        "rows": rows,
    }

    print(render_summary(root, summary, by_case_prefix))
    if args.json_out:
        write_json(args.json_out, payload)
    if args.csv_out:
        write_csv(args.csv_out, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
