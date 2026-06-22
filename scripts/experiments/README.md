# Experiment Scripts

This directory contains shell entrypoints for running CausaLab experiment suites
from a standard local shell on a workstation or server. All paths are resolved
relative to the repository root.

Most scripts support these environment variables:

- `DRY_RUN=1`: print planned jobs without model API calls.
- `GRAPH_LIMIT=N`: restrict to the first `N` graph configs.
- `SEEDS_PER_GRAPH=N`: number of environment seeds per graph.
- `BATCH_SIZE=N`: number of concurrent jobs.
- `SKIP_CONDA_ACTIVATE=1`: use the current Python environment.

Examples:

```bash
SKIP_CONDA_ACTIVATE=1 DRY_RUN=1 GRAPH_LIMIT=1 \
  bash scripts/experiments/run_react_simple-mem_freqparent_4nodes_main.sh
```

```bash
export OPENAI_API_KEY=...
bash scripts/experiments/run_react_simple-mem_parallel.sh
```

```bash
export OPENAI_API_KEY=...
bash scripts/experiments/run_react_simple-mem_oracle_main_suite.sh
```

```bash
export OPENAI_API_KEY=...
bash scripts/experiments/run_react_simple-mem_freqparent_6nodes_main.sh
```

```bash
export OPENAI_API_KEY=...
bash scripts/experiments/run_react_simple-mem_golden_4nodes_main.sh
```

```bash
export OPENAI_API_KEY=...
bash scripts/experiments/run_react_simple-mem_scaling_oracle_suite.sh
```

```bash
export OPENAI_API_KEY=...
python scripts/experiments/monitor_long_runs.py --interval-seconds 1800
```

The main-suite wrappers route through `run_react_simple-mem_experiment.sh`, so
they write `suite_manifest.json` and per-run `experiment_manifest.json` files in
timestamped output directories. Local caches and temporary files default to
`./.runtime_local`; experiment outputs default to `./output_dir`.
