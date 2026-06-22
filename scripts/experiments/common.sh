#!/bin/bash

set -euo pipefail

experiments_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

repo_root() {
  local script_dir
  script_dir="$(experiments_dir)"
  cd "${script_dir}/../.." && pwd
}

setup_repo_environment() {
  export ROOT="${ROOT:-$(repo_root)}"
  export LOCAL_JOB_ID="${LOCAL_JOB_ID:-${SLURM_JOB_ID:-$$}}"
  export SLURM_JOB_ID="${SLURM_JOB_ID:-$LOCAL_JOB_ID}"

  export PROJECT_ROOT="${PROJECT_ROOT:-$ROOT}"
  export WORK_ROOT="${WORK_ROOT:-$ROOT/.runtime_local}"

  mkdir -p "$WORK_ROOT/.cache" "$WORK_ROOT/tmp"

  export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$WORK_ROOT/.cache}"
  export HF_HOME="${HF_HOME:-$XDG_CACHE_HOME/huggingface}"
  export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME/transformers}"
  export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME/hub}"
  export VLLM_CACHE_DIR="${VLLM_CACHE_DIR:-$XDG_CACHE_HOME/vllm}"
  export CUDA_CACHE_PATH="${CUDA_CACHE_PATH:-$XDG_CACHE_HOME/nv}"
  export TMPDIR="${TMPDIR:-$WORK_ROOT/tmp}"

  mkdir -p \
    "$XDG_CACHE_HOME" \
    "$HF_HOME" \
    "$TRANSFORMERS_CACHE" \
    "$HUGGINGFACE_HUB_CACHE" \
    "$VLLM_CACHE_DIR" \
    "$CUDA_CACHE_PATH" \
    "$TMPDIR"

  export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-4}"
  export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
  export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
  export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-4}"
}

activate_discoveryworld_env() {
  if [[ "${SKIP_CONDA_ACTIVATE:-0}" == "1" ]]; then
    return 0
  fi

  # Preserve externally provided API settings across shell init.
  # Some user bashrc files unconditionally export OPENAI_* vars.
  local preserved_openai_api_key="${OPENAI_API_KEY-__UNSET__}"
  local preserved_openai_api_base="${OPENAI_API_BASE-__UNSET__}"

  if [[ -f "$HOME/.bashrc" ]]; then
    # Some interactive bashrc files reference unset prompt variables like PS1.
    # Temporarily relax nounset while sourcing to stay script-safe on Ubuntu boxes.
    local had_nounset=0
    case $- in
      *u*) had_nounset=1 ;;
    esac
    set +u
    # shellcheck disable=SC1090
    source "$HOME/.bashrc"
    if [[ "$had_nounset" == "1" ]]; then
      set -u
    fi
  fi

  if [[ "$preserved_openai_api_key" != "__UNSET__" ]]; then
    export OPENAI_API_KEY="$preserved_openai_api_key"
  fi
  if [[ "$preserved_openai_api_base" != "__UNSET__" ]]; then
    export OPENAI_API_BASE="$preserved_openai_api_base"
  fi

  if ! command -v conda >/dev/null 2>&1; then
    echo "WARN: conda not found; continuing without conda activation." >&2
    return 0
  fi

  local conda_hook
  conda_hook="$(conda shell.bash hook 2>/dev/null || true)"
  if [[ -n "$conda_hook" ]]; then
    eval "$conda_hook"
  fi

  if ! conda activate "${CONDA_ENV_NAME:-causalab}" >/dev/null 2>&1; then
    echo "WARN: failed to activate conda env ${CONDA_ENV_NAME:-causalab}; continuing anyway." >&2
  fi
}

enter_repo_root() {
  cd "$ROOT"
}

ensure_openai_api_key_if_needed() {
  local dry_run="${DRY_RUN:-0}"
  if [[ "$dry_run" != "1" && -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: OPENAI_API_KEY is not set. Export it before running non-dry-run jobs." >&2
    exit 1
  fi
}

print_runtime_header() {
  local label="${1:-job}"
  echo "============================================================================"
  echo "${label} starting on $(hostname) at $(date)"
  echo "Local job ID: ${LOCAL_JOB_ID:-$$}"
  echo "Repo root: ${ROOT:-unknown}"
  echo "Work root: ${WORK_ROOT:-unknown}"
  echo "============================================================================"
}

default_base_max_env_calls_for_node_count() {
  case "${1:-}" in
    3) echo "28" ;;
    4) echo "29" ;;
    5) echo "30" ;;
    6) echo "31" ;;
    7) echo "32" ;;
    *) return 1 ;;
  esac
}

infer_node_count_from_graph_ref() {
  local graph_ref="${1:-}"
  local inferred=""

  if [[ "${NODE_COUNT:-}" =~ ^[3-7]$ ]]; then
    echo "$NODE_COUNT"
    return 0
  fi

  if [[ -n "$graph_ref" && "$graph_ref" =~ (^|/)([3-7])nodes([_.-]|/|$) ]]; then
    echo "${BASH_REMATCH[2]}"
    return 0
  fi

  if [[ -n "$graph_ref" && -f "$graph_ref" ]]; then
    inferred="$(
      python3 - "$graph_ref" <<'PY' 2>/dev/null || true
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])

def infer_from_graph_id(graph_id):
    if not isinstance(graph_id, str):
        return None
    prefix = graph_id.split("_", 1)[0]
    if prefix.endswith("nodes") and prefix[:-5].isdigit():
        value = int(prefix[:-5])
        if 3 <= value <= 7:
            return str(value)
    return None

try:
    if path.suffix == ".json":
        raw = path.read_text(encoding="utf-8").strip()
        if raw:
            graph = json.loads(raw)
            inferred = infer_from_graph_id(graph.get("graph_id"))
            if inferred:
                print(inferred)
    else:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                graph = json.loads(raw)
                inferred = infer_from_graph_id(graph.get("graph_id"))
                if inferred:
                    print(inferred)
                break
except Exception:
    pass
PY
    )"
    if [[ "$inferred" =~ ^[3-7]$ ]]; then
      echo "$inferred"
      return 0
    fi
  fi

  return 1
}

resolve_base_max_env_calls() {
  local graph_ref="${1:-}"
  local node_count=""

  if node_count="$(infer_node_count_from_graph_ref "$graph_ref")"; then
    default_base_max_env_calls_for_node_count "$node_count"
  else
    echo "38"
  fi
}
