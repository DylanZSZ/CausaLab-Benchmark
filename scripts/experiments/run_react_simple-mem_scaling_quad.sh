#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

setup_repo_environment
activate_discoveryworld_env
enter_repo_root

export MODE="${MODE:-validation}"
export ONLY_SETTINGS="${ONLY_SETTINGS:-}"
export SETTING_JOBS="${SETTING_JOBS:-2}"
export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export DRY_RUN="${DRY_RUN:-0}"
export MODEL="${MODEL:-gpt-5-mini}"
export CONFIG_FILE="${CONFIG_FILE:-agents/recoma/configs/react-simple-memory.jsonnet}"
export OPENAI_API_BASE="${OPENAI_API_BASE:-https://api.openai.com/v1}"

print_runtime_header "run_react_simple-mem_scaling_quad"
echo "Mode: ${MODE}"
echo "Only settings: ${ONLY_SETTINGS:-<all>}"
echo "Setting jobs: ${SETTING_JOBS}"
echo "Dry run: ${DRY_RUN}"
echo "Model: ${MODEL}"
echo "Config: ${CONFIG_FILE}"

ensure_openai_api_key_if_needed

if [[ "$MODE" != "validation" && "$MODE" != "full" ]]; then
  echo "ERROR: MODE must be one of: validation, full" >&2
  exit 1
fi

default_graph_limit() {
  if [[ "$MODE" == "validation" ]]; then
    echo "3"
  else
    echo "0"
  fi
}

default_batch_size() {
  if [[ "$MODE" == "validation" ]]; then
    echo "3"
  else
    echo "25"
  fi
}

output_root() {
  local suffix="scaling"
  if [[ "$MODE" == "validation" ]]; then
    suffix="scaling_validation"
  fi
  echo "$ROOT/output_dir/react_simple-mem/obs_CausalQuadHard_${MODEL}/4nodes_quad_hard/${suffix}"
}

effective_graph_limit="${GRAPH_LIMIT:-$(default_graph_limit)}"
effective_batch_size="${BATCH_SIZE:-$(default_batch_size)}"
quad_output_root="$(output_root)"

echo "Graph group: 4nodes_quad_hard.jsonl"
echo "Output root: ${quad_output_root}"
echo "GRAPH_LIMIT: ${effective_graph_limit}"
echo "BATCH_SIZE: ${effective_batch_size}"

env \
  MODEL="${MODEL}" \
  CONFIG_FILE="${CONFIG_FILE}" \
  NODE_COUNT="4" \
  CAUSAL_GRAPH_GROUP="4nodes_quad_hard.jsonl" \
  OBSERVATION_COUNTS="3 6 12 24" \
  INTERVENTION_COUNTS="3 6 12 24" \
  FIXED_OBS="3" \
  BASE_MAX_ENV_CALLS="29" \
  SCALING_BASE_OUTPUT_DIR="${quad_output_root}" \
  ONLY_SETTINGS="${ONLY_SETTINGS}" \
  GRAPH_LIMIT="${effective_graph_limit}" \
  BATCH_SIZE="${effective_batch_size}" \
  SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH}" \
  DRY_RUN="${DRY_RUN}" \
  REACTOR_TASK_PROMPT_MODE="dsl_quad" \
  PROMPT_NAME="dsl_quad" \
  bash "$SCRIPT_DIR/run_react_simple-mem_scaling_suite.sh"

if [[ "$MODE" == "validation" && "$DRY_RUN" != "1" ]]; then
  python "$ROOT/scripts/verify_scaling_runs.py" \
    "${quad_output_root}" \
    --output-dir "$ROOT/output_dir/analysis/quad_scaling_validation"
fi

echo "============================================================================"
echo "Quadratic scaling orchestration completed successfully."
echo "Mode: ${MODE}"
echo "GRAPH_LIMIT: ${effective_graph_limit}"
echo "BATCH_SIZE: ${effective_batch_size}"
if [[ "$MODE" == "validation" ]]; then
  echo "Validation report: $ROOT/output_dir/analysis/quad_scaling_validation"
fi
echo "Stable full command:"
echo "MODE=full bash scripts/experiments/run_react_simple-mem_scaling_quad.sh"
