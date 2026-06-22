#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/common.sh"

setup_repo_environment
activate_discoveryworld_env
enter_repo_root

export MODEL="${MODEL:-gpt-5-mini}"
export GRAPH_LIMIT="${GRAPH_LIMIT:-5}"
export SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH:-1}"
export BATCH_SIZE="${BATCH_SIZE:-5}"
export TEST_MAX_ENV_CALLS="${TEST_MAX_ENV_CALLS:-0}"
export MAX_PARALLEL_SETTINGS="${MAX_PARALLEL_SETTINGS:-3}"
export ANALYSIS_HIDDEN_SOURCE="${ANALYSIS_HIDDEN_SOURCE:-output_dir/react_simple-mem/obs_CausalHidden_gpt-5-mini_seed1_selected.tar.gz}"
export ANALYSIS_NONHIDDEN_SOURCE="${ANALYSIS_NONHIDDEN_SOURCE:-output_dir/react_simple-mem/obs_Causal_gpt-5-mini/4nodes/20260223-2134_dsl_right}"
export ANALYSIS_MODEL="${ANALYSIS_MODEL:-$MODEL}"
export ANALYSIS_API_BASE="${ANALYSIS_API_BASE:-${OPENAI_API_BASE:-https://api.openai.com/v1}}"
if [[ -z "${ANALYSIS_API_KEY+x}" ]]; then
  export ANALYSIS_API_KEY="${OPENAI_API_KEY:-}"
else
  export ANALYSIS_API_KEY
fi
export ANALYSIS_MAX_RUNS="${ANALYSIS_MAX_RUNS:-0}"
export SKIP_BASELINE_ANALYSIS="${SKIP_BASELINE_ANALYSIS:-0}"
export SECOND_ROUND_ENABLED="${SECOND_ROUND_ENABLED:-1}"
export DRY_RUN="${DRY_RUN:-0}"

TS="$(date +%Y%m%d-%H%M%S)"
SAFE_MODEL="$(echo "$MODEL" | sed 's#[^A-Za-z0-9_.-]#_#g')"
ANALYSIS_OUTPUT_DIR="${ANALYSIS_OUTPUT_DIR:-output_dir/hidden_adaptive_analysis/${TS}_${SAFE_MODEL}}"
RUN_OUTPUT_ROOT="${RUN_OUTPUT_ROOT:-output_dir/react_simple-mem/obs_CausalHiddenAdaptive_${SAFE_MODEL}/4nodes_hidden_adaptive}"

print_runtime_header "run_hidden_adaptive"
echo "Analysis hidden source: $ANALYSIS_HIDDEN_SOURCE"
echo "Analysis nonhidden source: $ANALYSIS_NONHIDDEN_SOURCE"
echo "Analysis output dir: $ANALYSIS_OUTPUT_DIR"
echo "Run output root: $RUN_OUTPUT_ROOT"
echo "GRAPH_LIMIT: $GRAPH_LIMIT"
echo "SEEDS_PER_GRAPH: $SEEDS_PER_GRAPH"
echo "TEST_MAX_ENV_CALLS: $TEST_MAX_ENV_CALLS"

mkdir -p "$ANALYSIS_OUTPUT_DIR" "$RUN_OUTPUT_ROOT"

if [[ "$SKIP_BASELINE_ANALYSIS" != "1" && ! -e "$ANALYSIS_NONHIDDEN_SOURCE" ]]; then
  AUTO_NONHIDDEN="$(
    python - <<'PY'
from pathlib import Path
root = Path("output_dir/react_simple-mem")
for obs_dir in sorted(root.glob("obs_Causal*")):
    if not obs_dir.is_dir() or "Hidden" in obs_dir.name:
        continue
    candidate = obs_dir / "4nodes"
    if candidate.exists():
        print(candidate)
        break
PY
  )"
  if [[ -n "$AUTO_NONHIDDEN" ]]; then
    ANALYSIS_NONHIDDEN_SOURCE="$AUTO_NONHIDDEN"
    export ANALYSIS_NONHIDDEN_SOURCE
  fi
fi

echo "Resolved nonhidden source: ${ANALYSIS_NONHIDDEN_SOURCE:-<none>}"

echo "== generate paired hidden variants =="
if [[ "$DRY_RUN" == "1" ]]; then
  python "$SCRIPT_DIR/generate_hidden_variant_configs.py" --dry-run
else
  python "$SCRIPT_DIR/generate_hidden_variant_configs.py"
fi

echo "== analyze existing hidden runs =="
ANALYZE_ARGS=(
  --hidden-root "$ANALYSIS_HIDDEN_SOURCE"
  --output-dir "$ANALYSIS_OUTPUT_DIR"
  --model "$ANALYSIS_MODEL"
  --api-base "$ANALYSIS_API_BASE"
  --api-key "$ANALYSIS_API_KEY"
)
if [[ "$ANALYSIS_MAX_RUNS" =~ ^[1-9][0-9]*$ ]]; then
  ANALYZE_ARGS+=(--max-runs "$ANALYSIS_MAX_RUNS")
