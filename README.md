<div align="center">

<br/>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://dylanzsz.github.io/causalab/figures/episode_overview.png">
  <img src="https://dylanzsz.github.io/causalab/figures/episode_overview.png" alt="CausaLab" width="800"/>
</picture>

<br/><br/>

# CausaLab

**Can an LLM agent discover a causal law the way a scientist would — by experimenting?**

<br/>

[![Paper](https://img.shields.io/badge/arXiv-2605.26029-b31b1b?style=for-the-badge&logo=arxiv)](https://arxiv.org/abs/2605.26029)&nbsp;
[![Blog](https://img.shields.io/badge/Blog-dylanzsz.github.io%2Fcausalab-4285F4?style=for-the-badge&logo=googlechrome&logoColor=white)](https://dylanzsz.github.io/causalab)&nbsp;
[![Website](https://img.shields.io/badge/Author-dylanzsz.github.io-0a0a0a?style=for-the-badge&logo=githubpages)](https://dylanzsz.github.io)

[![License](https://img.shields.io/badge/License-Apache%202.0-blue?style=flat-square)](LICENSE.txt)&nbsp;
[![Python](https://img.shields.io/badge/Python-3.10-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)&nbsp;
[![Version](https://img.shields.io/badge/Version-0.0.2%20early%20release-orange?style=flat-square)](https://github.com/DylanZSZ/CausaLab-Benchmark/releases)&nbsp;
[![GitHub Stars](https://img.shields.io/github/stars/DylanZSZ/CausaLab-Benchmark?style=flat-square)](https://github.com/DylanZSZ/CausaLab-Benchmark/stargazers)

<br/>

> **⚠️ v0.0.2 — First Public Release.** Interfaces and dataset formats may change.
> Please [open an issue](https://github.com/DylanZSZ/CausaLab-Benchmark/issues) if you encounter problems.

<br/>

</div>

---

<div align="center">

### The core question

</div>

A real scientist doesn't look up how the world works. They **intervene** on it, watch what changes, and revise a theory until it transfers to a case they've never seen. Most LLM benchmarks test *retrieval* — can the model recall a known fact? **CausaLab tests discovery**: can an agent run experiments, recover the hidden causal mechanism, and apply it to a novel case from scratch?

Each episode hides a freshly sampled structural causal model (SCM) inside a synthetic crystal reactor. The agent manipulates variables, observes outcomes, and must both **predict** a held-out measurement *and* **recover the causal graph** that explains it. You can't win by reciting memorized facts.

---

<div align="center">

### Three findings

</div>

<table>
<tr>
<td width="33%" align="center">

**🎯 Prediction ≠ Understanding**

`GPT-5.2-high` reaches **92% task accuracy** on 6-node graphs — but only **0.47 all-edge F₁**.

Right number. Wrong graph.

</td>
<td width="33%" align="center">

**🔬 The act of experimenting matters**

Handing the agent *perfect* pre-collected data ("Golden") boosts prediction but **not** mechanism recovery.

The *choice* of experiment carries structural signal.

</td>
<td width="33%" align="center">

**⏱️ Agents stop too soon**

Win or lose, runs leave ~half their intervention budget unused.

One "check theory vs. evidence" step lifts 4-node accuracy: **48% → 60%**.

</td>
</tr>
</table>

---

## Contents

- [How It Works](#how-it-works)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Running Experiments](#running-experiments)
- [Dataset](#dataset)
- [Citation](#citation)
- [Authors](#authors)

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  Hidden SCM  →  prior records  →  agent observes               │
│                                                                  │
│  Agent intervenes on manipulator crystal                        │
│  ↓  (repeat until budget exhausted)                             │
│  Agent emits DSL causal hypothesis at each step                 │
│  ↓                                                               │
│  Final prediction: reactor crystal's hidden frequency           │
│                                                                  │
│  Scoring: prediction accuracy  +  graph/equation F₁             │
└─────────────────────────────────────────────────────────────────┘
```

A **hidden SCM** governs both a *manipulator* crystal (the agent can poke it) and a *reactor* crystal (held out). The agent must discover the shared causal law through experimentation, then transfer it. We score **two things**: whether the agent got the right answer, and whether it recovered the right mechanism.

<details>
<summary><b>Repository structure</b></summary>

```
CausaLab-Benchmark/
│
├── discoveryworld/              # Reactor Lab environment (DiscoveryWorld fork)
│   └── scenarios/reactor_lab.py #   ← the CausaLab task definition
│
├── agents/recoma/               # ReAct / Recoma agent
│   ├── run_recoma.py            #   ← main agent runner
│   ├── react_controller.py      #   ← controller loop
│   └── prompts/                 #   ← DSL & non-DSL prompt variants
│
├── scripts/
│   ├── experiments/             # Launch scripts, summarizer, monitor
│   ├── vis_backend/             # Trajectory visualization server
│   └── vis_frontend/            # Visualization UI
│
├── causalab_reeval/             # ReEval scoring module
│
├── release/causalab_dataset/    # Synthetic graph configs — 950 records
│   └── data/                    #   ← 19 JSONL suites, 3–7 nodes
│
└── examples/sample_runs/        # Bundled sample trajectory for offline checks
```

</details>

---

## Installation

> Requires **Python 3.10**

```bash
conda create -n causalab python=3.10 -y
conda activate causalab

pip install --upgrade pip
pip install --use-pep517 -r agents/requirements.txt
pip install -e .
```

For API-backed runs:

```bash
export OPENAI_API_KEY=sk-...
export OPENAI_API_BASE=https://api.openai.com/v1   # optional override
```

Offline smoke checks do not require an API key.

---

## Quick Start

**1 — Dry-run (no API calls)**

```bash
SKIP_CONDA_ACTIVATE=1 DRY_RUN=1 GRAPH_LIMIT=1 \
  bash scripts/experiments/run_react_simple-mem_freqparent_4nodes_main.sh
```

**2 — ReEval on the bundled sample**

```bash
python -m causalab_reeval.run_lightweight_reeval \
  --source-only --limit 1 \
  --output-dir output_dir/reeval_sample \
  examples/sample_runs/react_simple-mem
```

**3 — Trajectory visualization**

```bash
python scripts/vis_backend/visualization_server.py
# → open http://127.0.0.1:5001
```

---

## Running Experiments

All scripts live in `scripts/experiments/` and resolve paths from the repo root. Outputs go to `output_dir/`.

| Variable | Effect |
|---|---|
| `DRY_RUN=1` | Print planned jobs, no API calls |
| `GRAPH_LIMIT=N` | Restrict to first *N* graph configs |
| `SEEDS_PER_GRAPH=N` | Seeds per graph |
| `BATCH_SIZE=N` | Concurrent local jobs |
| `SKIP_CONDA_ACTIVATE=1` | Use current Python environment |

<details>
<summary><b>Experiment scripts reference</b></summary>

```bash
# ── Main runs ─────────────────────────────────────────────────────
bash scripts/experiments/run_react_simple-mem_parallel.sh          # GPT-5-mini 4/6-node
bash scripts/experiments/run_react_simple-mem_scaling_gpt52.sh     # GPT-5.2 scaling

# ── Scaling suites ────────────────────────────────────────────────
bash scripts/experiments/run_react_simple-mem_scaling_suite.sh
bash scripts/experiments/run_react_simple-mem_scaling_suite_6nodes.sh

# ── Formula variants ──────────────────────────────────────────────
bash scripts/experiments/run_react_simple-mem_4nodes_quad.sh
bash scripts/experiments/run_react_simple-mem_4nodes_quad_hard.sh

# ── Hidden-variable suites ────────────────────────────────────────
bash scripts/experiments/run_hidden_variants_full.sh
bash scripts/experiments/run_hidden_frequency_node_priority_full.sh

# ── Oracle / FreqParent / Golden follow-ups ───────────────────────
bash scripts/experiments/run_react_simple-mem_oracle_main_suite.sh
bash scripts/experiments/run_react_simple-mem_freqparent_4nodes_main.sh
bash scripts/experiments/run_react_simple-mem_golden_4nodes_main.sh
```

</details>

**Summarizing results**

```bash
python scripts/experiments/summarize_completion_flags.py \
  output_dir/react_simple-mem/obs_CausalFreqParent_gpt-5-mini/4nodes_main/<run_id> \
  --json-out output_dir/summary.json \
  --csv-out  output_dir/flags.csv
```

---

## Dataset

`release/causalab_dataset/` contains **950 synthetic causal graph configurations** across **19 JSONL suites** (3–7 nodes; standard, quadratic, hidden-variable, FreqParent, and Golden variants). Ships with Croissant metadata and SHA-256 checksums.

```python
import json
from pathlib import Path

configs = [
    json.loads(line)
    for line in Path("release/causalab_dataset/data/4nodes.jsonl").read_text().splitlines()
]
print(len(configs), configs[0]["graph_id"])
# → 50  4nodes_0
```

See [`release/causalab_dataset/README.md`](release/causalab_dataset/README.md) for the full schema and field reference.

---

## Citation

```bibtex
@article{zhang2025causalab,
  title     = {CausaLab: Interactive Causal Discovery Toward AI Scientists},
  author    = {Zhang, Dylan (Shizhuo) and Yang, Junlin and Song, Xiangchen
               and Dai, Qirun and Liu, Xiao and Chen, Yuen and Vashishtha, Aniket
               and Shi, Jing and Tan, Chenhao and Peng, Hao},
  journal   = {arXiv preprint arXiv:2605.26029},
  year      = {2025},
  url       = {https://arxiv.org/abs/2605.26029},
}
```

---

## Authors

**Dylan Zhang** · [dylanzsz.github.io](https://dylanzsz.github.io) · [@dylan_works_](https://x.com/dylan_works_) · [shizhuo2@illinois.edu](mailto:shizhuo2@illinois.edu)

With **Junlin Yang, Xiangchen Song, Qirun Dai, Xiao Liu, Yuen Chen, Aniket Vashishtha, Jing Shi, Chenhao Tan,** and **Hao Peng** — across UIUC, Tsinghua, CMU, University of Chicago, and Adobe.

<br/>

<div align="center">

[📄 Paper](https://arxiv.org/abs/2605.26029) &nbsp;·&nbsp;
[📝 Blog](https://dylanzsz.github.io/causalab) &nbsp;·&nbsp;
[🌐 Website](https://dylanzsz.github.io) &nbsp;·&nbsp;
[💻 Code](https://github.com/DylanZSZ/CausaLab-Benchmark)

<sub>Apache 2.0 — © 2026 the CausaLab authors</sub>

</div>
