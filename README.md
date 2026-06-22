<div align="center">

# CausaLab

### Can an LLM Agent Discover a Causal Law the Way a Scientist Would — by Experimenting?

[![Paper](https://img.shields.io/badge/paper-arXiv%202605.26029-b31b1b?style=flat-square&logo=arxiv)](https://arxiv.org/abs/2605.26029)
[![Blog](https://img.shields.io/badge/blog-dylanzsz.github.io%2Fcausalab-4285F4?style=flat-square&logo=googlechrome&logoColor=white)](https://dylanzsz.github.io/causalab)
[![Website](https://img.shields.io/badge/website-dylanzsz.github.io-0a0a0a?style=flat-square&logo=githubpages)](https://dylanzsz.github.io)
[![GitHub](https://img.shields.io/badge/GitHub-DylanZSZ%2FCausaLab--Benchmark-181717?style=flat-square&logo=github)](https://github.com/DylanZSZ/CausaLab-Benchmark)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](LICENSE.txt)
[![Python](https://img.shields.io/badge/python-3.10-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)

<br/>

> **⚠️ Early Release Notice:** This is version 0.0.2 — the first public release of CausaLab. Interfaces and dataset formats may change. Please open an issue if you encounter problems.

<br/>

<img src="https://dylanzsz.github.io/causalab/figures/episode_overview.png" alt="One CausaLab episode" width="780"/>

*One CausaLab episode. A hidden SCM generates prior records, a manipulator crystal the agent can poke, and a held-out reactor crystal governed by the same law. The agent intervenes, observes, writes its current causal hypothesis, and finally predicts the reactor's hidden frequency. We score prediction AND the recovered graph + equation against ground truth.*

</div>

---

## Why CausaLab?

A real scientist does not look up how the world works. They **intervene** on it, watch what changes, and revise a theory until it transfers to a case they have never seen.

Current LLM benchmarks mostly test *retrieval* — can the model recall a known fact? CausaLab tests *discovery*: can the agent run experiments, recover the causal mechanism from scratch, and apply it to a novel crystal it has never seen?

**Three headline results from our paper:**

| Finding | Detail |
|---------|--------|
| **Prediction ≠ Understanding** | `GPT-5.2-high` reaches **92% task accuracy** on 6-node graphs but only **0.47 all-edge F₁** — right number, wrong graph. |
| **How you experiment is the whole game** | Agent-chosen interventions recover faithful structure; handing the agent perfect pre-collected data ("Golden") boosts the answer but *not* the mechanism. The *act of choosing* the experiment carries the structural signal. |
| **Agents fail by stopping early** | Win or lose, runs leave ~half their intervention budget unused. A single "check your theory against your evidence" step lifts 4-node accuracy from **48% → 60%**. |

---

## Repository Structure

```
CausaLab/
├── discoveryworld/              # Reactor Lab environment (DiscoveryWorld fork)
│   └── scenarios/reactor_lab.py #   ← the CausaLab task
├── agents/recoma/               # ReAct / Recoma agent, prompts, model adapters
│   ├── run_recoma.py            #   ← main agent runner
│   └── prompts/                 #   ← DSL & non-DSL prompt variants
├── scripts/
│   ├── experiments/             # Experiment launch scripts & summarizer
│   ├── vis_backend/             # Trajectory visualization server
│   └── vis_frontend/            # Visualization UI
├── causalab_reeval/             # ReEval scoring module
├── release/causalab_dataset/    # Released synthetic graph configs (950 records)
│   └── data/                    #   ← 19 JSONL suites, 3–7 nodes
└── examples/sample_runs/        # Bundled sample trajectory for offline checks
```

---

## Installation

Requires **Python 3.10**.

```bash
conda create -n causalab python=3.10 -y
conda activate causalab
pip install --upgrade pip
pip install --use-pep517 -r agents/requirements.txt
pip install -e .
```

For API-backed runs, export your key:

```bash
export OPENAI_API_KEY=sk-...
# Optionally override the endpoint (e.g. for Azure, Together, etc.)
export OPENAI_API_BASE=https://api.openai.com/v1
```

Offline smoke checks (dry-run, ReEval on sample) do not require an API key.

---

## Quick Start

### 1. Dry-run (no API calls)

Verify setup, graph loading, and manifest expansion:

```bash
SKIP_CONDA_ACTIVATE=1 DRY_RUN=1 GRAPH_LIMIT=1 \
  bash scripts/experiments/run_react_simple-mem_freqparent_4nodes_main.sh
```

### 2. ReEval on the bundled sample

Score the bundled sample trajectory without any API calls:

```bash
python -m causalab_reeval.run_lightweight_reeval \
  --source-only --limit 1 \
  --output-dir output_dir/reeval_sample \
  examples/sample_runs/react_simple-mem
```

### 3. Visualize a trajectory

```bash
python scripts/vis_backend/visualization_server.py
# → open http://127.0.0.1:5001
```

---

## Running Experiments

Experiment scripts live in `scripts/experiments/`. All resolve paths relative to the repository root; outputs go under `output_dir/`.

**Useful environment controls (most scripts):**

| Variable | Effect |
|----------|--------|
| `DRY_RUN=1` | Print jobs without API calls |
| `GRAPH_LIMIT=N` | First N graph configs only |
| `SEEDS_PER_GRAPH=N` | Seeds per graph |
| `BATCH_SIZE=N` | Concurrent local jobs |
| `SKIP_CONDA_ACTIVATE=1` | Use current Python env |

**Representative suites:**

```bash
# Main 4-node / 6-node runs (GPT-5-mini)
bash scripts/experiments/run_react_simple-mem_parallel.sh

# GPT-5.2 scaling
bash scripts/experiments/run_react_simple-mem_scaling_gpt52.sh

# Observation / intervention scaling
bash scripts/experiments/run_react_simple-mem_scaling_suite.sh
bash scripts/experiments/run_react_simple-mem_scaling_suite_6nodes.sh

# Quadratic formula suites
bash scripts/experiments/run_react_simple-mem_4nodes_quad.sh
bash scripts/experiments/run_react_simple-mem_4nodes_quad_hard.sh

# Hidden-variable suites
bash scripts/experiments/run_hidden_variants_full.sh
bash scripts/experiments/run_hidden_frequency_node_priority_full.sh

# Oracle / FreqParent / Golden follow-ups
bash scripts/experiments/run_react_simple-mem_oracle_main_suite.sh
bash scripts/experiments/run_react_simple-mem_freqparent_4nodes_main.sh
bash scripts/experiments/run_react_simple-mem_golden_4nodes_main.sh
```

---

## Summarizing Results

Each completed seed writes a `*_complete.txt` flag (`1` = solved, `0` = failed). Point the summarizer at the timestamped run root:

```bash
python scripts/experiments/summarize_completion_flags.py \
  output_dir/react_simple-mem/obs_CausalFreqParent_gpt-5-mini/4nodes_main/20260618-155735_dsl
```

Add `--json-out` / `--csv-out` for machine-readable output.

---

## Dataset

The `release/causalab_dataset/` directory contains **950 synthetic causal graph configurations** across 19 JSONL suites (3–7 nodes, standard, quadratic, hidden-variable, FreqParent, and Golden variants). It ships with a Croissant metadata file and SHA-256 checksums.

```python
import json
from pathlib import Path

configs = [json.loads(l) for l in Path("release/causalab_dataset/data/4nodes.jsonl").read_text().splitlines()]
print(len(configs), configs[0]["graph_id"])
# → 50  4nodes_0
```

See [`release/causalab_dataset/README.md`](release/causalab_dataset/README.md) for the full schema.

---

## Citation

If you use CausaLab in your research, please cite:

```bibtex
@article{zhang2025causalab,
  title     = {CausaLab: Interactive Causal Discovery Toward AI Scientists},
  author    = {Zhang, Dylan (Shizhuo) and Yang, Junlin and Song, Xiangchen and Dai, Qirun and Liu, Xiao and Chen, Yuen and Vashishtha, Aniket and Shi, Jing and Tan, Chenhao and Peng, Hao},
  journal   = {Advances in Neural Information Processing Systems, Datasets and Benchmarks Track},
  year      = {2025},
  url       = {https://arxiv.org/abs/2605.26029},
}
```

---

## Links

| Resource | URL |
|----------|-----|
| Paper | [arxiv.org/abs/2605.26029](https://arxiv.org/abs/2605.26029) |
| Blog | [dylanzsz.github.io/causalab](https://dylanzsz.github.io/causalab) |
| Personal website | [dylanzsz.github.io](https://dylanzsz.github.io) |
| Code | [github.com/DylanZSZ/CausaLab-Benchmark](https://github.com/DylanZSZ/CausaLab-Benchmark) |

---

## License

Apache 2.0 — see [LICENSE.txt](LICENSE.txt).

---

<div align="center">
<sub>Made with ☕ by <a href="https://dylanzsz.github.io">Dylan Zhang</a> and collaborators at UIUC, Tsinghua, CMU, U Chicago, and Adobe.</sub>
</div>
