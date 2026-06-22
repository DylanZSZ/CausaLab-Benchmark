#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

resolve_node_settings() {
  case "$1" in
    3)
      CAUSAL_GRAPH_GROUP="3nodes.jsonl"
      ;;
    4)
      CAUSAL_GRAPH_GROUP="4nodes.jsonl"
      ;;
    5)
      CAUSAL_GRAPH_GROUP="5nodes.jsonl"
      ;;
    6)
      CAUSAL_GRAPH_GROUP="6nodes.jsonl"
      ;;
    7)
      CAUSAL_GRAPH_GROUP="7nodes.jsonl"
      ;;
    *)
      echo "ERROR: NODE_COUNT must be one of 3, 4, 5, 6, or 7; got: $1" >&2
      exit 1
      ;;
  esac

  MAX_ENV_CALLS="$(( $(resolve_base_max_env_calls "$CAUSAL_GRAPH_GROUP") + 24 ))"
  export CAUSAL_GRAPH_GROUP
  export MAX_ENV_CALLS
}

NODE_COUNT="${NODE_COUNT:-3}"
resolve_node_settings "$NODE_COUNT"

setup_repo_environment
activate_discoveryworld_env
enter_repo_root

export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export BATCH_SIZE="${BATCH_SIZE:-10}"
export GRAPH_LIMIT="${GRAPH_LIMIT:-0}"
export DRY_RUN="${DRY_RUN:-0}"
export TEST_MAX_ENV_CALLS="${TEST_MAX_ENV_CALLS:-0}"

export SEED="${SEED:-0}"
export DIFF="${DIFF:-Causal}"
export TASK="${TASK:-Reactor Lab Causal}"
export REACTOR_HINT_LEVEL="${REACTOR_HINT_LEVEL:-no_hint}"
export REACTOR_MAX_SUBMISSIONS="${REACTOR_MAX_SUBMISSIONS:-3}"
export FREQ_ESTIMATOR="${FREQ_ESTIMATOR:-0}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl}"
export PROMPT_NAME="${PROMPT_NAME:-dsl}"
export MODEL="${MODEL:-gpt-5.2}"
export CONFIG_FILE="${CONFIG_FILE:-agents/recoma/configs/react-simple-memory_gpt52.jsonnet}"
export OPENAI_API_BASE="${OPENAI_API_BASE:-https://api.openai.com/v1}"

if [[ "$TEST_MAX_ENV_CALLS" =~ ^[1-9][0-9]*$ ]]; then
  export MAX_ENV_CALLS="$TEST_MAX_ENV_CALLS"
fi

print_runtime_header "run_react_simple-mem_parallel_gpt52"
echo "Node count: ${NODE_COUNT}"
echo "Graph group: ${CAUSAL_GRAPH_GROUP}"
echo "MAX_ENV_CALLS: ${MAX_ENV_CALLS}"
echo "DRY_RUN: ${DRY_RUN}"

ensure_openai_api_key_if_needed

echo "Using conda environment: ${CONDA_DEFAULT_ENV:-unknown}"
echo "Python path: $(which python)"

if [[ "${FREQ_ESTIMATOR}" == "1" ]]; then
  FREQ_TAG="inter"
else
  FREQ_TAG="obs"
fi

TS="$(date +%Y%m%d-%H%M)"
SAFE_MODEL="$(echo "$MODEL" | sed 's#[^A-Za-z0-9_.-]#_#g')"
BASE_OUTPUT_DIR="output_dir/react_simple-mem/${FREQ_TAG}_${DIFF}_${SAFE_MODEL}"
mkdir -p "$BASE_OUTPUT_DIR"

CONFIG_ROOT="$(pwd)/causal_graph_configs"
GROUP_PATH="$CONFIG_ROOT/$CAUSAL_GRAPH_GROUP"
if [[ ! -f "$GROUP_PATH" ]]; then
  echo "ERROR: Graph config file not found: $GROUP_PATH" >&2
  exit 1
