#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

ROOT="${ROOT:-$(repo_root)}"
SOURCE_GRAPH_GROUP="${SOURCE_GRAPH_GROUP:-$ROOT/causal_graph_configs/6nodes.jsonl}"

DEFAULT_GRAPH_IDS="$(python3 - <<'PY'
print(",".join(f"6nodes_{i}" for i in range(10, 50)))
PY
)"

export GRAPH_IDS_CSV="${GRAPH_IDS_CSV:-$DEFAULT_GRAPH_IDS}"
export OUTPUT_TAG="${OUTPUT_TAG:-rerun_6nodes_10_49}"
export EXPERIMENT_FAMILY="${EXPERIMENT_FAMILY:-rerun_selected_cases}"
export NODE_COUNT="${NODE_COUNT:-6}"

TEMP_GRAPH_GROUP="$(mktemp "${TMPDIR:-/tmp}/rerun_selected_6nodes_XXXXXX.jsonl")"
cleanup_temp_group() {
  if [[ -n "${TEMP_GRAPH_GROUP:-}" && -f "$TEMP_GRAPH_GROUP" ]]; then
    rm -f "$TEMP_GRAPH_GROUP"
  fi
}
trap cleanup_temp_group EXIT

SOURCE_GRAPH_GROUP="$SOURCE_GRAPH_GROUP" \
GRAPH_IDS_CSV="$GRAPH_IDS_CSV" \
TEMP_GRAPH_GROUP="$TEMP_GRAPH_GROUP" \
python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

source_path = Path(os.environ["SOURCE_GRAPH_GROUP"])
target_path = Path(os.environ["TEMP_GRAPH_GROUP"])
graph_ids = [item.strip() for item in os.environ["GRAPH_IDS_CSV"].split(",") if item.strip()]

if not source_path.is_file():
    print(f"ERROR: source graph group not found: {source_path}", file=sys.stderr)
    sys.exit(1)

wanted = set(graph_ids)
selected = []

with source_path.open("r", encoding="utf-8") as src, target_path.open("w", encoding="utf-8") as dst:
    for line in src:
        raw = line.strip()
        if not raw:
            continue
        graph = json.loads(raw)
        graph_id = graph.get("graph_id")
        if graph_id in wanted:
            dst.write(json.dumps(graph, ensure_ascii=False) + "\n")
            selected.append(graph_id)

missing = [graph_id for graph_id in graph_ids if graph_id not in selected]
if missing:
    print("ERROR: missing graph_ids in source config:", file=sys.stderr)
    for graph_id in missing:
        print(f"  - {graph_id}", file=sys.stderr)
    sys.exit(1)

print(
    f"Prepared filtered graph group with {len(selected)} cases at {target_path}",
    file=sys.stderr,
)
PY

echo "============================================================================"
echo "Rerunning selected 6-node cases"
echo "Source graph group: $SOURCE_GRAPH_GROUP"
echo "Filtered graph group: $TEMP_GRAPH_GROUP"
echo "Graph IDs: $GRAPH_IDS_CSV"
echo "Output tag: $OUTPUT_TAG"
echo "Experiment family: $EXPERIMENT_FAMILY"
echo "============================================================================"

export CAUSAL_GRAPH_GROUP="$TEMP_GRAPH_GROUP"

bash "$SCRIPT_DIR/run_react_simple-mem_experiment.sh"
