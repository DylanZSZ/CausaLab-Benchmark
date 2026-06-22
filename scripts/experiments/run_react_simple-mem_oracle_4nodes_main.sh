#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export EXPERIMENT_FAMILY="${EXPERIMENT_FAMILY:-oracle_main}"
export OUTPUT_TAG="${OUTPUT_TAG:-oracle_4nodes_main}"
export OUTPUT_ROOT_PREFIX="${OUTPUT_ROOT_PREFIX:-obs_CausalOracle}"
export SETTING_DIR_NAME="${SETTING_DIR_NAME:-4nodes_main}"
export MODEL="${MODEL:-gpt-5-mini}"
export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-4nodes.jsonl}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl}"
export PROMPT_NAME="${PROMPT_NAME:-dsl_oracle}"
export PROPERTY_MANIPULATOR_ORACLE_CHAINS="${PROPERTY_MANIPULATOR_ORACLE_CHAINS:-1}"

bash "$SCRIPT_DIR/run_react_simple-mem_main_variant.sh"