fi

TEMP_DIR="$(mktemp -d -t causal_graphs_XXXXXX)"
cleanup_temp_files() {
  if [[ -n "${TEMP_DIR:-}" && -d "$TEMP_DIR" ]]; then
    rm -rf "$TEMP_DIR"
  fi
}
trap cleanup_temp_files EXIT

declare -a GRAPH_IDS=()
declare -a GRAPH_FILES=()

line_num=0
while IFS= read -r line || [[ -n "$line" ]]; do
  line_num=$((line_num + 1))
  [[ -z "$line" ]] && continue

  graph_id="$(echo "$line" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('graph_id', 'graph_${line_num}'))" 2>/dev/null)"
  graph_id_safe="$(echo "$graph_id" | sed 's#[^A-Za-z0-9_.-]#_#g')"
  temp_json="$TEMP_DIR/${graph_id_safe}.json"
  echo "$line" > "$temp_json"

  GRAPH_IDS+=("${graph_id}")
  GRAPH_FILES+=("$temp_json")
done < "$GROUP_PATH"

if [[ ${#GRAPH_FILES[@]} -eq 0 ]]; then
  echo "ERROR: No valid graphs found in: $GROUP_PATH" >&2
  exit 1
fi

if [[ "$GRAPH_LIMIT" =~ ^[0-9]+$ ]] && [[ "$GRAPH_LIMIT" -gt 0 ]] && [[ "$GRAPH_LIMIT" -lt ${#GRAPH_FILES[@]} ]]; then
  GRAPH_IDS=("${GRAPH_IDS[@]:0:$GRAPH_LIMIT}")
  GRAPH_FILES=("${GRAPH_FILES[@]:0:$GRAPH_LIMIT}")
fi

SEEDS=()
for ((i = 1; i <= SEEDS_PER_GRAPH; i++)); do
  SEEDS+=("$i")
done

echo "Loaded ${#GRAPH_FILES[@]} graphs from JSONL file"
echo "Seeds per graph: ${#SEEDS[@]} (${SEEDS[*]})"
echo "Batch size: ${BATCH_SIZE} graphs at a time"

SCRIPT_PID=$$
TIMESTAMP_SEC="$(date +%s)"
UNIQUE_OFFSET=$(( (TIMESTAMP_SEC % 10000) + (SCRIPT_PID % 10000) ))
BASE_OFFSET=$((MAX_ENV_CALLS / 100))
BASE_THREADID_OFFSET=$((BASE_OFFSET + UNIQUE_OFFSET))

declare -a FAILED_GRAPHS=()
TOTAL_GRAPHS=${#GRAPH_IDS[@]}

for ((batch_start = 0; batch_start < TOTAL_GRAPHS; batch_start += BATCH_SIZE)); do
  batch_end=$((batch_start + BATCH_SIZE))
  if [[ $batch_end -gt $TOTAL_GRAPHS ]]; then
    batch_end=$TOTAL_GRAPHS
  fi

  batch_num=$(( batch_start / BATCH_SIZE + 1 ))
  total_batches=$(( (TOTAL_GRAPHS + BATCH_SIZE - 1) / BATCH_SIZE ))

  echo "------------------------------------------------------------------------"
  echo "Batch $batch_num/$total_batches: Processing graphs $batch_start to $((batch_end - 1))"
  echo "------------------------------------------------------------------------"

  declare -a BATCH_PIDS=()
  declare -A PID_TO_GRAPH=()

  for ((idx = batch_start; idx < batch_end; idx++)); do
    CURRENT_GRAPH_ID="${GRAPH_IDS[$idx]}"
    CURRENT_GRAPH_FILE="${GRAPH_FILES[$idx]}"
    GRAPH_SAFE="$(echo "$CURRENT_GRAPH_ID" | sed 's#[^A-Za-z0-9_.-/]#_#g')"

    JSONL_BASENAME="$(basename "$GROUP_PATH" .jsonl)"
    GRAPH_ROOT="$BASE_OUTPUT_DIR/${JSONL_BASENAME}/${TS}_${PROMPT_NAME}/${GRAPH_SAFE}_${MAX_ENV_CALLS}calls"
    mkdir -p "$GRAPH_ROOT"

    echo "  Graph ${CURRENT_GRAPH_ID}: $GRAPH_ROOT"

    for ENV_SEED in "${SEEDS[@]}"; do
      SUBDIR="$GRAPH_ROOT/seed_$ENV_SEED"
      mkdir -p "$SUBDIR"
      cp "$CURRENT_GRAPH_FILE" "$SUBDIR/graph_config.json"

      UNIQUE_THREADID_OFFSET=$((BASE_THREADID_OFFSET + idx * 100 + ENV_SEED))

      if [[ "$DRY_RUN" == "1" ]]; then
        echo "[DRY_RUN] node=${NODE_COUNT} graph=${CURRENT_GRAPH_ID} seed=${ENV_SEED} output=${SUBDIR} threadid=${UNIQUE_THREADID_OFFSET}"
        continue
      fi

      SEED_CACHE_DIR="$XDG_CACHE_HOME/gpt3calls_job_${LOCAL_JOB_ID}_graph_${GRAPH_SAFE}_seed_${ENV_SEED}"
      mkdir -p "$SEED_CACHE_DIR"
      SEED_TEMP_HOME="$WORK_ROOT/temp_home_${LOCAL_JOB_ID}_graph_${GRAPH_SAFE}_seed_${ENV_SEED}"
      mkdir -p "$SEED_TEMP_HOME/.cache"
      ln -sfn "$SEED_CACHE_DIR" "$SEED_TEMP_HOME/.cache/gpt3calls"

      (
        HOME="$SEED_TEMP_HOME" \
        OUTPUT_DIR="$SUBDIR" \
        ENV_SEED="$ENV_SEED" \
        REACTOR_LAB_HINT_LEVEL="$REACTOR_HINT_LEVEL" \
        THREADID_OFFSET="$UNIQUE_THREADID_OFFSET" \
        CAUSAL_GRAPH_ID="$CURRENT_GRAPH_ID" \
        CAUSAL_GRAPH_CONFIG="$CURRENT_GRAPH_FILE" \
        python agents/recoma/run_recoma.py \
          --output_dir "$SUBDIR" \
          --config "$CONFIG_FILE" \
          --debug \
          > "$SUBDIR/recoma_execution.log" 2>&1
      ) &

      PID=$!
      BATCH_PIDS+=("$PID")
      PID_TO_GRAPH["$PID"]="$CURRENT_GRAPH_ID"
    done
  done

  if [[ "$DRY_RUN" != "1" ]]; then
    batch_failed=0
    for pid in "${BATCH_PIDS[@]}"; do
      if ! wait "$pid"; then
        batch_failed=1
        graph_id="${PID_TO_GRAPH[$pid]}"
        if [[ ! " ${FAILED_GRAPHS[*]} " =~ " ${graph_id} " ]]; then
          FAILED_GRAPHS+=("$graph_id")
        fi
      fi
    done
    if [[ "$batch_failed" -ne 0 ]]; then
      echo "Batch completed with failures." >&2
    fi
  fi

  unset BATCH_PIDS
  unset PID_TO_GRAPH
done

echo "============================================================================"
echo "Execution Summary"
echo "Output directory: $BASE_OUTPUT_DIR"
echo "Graphs processed: $TOTAL_GRAPHS"
echo "Seeds per graph: ${#SEEDS[@]}"
echo "Dry run: $DRY_RUN"
if [[ "$DRY_RUN" == "1" ]]; then
  exit 0
fi
if [[ ${#FAILED_GRAPHS[@]} -eq 0 ]]; then
  exit 0
fi
echo "Failed graphs: ${FAILED_GRAPHS[*]}" >&2
exit 1
