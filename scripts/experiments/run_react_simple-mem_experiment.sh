#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

setup_repo_environment
activate_discoveryworld_env
enter_repo_root

export CAUSAL_GRAPH_GROUP="${CAUSAL_GRAPH_GROUP:-5nodes.jsonl}"
export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export BATCH_SIZE="${BATCH_SIZE:-20}"
export GRAPH_LIMIT="${GRAPH_LIMIT:-0}"

export SEED="${SEED:-0}"
export DIFF="${DIFF:-Causal}"
export TASK="${TASK:-Reactor Lab Causal}"
export REACTOR_HINT_LEVEL="${REACTOR_HINT_LEVEL:-no_hint}"
export REACTOR_MAX_SUBMISSIONS="${REACTOR_MAX_SUBMISSIONS:-3}"
export FREQ_ESTIMATOR="${FREQ_ESTIMATOR:-0}"
export REACTOR_TASK_PROMPT_MODE="${REACTOR_TASK_PROMPT_MODE:-dsl}"
export PROMPT_NAME="${PROMPT_NAME:-$REACTOR_TASK_PROMPT_MODE}"
export PROPERTY_MANIPULATOR_ORACLE_CHAINS="${PROPERTY_MANIPULATOR_ORACLE_CHAINS:-0}"

export MODEL="${MODEL:-gpt-5-mini}"
export OPENAI_API_BASE="${OPENAI_API_BASE:-https://api.openai.com/v1}"

export OUTPUT_TAG="${OUTPUT_TAG:-react_simple_mem_default}"
export EXPERIMENT_FAMILY="${EXPERIMENT_FAMILY:-custom}"
export CAUSAL_INITIAL_OBSERVATIONS="${CAUSAL_INITIAL_OBSERVATIONS:-2}"
export INTERVENTION_BUDGET="${INTERVENTION_BUDGET:-12}"
export PROPERTY_MANIPULATOR_MAX_USES="${PROPERTY_MANIPULATOR_MAX_USES:-$INTERVENTION_BUDGET}"
export CAUSAL_GRAPH_BUDGET_OVERRIDE="${CAUSAL_GRAPH_BUDGET_OVERRIDE:-$INTERVENTION_BUDGET}"
export CAUSAL_TOOL_ENABLED="${CAUSAL_TOOL_ENABLED:-0}"
export CAUSAL_TOOL_MAX_GRAPHS="${CAUSAL_TOOL_MAX_GRAPHS:-20}"
export BASE_OUTPUT_DIR_OVERRIDE="${BASE_OUTPUT_DIR_OVERRIDE:-}"
export EXPERIMENT_SUBDIR_OVERRIDE="${EXPERIMENT_SUBDIR_OVERRIDE:-}"
export CONFIG_FILE="${CONFIG_FILE:-agents/recoma/configs/react-simple-memory.jsonnet}"
export DRY_RUN="${DRY_RUN:-0}"
export TEST_MAX_ENV_CALLS="${TEST_MAX_ENV_CALLS:-0}"

