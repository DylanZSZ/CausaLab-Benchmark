#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RUNNER="$SCRIPT_DIR/run_react_simple-mem_experiment.sh"
BASE_SUITE_DIR="$ROOT/output_dir/react_simple-mem/obs_Causal_gpt-5-mini/4nodes/causal_or_not"

export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-4nodes.jsonl}"
export BASE_MAX_ENV_CALLS="${BASE_MAX_ENV_CALLS:-$(resolve_base_max_env_calls "$CAUSAL_GRAPH_GROUP")}"
export MAX_ENV_CALLS="${MAX_ENV_CALLS:-$((BASE_MAX_ENV_CALLS + 24))}"
export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export BATCH_SIZE="${BATCH_SIZE:-10}"
export GRAPH_LIMIT="${GRAPH_LIMIT:-0}"
export DRY_RUN="${DRY_RUN:-0}"

export MODEL="${MODEL:-gpt-5-mini}"
export DIFF="${DIFF:-Causal}"
export TASK="${TASK:-Reactor Lab Causal}"
export REACTOR_HINT_LEVEL="${REACTOR_HINT_LEVEL:-no_hint}"
export REACTOR_MAX_SUBMISSIONS="${REACTOR_MAX_SUBMISSIONS:-3}"
export FREQ_ESTIMATOR="${FREQ_ESTIMATOR:-0}"
export CAUSAL_INITIAL_OBSERVATIONS="${CAUSAL_INITIAL_OBSERVATIONS:-2}"
export INTERVENTION_BUDGET="${INTERVENTION_BUDGET:-12}"
export PROPERTY_MANIPULATOR_MAX_USES="${PROPERTY_MANIPULATOR_MAX_USES:-$INTERVENTION_BUDGET}"
export CAUSAL_GRAPH_BUDGET_OVERRIDE="${CAUSAL_GRAPH_BUDGET_OVERRIDE:-$INTERVENTION_BUDGET}"

run_branch() {
  local branch_name="$1"
  local prompt_mode="$2"
  local prompt_name="$3"
  local ts

  ts="$(date +%Y%m%d-%H%M)"

  echo "============================================================================"
  echo "Running branch: ${branch_name}"
  echo "Prompt mode: ${prompt_mode}"
  echo "Output tag: ${ts}_${prompt_name}"
  echo "============================================================================"

  export EXPERIMENT_FAMILY="causal_or_not"
  export REACTOR_TASK_PROMPT_MODE="$prompt_mode"
  export PROMPT_NAME="$prompt_name"
  export OUTPUT_TAG="${ts}_${prompt_name}"
  export BASE_OUTPUT_DIR_OVERRIDE="${BASE_SUITE_DIR}/${branch_name}"

  bash "$RUNNER"
}

run_branch "causal" "dsl" "dsl"
run_branch "non-causal" "linear_non_dsl" "linear_non_dsl"
