#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

export EXPERIMENT_FAMILY="${EXPERIMENT_FAMILY:-scaling_intervention}"
export OUTPUT_TAG="${OUTPUT_TAG:-scaling_intervention_o0_i3}"
export MODEL="${MODEL:-gpt-5-mini}"
export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-4nodes.jsonl}"
export BASE_OUTPUT_DIR_OVERRIDE="${BASE_OUTPUT_DIR_OVERRIDE:-$ROOT/output_dir/react_simple-mem/obs_Causal_gpt-5-mini/4nodes/scaling}"
export CAUSAL_INITIAL_OBSERVATIONS="${CAUSAL_INITIAL_OBSERVATIONS:-0}"
export INTERVENTION_BUDGET="${INTERVENTION_BUDGET:-3}"
export BATCH_SIZE="${BATCH_SIZE:-10}"
export CAUSAL_TOOL_ENABLED="${CAUSAL_TOOL_ENABLED:-0}"

bash "$SCRIPT_DIR/run_react_simple-mem_experiment.sh"
