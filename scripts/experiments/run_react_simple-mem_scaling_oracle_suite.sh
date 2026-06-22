#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

setup_repo_environment
activate_discoveryworld_env
enter_repo_root

export MODEL="${MODEL:-gpt-5-mini}"
export NODE_COUNT="${NODE_COUNT:-4}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl}"
export PROMPT_NAME="${PROMPT_NAME:-dsl_oracle}"
export PROPERTY_MANIPULATOR_ORACLE_CHAINS="${PROPERTY_MANIPULATOR_ORACLE_CHAINS:-1}"
export SCALING_BASE_OUTPUT_DIR="${SCALING_BASE_OUTPUT_DIR:-$ROOT/output_dir/react_simple-mem/obs_CausalOracle_${MODEL}/${NODE_COUNT}nodes/scaling}"
export ONLY_SETTINGS="${ONLY_SETTINGS:-}"

print_runtime_header "run_react_simple-mem_scaling_oracle_suite"
echo "Model: ${MODEL}"
echo "Node count: ${NODE_COUNT}"
echo "Prompt mode: ${REACTOR_TASK_PROMPT_MODE}"
echo "Prompt name: ${PROMPT_NAME}"
echo "Oracle chains enabled: ${PROPERTY_MANIPULATOR_ORACLE_CHAINS}"
echo "Scaling output root: ${SCALING_BASE_OUTPUT_DIR}"
echo "Only settings: ${ONLY_SETTINGS:-all}"

ensure_openai_api_key_if_needed

env \
  MODEL="${MODEL}" \
  NODE_COUNT="${NODE_COUNT}" \
  REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE}" \
  PROMPT_NAME="${PROMPT_NAME}" \
  PROPERTY_MANIPULATOR_ORACLE_CHAINS="${PROPERTY_MANIPULATOR_ORACLE_CHAINS}" \
  SCALING_BASE_OUTPUT_DIR="${SCALING_BASE_OUTPUT_DIR}" \
  ONLY_SETTINGS="${ONLY_SETTINGS}" \
  bash "$SCRIPT_DIR/run_react_simple-mem_scaling_suite.sh"
