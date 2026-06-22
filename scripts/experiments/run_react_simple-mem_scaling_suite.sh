#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

NODE_COUNT="${NODE_COUNT:-4}"
DEFAULT_GRAPH_GROUP="${NODE_COUNT}nodes.jsonl"

export MODEL="${MODEL:-gpt-5-mini}"
export CONFIG_FILE="${CONFIG_FILE:-agents/recoma/configs/react-simple-memory.jsonnet}"
export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-$DEFAULT_GRAPH_GROUP}"
export SCALING_BASE_OUTPUT_DIR="${SCALING_BASE_OUTPUT_DIR:-$ROOT/output_dir/react_simple-mem/obs_Causal_${MODEL}/${NODE_COUNT}nodes/scaling}"
export OBSERVATION_COUNTS="${OBSERVATION_COUNTS:-3 6 12 24}"
export INTERVENTION_COUNTS="${INTERVENTION_COUNTS:-3 6 12 24}"
export FIXED_OBS="${FIXED_OBS:-3}"
export ONLY_SETTINGS="${ONLY_SETTINGS:-}"
export BASE_MAX_ENV_CALLS="${BASE_MAX_ENV_CALLS:-$(resolve_base_max_env_calls "$CAUSAL_GRAPH_GROUP")}"
export BATCH_SIZE="${BATCH_SIZE:-10}"

CONFIG_ROOT="$ROOT/causal_graph_configs"
GROUP_PATH="$CONFIG_ROOT/$CAUSAL_GRAPH_GROUP"
if [[ ! -f "$GROUP_PATH" ]]; then
  echo "ERROR: Graph config file not found: $GROUP_PATH" >&2
  exit 1
fi

read -r -a OBS_COUNTS <<< "$OBSERVATION_COUNTS"
read -r -a INT_COUNTS <<< "$INTERVENTION_COUNTS"
read -r -a ONLY_SETTING_ARRAY <<< "${ONLY_SETTINGS//,/ }"

setting_allowed() {
  local setting_tag="$1"
  if [[ ${#ONLY_SETTING_ARRAY[@]} -eq 0 ]]; then
    return 0
  fi

  local allowed
  for allowed in "${ONLY_SETTING_ARRAY[@]}"; do
    if [[ "$allowed" == "$setting_tag" ]]; then
      return 0
    fi
  done
  return 1
}

run_setting() {
  local label="$1"
  local script_name="$2"
  local output_tag="$3"
  local obs="$4"
  local budget="$5"
  local experiment_family="${6:-}"

  echo "============================================================================"
  echo "Running ${label}"
  echo "Graph group: ${CAUSAL_GRAPH_GROUP}"
  echo "Output tag: ${output_tag}"
  echo "Observations: ${obs}"
  echo "Intervention budget: ${budget}"
  echo "============================================================================"

  if [[ -n "$experiment_family" ]]; then
    env \
      MODEL="${MODEL}" \
      CONFIG_FILE="${CONFIG_FILE}" \
      OUTPUT_TAG="${output_tag}" \
      CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP}" \
      CAUSAL_INITIAL_OBSERVATIONS="${obs}" \
      INTERVENTION_BUDGET="${budget}" \
      BASE_OUTPUT_DIR_OVERRIDE="${SCALING_BASE_OUTPUT_DIR}" \
      BASE_MAX_ENV_CALLS="${BASE_MAX_ENV_CALLS}" \
      EXPERIMENT_FAMILY="${experiment_family}" \
      bash "${SCRIPT_DIR}/${script_name}"
  else
    env \
      MODEL="${MODEL}" \
      CONFIG_FILE="${CONFIG_FILE}" \
      OUTPUT_TAG="${output_tag}" \
      CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP}" \
      CAUSAL_INITIAL_OBSERVATIONS="${obs}" \
      INTERVENTION_BUDGET="${budget}" \
      BASE_OUTPUT_DIR_OVERRIDE="${SCALING_BASE_OUTPUT_DIR}" \
      BASE_MAX_ENV_CALLS="${BASE_MAX_ENV_CALLS}" \
      bash "${SCRIPT_DIR}/${script_name}"
  fi
}

for obs in "${OBS_COUNTS[@]}"; do
  setting_tag="${obs}o0i"
  if ! setting_allowed "$setting_tag"; then
    continue
  fi
  run_setting \
    "scaling_observation_o${obs}_i0" \
    "run_react_simple-mem_scaling_observation.sh" \
    "scaling_observation_o${obs}_i0" \
    "${obs}" \
    "0"
done

for budget in "${INT_COUNTS[@]}"; do
  setting_tag="0o${budget}i"
  if ! setting_allowed "$setting_tag"; then
    continue
  fi
  run_setting \
    "scaling_intervention_o0_i${budget}" \
    "run_react_simple-mem_scaling_intervention.sh" \
    "scaling_intervention_o0_i${budget}" \
    "0" \
    "${budget}"
done

for budget in "${INT_COUNTS[@]}"; do
  setting_tag="${FIXED_OBS}o${budget}i"
  if ! setting_allowed "$setting_tag"; then
    continue
  fi
  run_setting \
    "scaling_obs${FIXED_OBS}_intervention_o${FIXED_OBS}_i${budget}" \
    "run_react_simple-mem_scaling_obs3_intervention.sh" \
    "scaling_obs${FIXED_OBS}_intervention_o${FIXED_OBS}_i${budget}" \
    "${FIXED_OBS}" \
    "${budget}" \
    "scaling_obs${FIXED_OBS}_intervention"
done
