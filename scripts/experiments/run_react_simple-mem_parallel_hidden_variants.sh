#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

setup_repo_environment
activate_discoveryworld_env
enter_repo_root

export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-4nodes_hidden.jsonl}"
export BASE_MAX_ENV_CALLS="${BASE_MAX_ENV_CALLS:-$(resolve_base_max_env_calls "$CAUSAL_GRAPH_GROUP")}"
export MAX_ENV_CALLS="${MAX_ENV_CALLS:-$((BASE_MAX_ENV_CALLS + 24))}"
export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export BATCH_SIZE="${BATCH_SIZE:-10}"
export SEED="${SEED:-0}"
export DIFF="${DIFF:-Causal}"
export OUTPUT_TAG="${OUTPUT_TAG:-CausalHidden}"
export TASK="${TASK:-Reactor Lab Causal}"
export REACTOR_HINT_LEVEL="${REACTOR_HINT_LEVEL:-no_hint}"
export REACTOR_MAX_SUBMISSIONS="${REACTOR_MAX_SUBMISSIONS:-3}"
export FREQ_ESTIMATOR="${FREQ_ESTIMATOR:-0}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl_hidden}"
export PROMPT_NAME="${PROMPT_NAME:-dsl_hidden}"
export MODEL="${MODEL:-gpt-5-mini}"
export BASE_OUTPUT_DIR_OVERRIDE="${BASE_OUTPUT_DIR_OVERRIDE:-}"
export GRAPH_LIMIT="${GRAPH_LIMIT:-0}"
export DRY_RUN="${DRY_RUN:-0}"
export TEST_MAX_ENV_CALLS="${TEST_MAX_ENV_CALLS:-0}"
export OPENAI_API_BASE="${OPENAI_API_BASE:-https://api.openai.com/v1}"

if [[ "$TEST_MAX_ENV_CALLS" =~ ^[1-9][0-9]*$ ]]; then
  export MAX_ENV_CALLS="$TEST_MAX_ENV_CALLS"
fi

print_runtime_header "run_react_simple-mem_parallel_hidden_variants"
echo "Output tag: ${OUTPUT_TAG}"
echo "Graph group: ${CAUSAL_GRAPH_GROUP}"
echo "MAX_ENV_CALLS: ${MAX_ENV_CALLS}"
echo "Prompt name: ${PROMPT_NAME}"

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
if [[ -n "$BASE_OUTPUT_DIR_OVERRIDE" ]]; then
  BASE_OUTPUT_DIR="$BASE_OUTPUT_DIR_OVERRIDE"
else
  BASE_OUTPUT_DIR="output_dir/react_simple-mem/${FREQ_TAG}_${OUTPUT_TAG}_${SAFE_MODEL}"
fi
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

SCRIPT_PID=$$
TIMESTAMP_SEC="$(date +%s)"
UNIQUE_OFFSET=$(( (TIMESTAMP_SEC % 10000) + (SCRIPT_PID % 10000) ))
BASE_OFFSET=$((MAX_ENV_CALLS / 100))
BASE_THREADID_OFFSET=$((BASE_OFFSET + UNIQUE_OFFSET))

declare -a FAILED_GRAPHS=()
TOTAL_GRAPHS=${#GRAPH_IDS[@]}

echo "Base output directory: $BASE_OUTPUT_DIR"
echo "Loaded graphs: $TOTAL_GRAPHS"
echo "Seeds per graph: ${#SEEDS[@]} (${SEEDS[*]})"
echo "Batch size: $BATCH_SIZE"
echo "Dry run: $DRY_RUN"

for ((batch_start = 0; batch_start < TOTAL_GRAPHS; batch_start += BATCH_SIZE)); do
  batch_end=$((batch_start + BATCH_SIZE))
  if [[ $batch_end -gt $TOTAL_GRAPHS ]]; then
    batch_end=$TOTAL_GRAPHS
  fi

  declare -a BATCH_PIDS=()
  declare -A PID_TO_GRAPH=()
  declare -A PID_TO_SEED=()

  for ((idx = batch_start; idx < batch_end; idx++)); do
    CURRENT_GRAPH_ID="${GRAPH_IDS[$idx]}"
    CURRENT_GRAPH_FILE="${GRAPH_FILES[$idx]}"
    GRAPH_SAFE="$(echo "$CURRENT_GRAPH_ID" | sed 's#[^A-Za-z0-9_.-/]#_#g')"

    JSONL_BASENAME="$(basename "$GROUP_PATH" .jsonl)"
    GRAPH_ROOT="$BASE_OUTPUT_DIR/${JSONL_BASENAME}/${TS}_${PROMPT_NAME}/${GRAPH_SAFE}_${MAX_ENV_CALLS}calls"
    mkdir -p "$GRAPH_ROOT"

    for ENV_SEED in "${SEEDS[@]}"; do
      SUBDIR="$GRAPH_ROOT/seed_$ENV_SEED"
      mkdir -p "$SUBDIR"
      cp "$CURRENT_GRAPH_FILE" "$SUBDIR/graph_config.json"

      if [[ "$DRY_RUN" == "1" ]]; then
        echo "[DRY_RUN] graph=$CURRENT_GRAPH_ID seed=$ENV_SEED subdir=$SUBDIR"
        continue
      fi

      SEED_CACHE_DIR="$XDG_CACHE_HOME/gpt3calls_job_${LOCAL_JOB_ID}_graph_${GRAPH_SAFE}_seed_${ENV_SEED}"
      mkdir -p "$SEED_CACHE_DIR"
      SEED_TEMP_HOME="$WORK_ROOT/temp_home_${LOCAL_JOB_ID}_graph_${GRAPH_SAFE}_seed_${ENV_SEED}"
      mkdir -p "$SEED_TEMP_HOME/.cache"
      ln -sfn "$SEED_CACHE_DIR" "$SEED_TEMP_HOME/.cache/gpt3calls"

      UNIQUE_THREADID_OFFSET=$((BASE_THREADID_OFFSET + idx * 100 + ENV_SEED))
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
          --config agents/recoma/configs/react-simple-memory.jsonnet \
          --debug \
          > "$SUBDIR/recoma_execution.log" 2>&1
      ) &

      PID=$!
      BATCH_PIDS+=("$PID")
      PID_TO_GRAPH["$PID"]="$CURRENT_GRAPH_ID"
      PID_TO_SEED["$PID"]="$ENV_SEED"
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
  unset PID_TO_SEED
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
