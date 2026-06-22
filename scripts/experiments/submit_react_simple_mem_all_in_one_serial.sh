#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

GRAPH_LIMIT="${GRAPH_LIMIT:-0}"
DRY_RUN="${DRY_RUN:-0}"
SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
BATCH_SIZE="${BATCH_SIZE:-25}"
MAX_PARALLEL="${MAX_PARALLEL:-1}"
TEST_MAX_ENV_CALLS="${TEST_MAX_ENV_CALLS:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --subset)
      GRAPH_LIMIT=5
      BATCH_SIZE=5
      TEST_MAX_ENV_CALLS=3
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --seeds)
      SEEDS_PER_GRAPH="$2"
      shift 2
      ;;
    --batch-size)
      BATCH_SIZE="$2"
      shift 2
      ;;
    --max-parallel)
      MAX_PARALLEL="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if ! [[ "$MAX_PARALLEL" =~ ^[1-9][0-9]*$ ]]; then
  echo "MAX_PARALLEL must be a positive integer, got: $MAX_PARALLEL" >&2
  exit 1
fi

running_jobs=0
stage_failed=0

run_job() {
  local label="$1"
  local script="$2"
  shift 2

  if [[ "${DRY_RUN}" == "1" ]]; then
    echo "[DRY_RUN][${label}] env GRAPH_LIMIT=${GRAPH_LIMIT} DRY_RUN=${DRY_RUN} SEEDS_PER_GRAPH=${SEEDS_PER_GRAPH} BATCH_SIZE=${BATCH_SIZE} TEST_MAX_ENV_CALLS=${TEST_MAX_ENV_CALLS} $* bash ${script}"
    return 0
  fi

  while (( running_jobs >= MAX_PARALLEL )); do
    if ! wait -n; then
      stage_failed=1
    fi
    running_jobs=$((running_jobs - 1))
  done

  (
    echo "[$(date '+%F %T')] START ${label}"
    if env \
      GRAPH_LIMIT="${GRAPH_LIMIT}" \
      DRY_RUN="${DRY_RUN}" \
      SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH}" \
      BATCH_SIZE="${BATCH_SIZE}" \
      TEST_MAX_ENV_CALLS="${TEST_MAX_ENV_CALLS}" \
      "$@" \
      bash "${script}"; then
      echo "[$(date '+%F %T')] END   ${label} (success)"
    else
      status=$?
      echo "[$(date '+%F %T')] END   ${label} (failed, exit=${status})" >&2
      exit "${status}"
    fi
  ) &
  running_jobs=$((running_jobs + 1))
}

wait_for_stage() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    return 0
  fi

  while (( running_jobs > 0 )); do
    if ! wait -n; then
      stage_failed=1
    fi
    running_jobs=$((running_jobs - 1))
  done

  if (( stage_failed != 0 )); then
    echo "A job failed in the current stage." >&2
    exit 1
  fi
}

echo "== causal vs non-causal =="
run_job \
  "causal_or_not" \
  "$SCRIPT_DIR/run_react_simple-mem_parallel_causal_or_not.sh"
wait_for_stage

echo "== gpt-5.2 model compare runs =="
for node in 3 6 7; do
  run_job \
    "gpt52_${node}nodes" \
    "$SCRIPT_DIR/run_react_simple-mem_parallel_gpt52.sh" \
    "NODE_COUNT=${node}"
done
wait_for_stage

echo "== model compare summary =="
if [[ "${DRY_RUN}" == "1" ]]; then
  python "$SCRIPT_DIR/compare_react_simple_mem_model_scores.py"
else
  python "$SCRIPT_DIR/compare_react_simple_mem_model_scores.py"
fi

echo "== hidden-variable variants =="
if [[ "${DRY_RUN}" == "1" ]]; then
  python "$SCRIPT_DIR/generate_hidden_variant_configs.py" --dry-run
else
  python "$SCRIPT_DIR/generate_hidden_variant_configs.py"
fi

HIDDEN_BASE="$ROOT/output_dir/react_simple-mem/obs_CausalHidden_gpt-5-mini/4nodes_hidden_variants"
HIDDEN_FILES=(
  "4nodes_hidden_vrange_pm0p5.jsonl:hidden_vrange_pm0p5"
  "4nodes_hidden_vrange_pm5.jsonl:hidden_vrange_pm5"
  "4nodes_hidden_vrange_pm50.jsonl:hidden_vrange_pm50"
  "4nodes_hidden_n1.jsonl:hidden_n1"
  "4nodes_hidden_n2.jsonl:hidden_n2"
  "4nodes_hidden_n3.jsonl:hidden_n3"
)

for spec in "${HIDDEN_FILES[@]}"; do
  IFS=":" read -r graph_group output_tag <<< "$spec"
  run_job \
    "${output_tag}" \
    "$SCRIPT_DIR/run_react_simple-mem_parallel_hidden_variants.sh" \
    "CAUSAL_GRAPH_GROUP=${graph_group}" \
    "OUTPUT_TAG=${output_tag}" \
    "MODEL=gpt-5-mini" \
    "BASE_OUTPUT_DIR_OVERRIDE=${HIDDEN_BASE}" \
    "REACTOR_TASK_PROMPT_MODE=dsl_hidden" \
    "PROMPT_NAME=dsl_hidden"
done
wait_for_stage

echo "== scaling observation/intervention suites =="
SCALING_BASE="$ROOT/output_dir/react_simple-mem/obs_Causal_gpt-5-mini/4nodes/scaling"

for obs in 3 6 12 24; do
  run_job \
    "scaling_observation_o${obs}_i0" \
    "$SCRIPT_DIR/run_react_simple-mem_scaling_observation.sh" \
    "MODEL=gpt-5-mini" \
    "OUTPUT_TAG=scaling_observation_o${obs}_i0" \
    "CAUSAL_GRAPH_GROUP=4nodes.jsonl" \
    "CAUSAL_INITIAL_OBSERVATIONS=${obs}" \
    "INTERVENTION_BUDGET=0" \
    "BASE_OUTPUT_DIR_OVERRIDE=${SCALING_BASE}"
done

for budget in 3 6 12 24; do
  run_job \
    "scaling_intervention_o0_i${budget}" \
    "$SCRIPT_DIR/run_react_simple-mem_scaling_intervention.sh" \
    "MODEL=gpt-5-mini" \
    "OUTPUT_TAG=scaling_intervention_o0_i${budget}" \
    "CAUSAL_GRAPH_GROUP=4nodes.jsonl" \
    "CAUSAL_INITIAL_OBSERVATIONS=0" \
    "INTERVENTION_BUDGET=${budget}" \
    "BASE_OUTPUT_DIR_OVERRIDE=${SCALING_BASE}"
done

for budget in 3 6 12 24; do
  run_job \
    "scaling_obs3_intervention_o3_i${budget}" \
    "$SCRIPT_DIR/run_react_simple-mem_scaling_obs3_intervention.sh" \
    "MODEL=gpt-5-mini" \
    "OUTPUT_TAG=scaling_obs3_intervention_o3_i${budget}" \
    "CAUSAL_GRAPH_GROUP=4nodes.jsonl" \
    "CAUSAL_INITIAL_OBSERVATIONS=3" \
    "INTERVENTION_BUDGET=${budget}" \
    "BASE_OUTPUT_DIR_OVERRIDE=${SCALING_BASE}"
done
wait_for_stage

echo "All suites completed with MAX_PARALLEL=${MAX_PARALLEL}."

