#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

setup_repo_environment
activate_discoveryworld_env
enter_repo_root

export MODE="${MODE:-validation}"
export NODES="${NODES:-all}"
export ONLY_SETTINGS="${ONLY_SETTINGS:-}"
export SETTING_JOBS="${SETTING_JOBS:-2}"
export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export DRY_RUN="${DRY_RUN:-0}"
export MODEL="${MODEL:-gpt-5.2}"
export CONFIG_FILE="${CONFIG_FILE:-agents/recoma/configs/react-simple-memory_gpt52.jsonnet}"
export OPENAI_API_BASE="${OPENAI_API_BASE:-https://api.openai.com/v1}"

print_runtime_header "run_react_simple-mem_scaling_gpt52"
echo "Mode: ${MODE}"
echo "Nodes: ${NODES}"
echo "Only settings: ${ONLY_SETTINGS:-<all>}"
echo "Setting jobs: ${SETTING_JOBS}"
echo "Dry run: ${DRY_RUN}"
echo "Model: ${MODEL}"
echo "Config: ${CONFIG_FILE}"

ensure_openai_api_key_if_needed

if [[ "$MODE" != "validation" && "$MODE" != "full" ]]; then
  echo "ERROR: MODE must be one of: validation, full" >&2
  exit 1
fi

if [[ "$NODES" != "4" && "$NODES" != "6" && "$NODES" != "all" ]]; then
  echo "ERROR: NODES must be one of: 4, 6, all" >&2
  exit 1
fi

if ! [[ "$SETTING_JOBS" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: SETTING_JOBS must be a positive integer; got: $SETTING_JOBS" >&2
  exit 1
fi

node_settings() {
  case "$1" in
    4)
      echo "3o0i 6o0i 12o0i 0o3i 0o6i 0o12i 3o3i 3o6i 3o12i"
      ;;
    6)
      echo "5o0i 10o0i 20o0i 0o5i 0o10i 0o20i 5o5i 5o10i 5o20i"
      ;;
    *)
      return 1
      ;;
  esac
}

node_graph_group() {
  echo "${1}nodes.jsonl"
}

node_fixed_obs() {
  case "$1" in
    4) echo "3" ;;
    6) echo "5" ;;
    *) return 1 ;;
  esac
}

node_obs_counts() {
  case "$1" in
    4) echo "3 6 12" ;;
    6) echo "5 10 20" ;;
    *) return 1 ;;
  esac
}

node_int_counts() {
  case "$1" in
    4) echo "3 6 12" ;;
    6) echo "5 10 20" ;;
    *) return 1 ;;
  esac
}

node_base_max_env_calls() {
  case "$1" in
    4) echo "29" ;;
    6) echo "31" ;;
    *) return 1 ;;
  esac
}

node_output_root() {
  local node="$1"
  local suffix="scaling"
  if [[ "$MODE" == "validation" ]]; then
    suffix="scaling_validation"
  fi
  echo "$ROOT/output_dir/react_simple-mem/obs_Causal_${MODEL}/${node}nodes/${suffix}"
}

default_graph_limit() {
  if [[ "$MODE" == "validation" ]]; then
    echo "5"
  else
    echo "0"
  fi
}

default_batch_size() {
  if [[ "$MODE" == "validation" ]]; then
    echo "5"
  else
    echo "10"
  fi
}

