#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# 6-node scaling design:
# - observation counts: 5 / 10 / 20 / 40
# - intervention counts: 5 / 10 / 20 / 40
# - fixed-observation sweep uses 5 initial observations because a 6-node graph
#   has 5 controllable variables under the current reactor-lab setup.
export NODE_COUNT="${NODE_COUNT:-6}"
export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-6nodes.jsonl}"
export OBSERVATION_COUNTS="${OBSERVATION_COUNTS:-5 10 20}"
export INTERVENTION_COUNTS="${INTERVENTION_COUNTS:-5 10 20}"
export FIXED_OBS="${FIXED_OBS:-5}"
export BASE_MAX_ENV_CALLS="${BASE_MAX_ENV_CALLS:-31}"
export SCALING_BASE_OUTPUT_DIR="${SCALING_BASE_OUTPUT_DIR:-$ROOT/output_dir/react_simple-mem/obs_Causal_gpt-5-mini/6nodes/scaling}"

bash "$SCRIPT_DIR/run_react_simple-mem_scaling_suite.sh"
