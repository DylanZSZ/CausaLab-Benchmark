#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TS="$(date +%Y%m%d-%H%M)"

export EXPERIMENT_FAMILY="${EXPERIMENT_FAMILY:-quad_eval_hard}"
export OUTPUT_TAG="${OUTPUT_TAG:-${TS}_dsl_quad_hard}"
export MODEL="${MODEL:-gpt-5-mini}"
export NODE_COUNT="${NODE_COUNT:-4}"
export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-4nodes_quad_hard.jsonl}"
export CAUSAL_INITIAL_OBSERVATIONS="${CAUSAL_INITIAL_OBSERVATIONS:-2}"
export INTERVENTION_BUDGET="${INTERVENTION_BUDGET:-12}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl_quad}"
export PROMPT_NAME="${PROMPT_NAME:-$REACTOR_TASK_PROMPT_MODE}"
export BASE_OUTPUT_DIR_OVERRIDE="${BASE_OUTPUT_DIR_OVERRIDE:-$ROOT/output_dir/react_simple-mem/obs_CausalQuadHard_gpt-5-mini/4nodes_quad_hard}"
bash "$SCRIPT_DIR/run_react_simple-mem_experiment.sh"
