#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_dataset_checksums() -> None:
    checksum_path = REPO_ROOT / "release/causalab_dataset/checksums.sha256"
    dataset_root = checksum_path.parent
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel_path = line.split(maxsplit=1)
        file_path = dataset_root / rel_path
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if digest != expected:
            raise AssertionError(f"dataset checksum mismatch: {rel_path}")
    print("OK dataset checksums")


def check_dataset_manifest() -> None:
    manifest_path = REPO_ROOT / "release/causalab_dataset/manifest.json"
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise AssertionError("dataset manifest must be a JSON object")
    required = {"dataset_name", "files"}
    missing = sorted(required - set(manifest))
    if missing:
        raise AssertionError(f"dataset manifest missing keys: {missing}")
    print("OK dataset manifest")


def check_sample_run() -> None:
    sample = (
        REPO_ROOT
        / "examples/sample_runs/react_simple-mem/obs_Causal_gpt-5-mini/4nodes/"
        / "20260223-2134_dsl_right/4nodes_0_53calls/seed_1"
    )
    required = [
        "graph_config.json",
        "source_config.json",
        "Reactor Lab Causal_Causal_1_data.json",
        "Reactor Lab Causal_Causal_1_tracking_simple.jsonl",
        "raw_io.jsonl",
    ]
    missing = [name for name in required if not (sample / name).exists()]
    if missing:
        raise AssertionError(f"sample run missing files: {missing}")
    print("OK sample visualization/ReEval run")


def main(argv: list[str] | None = None) -> int:
    if argv:
        raise SystemExit("validate_release_artifacts.py does not accept arguments")
    check_dataset_checksums()
    check_dataset_manifest()
    check_sample_run()
    print("All release artifact checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
