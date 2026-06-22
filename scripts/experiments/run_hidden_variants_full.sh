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
export OPENAI_API_BASE="${OPENAI_API_BASE:-https://api.openai.com/v1}"

SAFE_MODEL="$(echo "$MODEL" | sed 's#[^A-Za-z0-9_.-]#_#g')"
export HIDDEN_BASE="${HIDDEN_BASE:-output_dir/react_simple-mem/obs_CausalHidden_${SAFE_MODEL}/4nodes_hidden_variants}"

print_runtime_header "run_hidden_variants_full"
echo "Model: ${MODEL}"
echo "Batch size: ${BATCH_SIZE}"
echo "Seeds per graph: ${SEEDS_PER_GRAPH}"
echo "Graph limit: ${GRAPH_LIMIT}"
echo "Output root: ${HIDDEN_BASE}"

ensure_openai_api_key_if_needed

if [[ "$DRY_RUN" == "1" ]]; then
  python "$SCRIPT_DIR/generate_hidden_variant_configs.py" --dry-run
else
  python "$SCRIPT_DIR/generate_hidden_variant_configs.py"
fi

HIDDEN_SPECS=(
  "4nodes_hidden_vrange_pm0p5.jsonl:hidden_vrange_pm0p5"
  "4nodes_hidden_vrange_pm5.jsonl:hidden_vrange_pm5"
  "4nodes_hidden_vrange_pm50.jsonl:hidden_vrange_pm50"
  "4nodes_hidden_n1.jsonl:hidden_n1"
  "4nodes_hidden_n2.jsonl:hidden_n2"
  "4nodes_hidden_n3.jsonl:hidden_n3"
)

for spec in "${HIDDEN_SPECS[@]}"; do
  IFS=":" read -r graph_group output_tag <<< "$spec"
  echo "============================================================================"
  echo "Running hidden variant: ${output_tag}"
  echo "Graph group: ${graph_group}"
  echo "============================================================================"

  env \
    MODEL="${MODEL}" \
    SEEDS_PER_GRAPH="${SEEDS_PER_GRAPH}" \
    BATCH_SIZE="${BATCH_SIZE}" \
    GRAPH_LIMIT="${GRAPH_LIMIT}" \
    DRY_RUN="${DRY_RUN}" \
    OPENAI_API_BASE="${OPENAI_API_BASE}" \
    CAUSAL_GRAPH_GROUP="${graph_group}" \
    OUTPUT_TAG="${output_tag}" \
    BASE_OUTPUT_DIR_OVERRIDE="${HIDDEN_BASE}" \
    REACTOR_TASK_PROMPT_MODE="dsl_hidden" \
    PROMPT_NAME="dsl_hidden" \
    bash "$SCRIPT_DIR/run_react_simple-mem_parallel_hidden_variants.sh"
done
