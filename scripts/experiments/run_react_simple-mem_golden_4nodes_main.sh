#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export EXPERIMENT_FAMILY="${EXPERIMENT_FAMILY:-golden_main}"
export OUTPUT_TAG="${OUTPUT_TAG:-golden_4nodes_main}"
export OUTPUT_ROOT_PREFIX="${OUTPUT_ROOT_PREFIX:-obs_CausalGolden}"
export SETTING_DIR_NAME="${SETTING_DIR_NAME:-4nodes_main}"
export MODEL="${MODEL:-gpt-5-mini}"
export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-4nodes_golden.jsonl}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl}"
export PROMPT_NAME="${PROMPT_NAME:-dsl}"
export INTERVENTION_BUDGET="${INTERVENTION_BUDGET:-0}"

bash "$SCRIPT_DIR/run_react_simple-mem_main_variant.sh"
