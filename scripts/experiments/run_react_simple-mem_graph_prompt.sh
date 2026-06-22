#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

setup_repo_environment
activate_discoveryworld_env
enter_repo_root

export MODE="${MODE:-validation}"
export NODES="${NODES:-all}"
export MODEL="${MODEL:-gpt-5-mini}"
export DIFF="${DIFF:-Causal}"
export TASK="${TASK:-Reactor Lab Causal}"
export FREQ_ESTIMATOR="${FREQ_ESTIMATOR:-0}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl}"
export PROMPT_NAME="${PROMPT_NAME:-dsl_graph_known}"
export REACTOR_TASK_INCLUDE_GRAPH_STRUCTURE="${REACTOR_TASK_INCLUDE_GRAPH_STRUCTURE:-1}"
export DRY_RUN="${DRY_RUN:-0}"
export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export TEST_MAX_ENV_CALLS="${TEST_MAX_ENV_CALLS:-0}"
export VALIDATION_GRAPH_LIMIT="${VALIDATION_GRAPH_LIMIT:-5}"
export VALIDATION_BATCH_SIZE="${VALIDATION_BATCH_SIZE:-5}"
export FULL_GRAPH_LIMIT="${FULL_GRAPH_LIMIT:-0}"
export FULL_BATCH_SIZE="${FULL_BATCH_SIZE:-10}"

print_runtime_header "run_react_simple-mem_graph_prompt"
echo "Mode: ${MODE}"
echo "Nodes: ${NODES}"
echo "Model: ${MODEL}"
echo "Prompt mode: ${REACTOR_TASK_PROMPT_MODE}"
echo "Prompt name: ${PROMPT_NAME}"
echo "Include graph structure: ${REACTOR_TASK_INCLUDE_GRAPH_STRUCTURE}"
echo "Dry run: ${DRY_RUN}"

if [[ "$MODE" != "validation" && "$MODE" != "full" ]]; then
  echo "ERROR: MODE must be one of: validation, full" >&2
  exit 1
fi

if [[ "$NODES" != "4" && "$NODES" != "6" && "$NODES" != "all" ]]; then
  echo "ERROR: NODES must be one of: 4, 6, all" >&2
  exit 1
fi

if [[ "${FREQ_ESTIMATOR}" != "0" ]]; then
  echo "ERROR: This experiment is defined for observation setting only (FREQ_ESTIMATOR=0)." >&2
  exit 1
fi

safe_model_name() {
  echo "$1" | sed 's#[^A-Za-z0-9_.-]#_#g'
}

node_graph_group() {
  case "$1" in
    4) echo "4nodes.jsonl" ;;
    6) echo "6nodes.jsonl" ;;
    *)
      echo "ERROR: unsupported node count: $1" >&2
      exit 1
      ;;
  esac
}

pick_graph_limit() {
  if [[ -n "${GRAPH_LIMIT+x}" ]]; then
    echo "${GRAPH_LIMIT}"
  elif [[ "$MODE" == "validation" ]]; then
    echo "${VALIDATION_GRAPH_LIMIT}"
  else
    echo "${FULL_GRAPH_LIMIT}"
  fi
}

pick_batch_size() {
  if [[ -n "${BATCH_SIZE+x}" ]]; then
    echo "${BATCH_SIZE}"
  elif [[ "$MODE" == "validation" ]]; then
    echo "${VALIDATION_BATCH_SIZE}"
  else
    echo "${FULL_BATCH_SIZE}"
  fi
}

summarize_latest_run() {
  local graph_group="$1"
  local graph_stem="${graph_group%.jsonl}"
  local safe_model
  local base_root
  local latest_prompt_dir

  safe_model="$(safe_model_name "$MODEL")"
  base_root="$ROOT/output_dir/react_simple-mem/obs_${DIFF}_${safe_model}/${graph_stem}"
  if [[ ! -d "$base_root" ]]; then
    echo "ERROR: expected run root not found: $base_root" >&2
    return 1
  fi

  latest_prompt_dir="$(
    find "$base_root" -mindepth 1 -maxdepth 1 -type d -name "*_${PROMPT_NAME}" 2>/dev/null \
      | sort \
      | tail -n 1
  )"
  if [[ -z "$latest_prompt_dir" ]]; then
    echo "ERROR: no prompt directory found under $base_root for PROMPT_NAME=$PROMPT_NAME" >&2
    return 1
  fi

  python3 - "$latest_prompt_dir" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1])
complete_files = sorted(root.glob("**/*_complete.txt"))
successes = 0
for path in complete_files:
    try:
        successes += int(path.read_text(encoding="utf-8").strip() == "1")
    except Exception:
        pass

marker = "KNOWN GRAPH STRUCTURE FOR THIS RUN:"
marker_found = False
sample_tracking = None
for path in sorted(root.glob("**/*_tracking.jsonl")):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        continue
    if marker in text:
        marker_found = True
        sample_tracking = path
        break

print(f"Run root: {root}")
print(f"Total tasks: {len(complete_files)}")
print(f"Completed successfully: {successes}")
print(f"Prompt marker found: {marker_found}")
if sample_tracking is not None:
    print(f"Sample tracking file: {sample_tracking}")

if not complete_files:
    raise SystemExit("No completion flags were produced.")
if not marker_found:
    raise SystemExit("Prompt marker not found in tracking logs.")
PY
}

run_one_node() {
  local node="$1"
  local graph_group
  local effective_graph_limit
  local effective_batch_size

  graph_group="$(node_graph_group "$node")"
  effective_graph_limit="$(pick_graph_limit)"
  effective_batch_size="$(pick_batch_size)"

  echo "----------------------------------------------------------------------------"
  echo "Launching node=${node}"
  echo "Graph group: ${graph_group}"
  echo "GRAPH_LIMIT: ${effective_graph_limit}"
  echo "BATCH_SIZE: ${effective_batch_size}"
  echo "----------------------------------------------------------------------------"

  env \
    CAUSAL_GRAPH_GROUP="${graph_group}" \
    GRAPH_LIMIT="${effective_graph_limit}" \
    BATCH_SIZE="${effective_batch_size}" \
    TEST_MAX_ENV_CALLS="${TEST_MAX_ENV_CALLS}" \
    SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH}" \
    DRY_RUN="${DRY_RUN}" \
    MODEL="${MODEL}" \
    DIFF="${DIFF}" \
    TASK="${TASK}" \
    FREQ_ESTIMATOR="${FREQ_ESTIMATOR}" \
    REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE}" \
    PROMPT_NAME="${PROMPT_NAME}" \
    REACTOR_TASK_INCLUDE_GRAPH_STRUCTURE="${REACTOR_TASK_INCLUDE_GRAPH_STRUCTURE}" \
    bash "$SCRIPT_DIR/run_react_simple-mem_parallel.sh"

  if [[ "$DRY_RUN" != "1" ]]; then
    summarize_latest_run "${graph_group}"
  fi
}

declare -a NODE_LIST=()
if [[ "$NODES" == "all" ]]; then
  NODE_LIST=(4 6)
else
  NODE_LIST=("$NODES")
fi

for node in "${NODE_LIST[@]}"; do
  run_one_node "$node"
done

echo "============================================================================"
echo "Graph-structure prompt experiment finished."
echo "Mode: ${MODE}"
echo "Nodes: ${NODE_LIST[*]}"
echo "============================================================================"