fi
if [[ "$SKIP_BASELINE_ANALYSIS" != "1" && -n "${ANALYSIS_NONHIDDEN_SOURCE:-}" && -e "$ANALYSIS_NONHIDDEN_SOURCE" ]]; then
  ANALYZE_ARGS+=(--nonhidden-root "$ANALYSIS_NONHIDDEN_SOURCE")
else
  echo "WARN: skipping nonhidden baseline analysis; continuing with hidden-only analysis." >&2
fi
python "$SCRIPT_DIR/analyze_hidden_adaptive.py" "${ANALYZE_ARGS[@]}"

ROOT_CAUSE_JSON="$ANALYSIS_OUTPUT_DIR/root_cause_summary.json"
if [[ ! -f "$ROOT_CAUSE_JSON" ]]; then
  echo "ERROR: missing analysis output: $ROOT_CAUSE_JSON" >&2
  exit 1
fi

mapfile -t CANDIDATE_FAMILIES < <(
  python - "$ROOT_CAUSE_JSON" <<'PY'
import json, sys
data = json.loads(open(sys.argv[1], encoding="utf-8").read())
families = data.get("suggested_families") or ["paired_variants"]
for family in families:
    print(family)
PY
)

if [[ ${#CANDIDATE_FAMILIES[@]} -eq 0 ]]; then
  CANDIDATE_FAMILIES=("paired_variants")
fi

echo "Suggested families: ${CANDIDATE_FAMILIES[*]}"

SETTINGS_PIDS=()
SETTINGS_LABELS=()
running_jobs=0

wait_for_slot() {
  while (( running_jobs >= MAX_PARALLEL_SETTINGS )); do
    if ! wait -n; then
      echo "A quick-validation job failed." >&2
      exit 1
    fi
    running_jobs=$((running_jobs - 1))
  done
}

run_setting_job() {
  local family="$1"
  local setting_name="$2"
  local graph_group="$3"
  local prompt_mode="$4"
  local initial_observations="$5"
  local intervention_budget="$6"
  local base_max_env_calls="$7"

  local family_root="$RUN_OUTPUT_ROOT/quick_validation/$family"
  wait_for_slot

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY_RUN][$family/$setting_name] graph_group=$graph_group prompt_mode=$prompt_mode obs=$initial_observations budget=$intervention_budget"
    return 0
  fi

  (
    env \
      MODEL="$MODEL" \
      GRAPH_LIMIT="$GRAPH_LIMIT" \
      SEEDS_PER_GRAPH="$SEEDS_PER_GRAPH" \
      BATCH_SIZE="$BATCH_SIZE" \
      TEST_MAX_ENV_CALLS="$TEST_MAX_ENV_CALLS" \
      OUTPUT_TAG="$setting_name" \
      EXPERIMENT_FAMILY="$family" \
      CAUSAL_GRAPH_GROUP="$graph_group" \
      REACTOR_TASK_PROMPT_MODE="$prompt_mode" \
      PROMPT_NAME="$prompt_mode" \
      CAUSAL_INITIAL_OBSERVATIONS="$initial_observations" \
      INTERVENTION_BUDGET="$intervention_budget" \
      BASE_MAX_ENV_CALLS="$base_max_env_calls" \
      BASE_OUTPUT_DIR_OVERRIDE="$family_root" \
      EXPERIMENT_SUBDIR_OVERRIDE="$setting_name" \
      bash "$SCRIPT_DIR/run_react_simple-mem_experiment.sh"
  ) &

  SETTINGS_PIDS+=("$!")
  SETTINGS_LABELS+=("$family/$setting_name")
  running_jobs=$((running_jobs + 1))
}

launch_family() {
  local family="$1"
  local initial_observations="$2"
  local intervention_budget="$3"
  local base_max_env_calls="$4"

  run_setting_job "$family" "baseline" "4nodes.jsonl" "dsl" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
  run_setting_job "$family" "hidden_vrange_pm0p5" "4nodes_hidden_vrange_pm0p5.jsonl" "dsl_hidden" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
  run_setting_job "$family" "hidden_vrange_pm5" "4nodes_hidden_vrange_pm5.jsonl" "dsl_hidden" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
  run_setting_job "$family" "hidden_vrange_pm50" "4nodes_hidden_vrange_pm50.jsonl" "dsl_hidden" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
  run_setting_job "$family" "hidden_n1" "4nodes_hidden_n1.jsonl" "dsl_hidden" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
  run_setting_job "$family" "hidden_n2" "4nodes_hidden_n2.jsonl" "dsl_hidden" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
  run_setting_job "$family" "hidden_n3" "4nodes_hidden_n3.jsonl" "dsl_hidden" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
  run_setting_job "$family" "hidden_freqnode_n1" "4nodes_hidden_freqnode_n1.jsonl" "dsl_hidden_freqnode" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
  run_setting_job "$family" "hidden_freqnode_n2" "4nodes_hidden_freqnode_n2.jsonl" "dsl_hidden_freqnode" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
  run_setting_job "$family" "hidden_freqnode_n3" "4nodes_hidden_freqnode_n3.jsonl" "dsl_hidden_freqnode" "$initial_observations" "$intervention_budget" "$base_max_env_calls"
}

echo "== launch quick-validation families =="
for family in "${CANDIDATE_FAMILIES[@]}"; do
  case "$family" in
    paired_variants)
      launch_family "$family" 2 12 29
      ;;
    evidence_starved)
      launch_family "$family" 0 3 29
      ;;
    critical_nodes)
      launch_family "$family" 0 3 29
      ;;
    *)
      echo "WARN: unknown family '$family', skipping." >&2
      ;;
  esac