CONFIG_ROOT="$(pwd)/causal_graph_configs"
if [[ "$CAUSAL_GRAPH_GROUP" = /* ]]; then
  GROUP_PATH="$CAUSAL_GRAPH_GROUP"
else
  GROUP_PATH="$CONFIG_ROOT/$CAUSAL_GRAPH_GROUP"
fi
if [[ ! -f "$GROUP_PATH" ]]; then
  echo "ERROR: Graph config file not found: $GROUP_PATH" >&2
  exit 1
fi

if [[ -z "${BASE_MAX_ENV_CALLS+x}" ]]; then
  export BASE_MAX_ENV_CALLS="$(resolve_base_max_env_calls "$GROUP_PATH")"
else
  export BASE_MAX_ENV_CALLS
fi

if [[ -z "${MAX_ENV_CALLS+x}" ]]; then
  export MAX_ENV_CALLS="$((BASE_MAX_ENV_CALLS + 2 * INTERVENTION_BUDGET))"
else
  export MAX_ENV_CALLS
fi

if [[ "$TEST_MAX_ENV_CALLS" =~ ^[1-9][0-9]*$ ]]; then
  export MAX_ENV_CALLS="$TEST_MAX_ENV_CALLS"
fi

print_runtime_header "run_react_simple-mem_experiment"
echo "Experiment family: $EXPERIMENT_FAMILY"
echo "Output tag: $OUTPUT_TAG"
echo "Graphs: $CAUSAL_GRAPH_GROUP"
echo "Initial observations: $CAUSAL_INITIAL_OBSERVATIONS"
echo "Intervention budget: $INTERVENTION_BUDGET"
echo "BASE_MAX_ENV_CALLS: $BASE_MAX_ENV_CALLS"
echo "MAX_ENV_CALLS: $MAX_ENV_CALLS"
echo "Causal tool enabled: $CAUSAL_TOOL_ENABLED"
echo "Oracle chains enabled: $PROPERTY_MANIPULATOR_ORACLE_CHAINS"

ensure_openai_api_key_if_needed

echo "Using conda environment: ${CONDA_DEFAULT_ENV:-unknown}"
echo "Python path: $(which python)"

if [[ "${FREQ_ESTIMATOR}" == "1" ]]; then
  FREQ_TAG="inter"
else
  FREQ_TAG="obs"
fi

TS="$(date +%Y%m%d-%H%M%S)"
export TS
SAFE_MODEL="$(echo "$MODEL" | sed 's#[^A-Za-z0-9_.-]#_#g')"
if [[ -n "$BASE_OUTPUT_DIR_OVERRIDE" ]]; then
  BASE_OUTPUT_DIR="$BASE_OUTPUT_DIR_OVERRIDE"
else
  BASE_OUTPUT_DIR="output_dir/react_simple-mem/${OUTPUT_TAG}_${SAFE_MODEL}"
fi

SETTING_TAG="${CAUSAL_INITIAL_OBSERVATIONS}o${INTERVENTION_BUDGET}i"
EXPERIMENT_SUBDIR=""
if [[ -n "$EXPERIMENT_SUBDIR_OVERRIDE" ]]; then
  EXPERIMENT_SUBDIR="$EXPERIMENT_SUBDIR_OVERRIDE"
elif [[ -n "$BASE_OUTPUT_DIR_OVERRIDE" ]]; then
  if [[ "$EXPERIMENT_FAMILY" == scaling_* ]]; then
    EXPERIMENT_SUBDIR="$SETTING_TAG/${TS}_${SETTING_TAG}"
  else
    EXPERIMENT_SUBDIR="$OUTPUT_TAG"
  fi
fi

RUN_OUTPUT_DIR="$BASE_OUTPUT_DIR"
if [[ -n "$EXPERIMENT_SUBDIR" ]]; then
  RUN_OUTPUT_DIR="$BASE_OUTPUT_DIR/$EXPERIMENT_SUBDIR"
fi
export SETTING_TAG
export EXPERIMENT_SUBDIR
export RUN_OUTPUT_DIR

mkdir -p "$RUN_OUTPUT_DIR"

python - <<'PY' > "$RUN_OUTPUT_DIR/suite_manifest.json"
import json, os
payload = {
    "output_tag": os.environ["OUTPUT_TAG"],
    "experiment_family": os.environ["EXPERIMENT_FAMILY"],
    "experiment_subdir": os.environ.get("EXPERIMENT_SUBDIR", ""),
    "setting_tag": os.environ.get("SETTING_TAG", ""),
    "graph_group": os.environ["CAUSAL_GRAPH_GROUP"],
    "initial_observations": int(os.environ["CAUSAL_INITIAL_OBSERVATIONS"]),
    "intervention_budget": int(os.environ["INTERVENTION_BUDGET"]),
    "max_env_calls": int(os.environ["MAX_ENV_CALLS"]),
    "causal_tool_enabled": os.environ["CAUSAL_TOOL_ENABLED"] == "1",
    "property_manipulator_oracle_chains": os.environ["PROPERTY_MANIPULATOR_ORACLE_CHAINS"] == "1",
    "model": os.environ["MODEL"],
    "config_file": os.environ["CONFIG_FILE"],
    "run_timestamp": os.environ.get("TS"),
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY

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
NUM_SEEDS=${#SEEDS[@]}

SCRIPT_PID=$$
TIMESTAMP_SEC="$(date +%s)"
UNIQUE_OFFSET=$(( (TIMESTAMP_SEC % 10000) + (SCRIPT_PID % 10000) ))
BASE_OFFSET=$((MAX_ENV_CALLS / 100))
BASE_THREADID_OFFSET=$((BASE_OFFSET + UNIQUE_OFFSET))

declare -a FAILED_GRAPHS=()
TOTAL_GRAPHS=${#GRAPH_IDS[@]}

echo "Base output directory: $BASE_OUTPUT_DIR"
echo "Run output directory: $RUN_OUTPUT_DIR"
echo "Loaded graphs: $TOTAL_GRAPHS"
echo "Seeds per graph: $NUM_SEEDS (${SEEDS[*]})"
echo "Batch size: $BATCH_SIZE"

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
    if [[ -n "$BASE_OUTPUT_DIR_OVERRIDE" ]]; then
      GRAPH_ROOT="$RUN_OUTPUT_DIR/${GRAPH_SAFE}_${MAX_ENV_CALLS}calls"
    else
      JSONL_BASENAME="$(basename "$GROUP_PATH" .jsonl)"
      GRAPH_ROOT="$RUN_OUTPUT_DIR/${JSONL_BASENAME}/${TS}_${PROMPT_NAME}/${GRAPH_SAFE}_${MAX_ENV_CALLS}calls"
    fi
    mkdir -p "$GRAPH_ROOT"

    for ENV_SEED in "${SEEDS[@]}"; do
      SUBDIR="$GRAPH_ROOT/seed_$ENV_SEED"
      mkdir -p "$SUBDIR"
      cp "$CURRENT_GRAPH_FILE" "$SUBDIR/graph_config.json"

      CURRENT_GRAPH_ID="$CURRENT_GRAPH_ID" ENV_SEED="$ENV_SEED" python - <<'PY' > "$SUBDIR/experiment_manifest.json"
import json, os
payload = {
    "output_tag": os.environ["OUTPUT_TAG"],
    "experiment_family": os.environ["EXPERIMENT_FAMILY"],
    "graph_group": os.environ["CAUSAL_GRAPH_GROUP"],
    "graph_id": os.environ["CURRENT_GRAPH_ID"],
    "model": os.environ["MODEL"],
    "llm_seed": int(os.environ["SEED"]),
    "env_seed": int(os.environ["ENV_SEED"]),
    "setting_tag": os.environ.get("SETTING_TAG", ""),
    "initial_observations": int(os.environ["CAUSAL_INITIAL_OBSERVATIONS"]),
    "intervention_budget": int(os.environ["INTERVENTION_BUDGET"]),
    "max_env_calls": int(os.environ["MAX_ENV_CALLS"]),
    "causal_tool_enabled": os.environ["CAUSAL_TOOL_ENABLED"] == "1",
    "property_manipulator_oracle_chains": os.environ["PROPERTY_MANIPULATOR_ORACLE_CHAINS"] == "1",
    "run_timestamp": os.environ.get("TS"),
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY

      UNIQUE_THREADID_OFFSET=$((BASE_THREADID_OFFSET + idx * 100 + ENV_SEED))
      if [[ "$DRY_RUN" == "1" ]]; then
        echo "[DRY_RUN] graph=$CURRENT_GRAPH_ID seed=$ENV_SEED subdir=$SUBDIR threadid=$UNIQUE_THREADID_OFFSET"
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
        CURRENT_GRAPH_ID="$CURRENT_GRAPH_ID" \
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
echo "Output directory: $RUN_OUTPUT_DIR"
echo "Graphs processed: $TOTAL_GRAPHS"
echo "Seeds per graph: $NUM_SEEDS"
echo "Dry run: $DRY_RUN"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "Dry run finished successfully."
  exit 0
fi
if [[ ${#FAILED_GRAPHS[@]} -eq 0 ]]; then
  echo "All tasks completed successfully."
  exit 0
fi
echo "Failed graphs: ${FAILED_GRAPHS[*]}" >&2
exit 1