split_csv_to_array() {
  local raw="$1"
  local -n out_ref="$2"
  local token
  out_ref=()
  raw="${raw//,/ }"
  read -r -a out_ref <<< "$raw"
  if [[ ${#out_ref[@]} -eq 1 && -z "${out_ref[0]}" ]]; then
    out_ref=()
  fi
  for token in "${out_ref[@]}"; do
    if [[ -z "$token" ]]; then
      echo "ERROR: ONLY_SETTINGS contains an empty setting tag." >&2
      exit 1
    fi
  done
}

filter_settings_for_node() {
  local node="$1"
  local -n out_ref="$2"
  local all_node_settings raw_setting
  local requested_settings=()
  split_csv_to_array "$ONLY_SETTINGS" requested_settings
  read -r -a all_node_settings <<< "$(node_settings "$node")"
  out_ref=()

  if [[ ${#requested_settings[@]} -eq 0 ]]; then
    out_ref=("${all_node_settings[@]}")
    return 0
  fi

  for raw_setting in "${all_node_settings[@]}"; do
    local requested
    for requested in "${requested_settings[@]}"; do
      if [[ "$requested" == "$raw_setting" ]]; then
        out_ref+=("$raw_setting")
      fi
    done
  done
}

wait_for_pid_queue() {
  local max_jobs="$1"
  local -n pid_ref="$2"
  local -n label_ref="$3"
  local first_pid first_label

  while [[ ${#pid_ref[@]} -ge $max_jobs ]]; do
    first_pid="${pid_ref[0]}"
    first_label="${label_ref[0]}"
    pid_ref=("${pid_ref[@]:1}")
    label_ref=("${label_ref[@]:1}")
    if ! wait "$first_pid"; then
      echo "ERROR: setting job failed: ${first_label}" >&2
      return 1
    fi
  done
  return 0
}

wait_for_remaining_jobs() {
  local -n pid_ref="$1"
  local -n label_ref="$2"
  local idx
  for ((idx = 0; idx < ${#pid_ref[@]}; idx++)); do
    if ! wait "${pid_ref[$idx]}"; then
      echo "ERROR: setting job failed: ${label_ref[$idx]}" >&2
      return 1
    fi
  done
  pid_ref=()
  label_ref=()
  return 0
}

launch_setting() {
  local node="$1"
  local setting_tag="$2"
  local effective_graph_limit="$3"
  local effective_batch_size="$4"
  local graph_group fixed_obs obs_counts int_counts base_max_env_calls output_root

  graph_group="$(node_graph_group "$node")"
  fixed_obs="$(node_fixed_obs "$node")"
  obs_counts="$(node_obs_counts "$node")"
  int_counts="$(node_int_counts "$node")"
  base_max_env_calls="$(node_base_max_env_calls "$node")"
  output_root="$(node_output_root "$node")"

  echo "----------------------------------------------------------------------------"
  echo "Launching node=${node} setting=${setting_tag}"
  echo "Graph group: ${graph_group}"
  echo "Output root: ${output_root}"
  echo "GRAPH_LIMIT: ${effective_graph_limit}"
  echo "BATCH_SIZE: ${effective_batch_size}"
  echo "----------------------------------------------------------------------------"

  env \
    MODE="${MODE}" \
    MODEL="${MODEL}" \
    CONFIG_FILE="${CONFIG_FILE}" \
    NODE_COUNT="${node}" \
    CAUSAL_GRAPH_GROUP="${graph_group}" \
    OBSERVATION_COUNTS="${obs_counts}" \
    INTERVENTION_COUNTS="${int_counts}" \
    FIXED_OBS="${fixed_obs}" \
    BASE_MAX_ENV_CALLS="${base_max_env_calls}" \
    SCALING_BASE_OUTPUT_DIR="${output_root}" \
    ONLY_SETTINGS="${setting_tag}" \
    GRAPH_LIMIT="${effective_graph_limit}" \
    BATCH_SIZE="${effective_batch_size}" \
    SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH}" \
    DRY_RUN="${DRY_RUN}" \
    bash "$SCRIPT_DIR/run_react_simple-mem_scaling_suite.sh"
}

declare -a REQUESTED_NODES=()
if [[ "$NODES" == "all" ]]; then
  REQUESTED_NODES=(4 6)
else
  REQUESTED_NODES=("$NODES")
fi

effective_graph_limit="${GRAPH_LIMIT:-$(default_graph_limit)}"
effective_batch_size="${BATCH_SIZE:-$(default_batch_size)}"

declare -a VALIDATION_ROOTS=()
declare -a RUN_PIDS=()
declare -a RUN_LABELS=()

for node in "${REQUESTED_NODES[@]}"; do
  declare -a NODE_SELECTED_SETTINGS=()
  filter_settings_for_node "$node" NODE_SELECTED_SETTINGS
  if [[ ${#NODE_SELECTED_SETTINGS[@]} -eq 0 ]]; then
    echo "Skipping node ${node}: no settings matched ONLY_SETTINGS=${ONLY_SETTINGS:-<all>}"
    continue
  fi

  output_root="$(node_output_root "$node")"
  if [[ "$MODE" == "validation" ]]; then
    VALIDATION_ROOTS+=("$output_root")
  fi

  if [[ "$MODE" == "validation" ]]; then
    for setting_tag in "${NODE_SELECTED_SETTINGS[@]}"; do
      wait_for_pid_queue "$SETTING_JOBS" RUN_PIDS RUN_LABELS
      launch_setting "$node" "$setting_tag" "$effective_graph_limit" "$effective_batch_size" &
      RUN_PIDS+=("$!")
      RUN_LABELS+=("${node}:${setting_tag}")
    done
  else
    for setting_tag in "${NODE_SELECTED_SETTINGS[@]}"; do
      launch_setting "$node" "$setting_tag" "$effective_graph_limit" "$effective_batch_size"
    done
  fi
done

if [[ "$MODE" == "validation" ]]; then
  wait_for_remaining_jobs RUN_PIDS RUN_LABELS

  if [[ "$DRY_RUN" != "1" && ${#VALIDATION_ROOTS[@]} -gt 0 ]]; then
    python "$ROOT/scripts/verify_scaling_runs.py" \
      "${VALIDATION_ROOTS[@]}" \
      --output-dir "$ROOT/output_dir/analysis/gpt52_scaling_validation"
  fi
fi

echo "============================================================================"
echo "Scaling orchestration completed successfully."
echo "Mode: ${MODE}"
echo "Nodes: ${NODES}"
echo "GRAPH_LIMIT: ${effective_graph_limit}"
echo "BATCH_SIZE: ${effective_batch_size}"
if [[ "$MODE" == "validation" ]]; then
  echo "Validation report: $ROOT/output_dir/analysis/gpt52_scaling_validation"
fi
echo "Stable full command:"
echo "MODE=full NODES=all bash scripts/experiments/run_react_simple-mem_scaling_gpt52.sh"
