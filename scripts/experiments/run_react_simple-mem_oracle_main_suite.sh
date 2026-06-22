#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

setup_repo_environment
activate_discoveryworld_env
enter_repo_root

export MODEL="${MODEL:-gpt-5-mini}"
export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export BATCH_SIZE="${BATCH_SIZE:-10}"
export GRAPH_LIMIT="${GRAPH_LIMIT:-0}"
export DRY_RUN="${DRY_RUN:-0}"
export PROPERTY_MANIPULATOR_ORACLE_CHAINS="${PROPERTY_MANIPULATOR_ORACLE_CHAINS:-1}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl}"
export PROMPT_NAME="${PROMPT_NAME:-dsl_oracle}"
export ONLY_NODE_COUNTS="${ONLY_NODE_COUNTS:-4 6}"

print_runtime_header "run_react_simple-mem_oracle_main_suite"
echo "Model: ${MODEL}"
echo "Prompt mode: ${REACTOR_TASK_PROMPT_MODE}"
echo "Prompt name: ${PROMPT_NAME}"
echo "Oracle chains enabled: ${PROPERTY_MANIPULATOR_ORACLE_CHAINS}"
echo "Node counts: ${ONLY_NODE_COUNTS}"

ensure_openai_api_key_if_needed

run_node_suite() {
  local node_count="$1"
  local script_path=""

  case "$node_count" in
    4) script_path="$SCRIPT_DIR/run_react_simple-mem_oracle_4nodes_main.sh" ;;
    6) script_path="$SCRIPT_DIR/run_react_simple-mem_oracle_6nodes_main.sh" ;;
    *)
      echo "ERROR: unsupported oracle node count: ${node_count}" >&2
      exit 1
      ;;
  esac

  echo "============================================================================"
  echo "Running oracle main suite for ${node_count} nodes"
  echo "============================================================================"

  env \
    MODEL="${MODEL}" \
    SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH}" \
    BATCH_SIZE="${BATCH_SIZE}" \
    GRAPH_LIMIT="${GRAPH_LIMIT}" \
    DRY_RUN="${DRY_RUN}" \
    REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE}" \
    PROMPT_NAME="${PROMPT_NAME}" \
    PROPERTY_MANIPULATOR_ORACLE_CHAINS="${PROPERTY_MANIPULATOR_ORACLE_CHAINS}" \
    bash "$script_path"
}

read -r -a NODE_COUNTS <<< "${ONLY_NODE_COUNTS//,/ }"
for node_count in "${NODE_COUNTS[@]}"; do
  run_node_suite "$node_count"
done
