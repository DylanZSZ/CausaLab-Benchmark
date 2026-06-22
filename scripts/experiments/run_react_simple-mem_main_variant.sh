#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

safe_model_name() {
  echo "$1" | sed 's#[^A-Za-z0-9_.-]#_#g'
}

require_env_var() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: required environment variable is not set: ${name}" >&2
    exit 1
  fi
}

require_env_var OUTPUT_ROOT_PREFIX
require_env_var SETTING_DIR_NAME

export MODEL="${MODEL:-gpt-5-mini}"
export EXPERIMENT_FAMILY="${EXPERIMENT_FAMILY:-main_suite}"
export OUTPUT_TAG="${OUTPUT_TAG:-${SETTING_DIR_NAME}}"
export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-4nodes.jsonl}"
export CAUSAL_INITIAL_OBSERVATIONS="${CAUSAL_INITIAL_OBSERVATIONS:-2}"
export INTERVENTION_BUDGET="${INTERVENTION_BUDGET:-12}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl}"
export PROMPT_NAME="${PROMPT_NAME:-$REACTOR_TASK_PROMPT_MODE}"
export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export BATCH_SIZE="${BATCH_SIZE:-10}"
export GRAPH_LIMIT="${GRAPH_LIMIT:-0}"
export DRY_RUN="${DRY_RUN:-0}"

SAFE_MODEL="$(safe_model_name "$MODEL")"
DEFAULT_BASE_OUTPUT_DIR="$ROOT/output_dir/react_simple-mem/${OUTPUT_ROOT_PREFIX}_${SAFE_MODEL}/${SETTING_DIR_NAME}"
export BASE_OUTPUT_DIR_OVERRIDE="${BASE_OUTPUT_DIR_OVERRIDE:-$DEFAULT_BASE_OUTPUT_DIR}"

if [[ -z "${EXPERIMENT_SUBDIR_OVERRIDE:-}" ]]; then
  RUN_STAMP="$(date +%Y%m%d-%H%M%S)"
  export EXPERIMENT_SUBDIR_OVERRIDE="${RUN_STAMP}_${PROMPT_NAME}"
fi

bash "$SCRIPT_DIR/run_react_simple-mem_experiment.sh"