done

if [[ "$DRY_RUN" != "1" ]]; then
  while (( running_jobs > 0 )); do
    if ! wait -n; then
      echo "A quick-validation setting failed." >&2
      exit 1
    fi
    running_jobs=$((running_jobs - 1))
  done
fi

verify_family() {
  local family="$1"
  local family_root="$RUN_OUTPUT_ROOT/quick_validation/$family"
  if [[ ! -d "$family_root" ]]; then
    echo "WARN: family root missing, skip verify: $family_root" >&2
    return 1
  fi

  python "$SCRIPT_DIR/verify_hidden_adaptive_runs.py" \
    "$family_root" \
    --output-json "$family_root/verify_summary.json"

  python - "$family_root" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
stats = {}
for complete_file in root.rglob("*_complete.txt"):
    run_dir = complete_file.parent
    manifest_path = run_dir / "experiment_manifest.json"
    if not manifest_path.exists():
        continue
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    setting = manifest.get("output_tag", run_dir.parent.name)
    stats.setdefault(setting, {"total": 0, "correct": 0})
    token = complete_file.read_text(encoding="utf-8").strip().split()
    if not token:
        continue
    if token[0] not in {"0", "1"}:
        continue
    stats[setting]["total"] += 1
    stats[setting]["correct"] += int(token[0])

accuracy = {
    key: (value["correct"] / value["total"]) if value["total"] else None
    for key, value in stats.items()
}
pm_keys = ["hidden_vrange_pm0p5", "hidden_vrange_pm5", "hidden_vrange_pm50"]
n_keys = ["hidden_n1", "hidden_n2", "hidden_n3"]
pm_monotonic = all(
    accuracy.get(pm_keys[idx]) is not None
    and accuracy.get(pm_keys[idx + 1]) is not None
    and accuracy[pm_keys[idx]] >= accuracy[pm_keys[idx + 1]]
    for idx in range(len(pm_keys) - 1)
)
n_monotonic = all(
    accuracy.get(n_keys[idx]) is not None
    and accuracy.get(n_keys[idx + 1]) is not None
    and accuracy[n_keys[idx]] >= accuracy[n_keys[idx + 1]]
    for idx in range(len(n_keys) - 1)
)
freqnode_keys = ["hidden_freqnode_n1", "hidden_freqnode_n2", "hidden_freqnode_n3"]
freqnode_monotonic = all(
    accuracy.get(freqnode_keys[idx]) is not None
    and accuracy.get(freqnode_keys[idx + 1]) is not None
    and accuracy[freqnode_keys[idx]] >= accuracy[freqnode_keys[idx + 1]]
    for idx in range(len(freqnode_keys) - 1)
)
summary = {
    "accuracy_by_setting": accuracy,
    "pm_monotonic": pm_monotonic,
    "n_monotonic": n_monotonic,
    "freqnode_monotonic": freqnode_monotonic,
}
(root / "quick_accuracy_summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
}

echo "== verify quick-validation outputs =="
NON_MONOTONIC_FAMILY=""
for family in "${CANDIDATE_FAMILIES[@]}"; do
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY_RUN] verify family $family"
    continue
  fi
  verify_family "$family"
  if [[ -z "$NON_MONOTONIC_FAMILY" ]]; then
    if ! python - "$RUN_OUTPUT_ROOT/quick_validation/$family/quick_accuracy_summary.json" <<'PY'
import json, sys
data = json.loads(open(sys.argv[1], encoding="utf-8").read())
raise SystemExit(0 if data.get("pm_monotonic") and data.get("n_monotonic") and data.get("freqnode_monotonic") else 1)
PY
    then
      if [[ "$family" != "paired_variants" ]]; then
        NON_MONOTONIC_FAMILY="$family"
      fi
    fi
  fi
done

if [[ "$DRY_RUN" != "1" && "$SECOND_ROUND_ENABLED" == "1" && -n "$NON_MONOTONIC_FAMILY" ]]; then
  echo "== second round: budget 2 for $NON_MONOTONIC_FAMILY =="
  launch_family "${NON_MONOTONIC_FAMILY}_round2" 0 2 38
  while (( running_jobs > 0 )); do
    if ! wait -n; then
      echo "A second-round setting failed." >&2
      exit 1
    fi
    running_jobs=$((running_jobs - 1))
  done
  verify_family "${NON_MONOTONIC_FAMILY}_round2"
fi

echo "Hidden adaptive workflow completed."
