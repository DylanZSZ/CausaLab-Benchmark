---
license: apache-2.0
pretty_name: CausaLab Causal Graph Configuration Dataset
task_categories:
- text-classification
language:
- en
configs:
- config_name: 3nodes
  data_files:
  - split: eval
    path: data/3nodes.jsonl
- config_name: 4nodes
  data_files:
  - split: eval
    path: data/4nodes.jsonl
- config_name: 5nodes
  data_files:
  - split: eval
    path: data/5nodes.jsonl
- config_name: 6nodes
  data_files:
  - split: eval
    path: data/6nodes.jsonl
- config_name: 7nodes
  data_files:
  - split: eval
    path: data/7nodes.jsonl
- config_name: 4nodes_quad_hard
  data_files:
  - split: eval
    path: data/4nodes_quad_hard.jsonl
- config_name: 4nodes_hidden_n1
  data_files:
  - split: eval
    path: data/4nodes_hidden_n1.jsonl
- config_name: 4nodes_hidden_n2
  data_files:
  - split: eval
    path: data/4nodes_hidden_n2.jsonl
- config_name: 4nodes_hidden_n3
  data_files:
  - split: eval
    path: data/4nodes_hidden_n3.jsonl
- config_name: 4nodes_hidden_vrange_pm0p5
  data_files:
  - split: eval
    path: data/4nodes_hidden_vrange_pm0p5.jsonl
- config_name: 4nodes_hidden_vrange_pm5
  data_files:
  - split: eval
    path: data/4nodes_hidden_vrange_pm5.jsonl
- config_name: 4nodes_hidden_vrange_pm50
  data_files:
  - split: eval
    path: data/4nodes_hidden_vrange_pm50.jsonl
- config_name: 4nodes_hidden_freqnode_n1
  data_files:
  - split: eval
    path: data/4nodes_hidden_freqnode_n1.jsonl
- config_name: 4nodes_hidden_freqnode_n2
  data_files:
  - split: eval
    path: data/4nodes_hidden_freqnode_n2.jsonl
- config_name: 4nodes_hidden_freqnode_n3
  data_files:
  - split: eval
    path: data/4nodes_hidden_freqnode_n3.jsonl
- config_name: 4nodes_freqparent
  data_files:
  - split: eval
    path: data/4nodes_freqparent.jsonl
- config_name: 6nodes_freqparent
  data_files:
  - split: eval
    path: data/6nodes_freqparent.jsonl
- config_name: 4nodes_golden
  data_files:
  - split: eval
    path: data/4nodes_golden.jsonl
- config_name: 6nodes_golden
  data_files:
  - split: eval
    path: data/6nodes_golden.jsonl
---

# CausaLab Causal Graph Configuration Dataset

Public release accompanying the CausaLab paper — arXiv:2605.26029.

This package contains the synthetic causal graph configuration suites used by the active experiments in the CausaLab paper. Each JSONL file contains 50 graph configurations, one JSON object per line.

## Contents

```text
.
├── data/                         # 19 JSONL graph-suite files, 950 total records
├── docs/
│   ├── experiment_file_mapping.md
├── manifest.json                 # file purposes, record counts, top-level fields, checksums
├── croissant.json                # Croissant metadata draft with Responsible AI fields
├── checksums.sha256
└── LICENSE
```

## Schema

Every JSONL record is one causal graph task. Common fields are:

- `graph_id`: graph/task identifier.
- `description`: text description of graph size or suite variant.
- `nodes`: variable definitions, including controllability, observability, display names, base-value generators, and optional structural equations.
- `edges`: directed causal edges as `from`/`to` pairs.
- `params`: numeric coefficients and constants for structural equations.
- `budget`: default intervention budget.

Some suites add optional fields:

- `hidden_variable`: hidden perturbation setup for hidden-noise suites.
- `bootstrap_past_data`: static intervention traces for Golden suites.
- `frequency_can_be_parent`: marker for FreqParent suites.
- `quadratic_metadata`: fixed probes and metadata for hard-quadratic suites.

## Loading Example

```python
import json
from pathlib import Path

configs = [
    json.loads(line)
    for line in Path("data/4nodes.jsonl").read_text().splitlines()
]
print(len(configs), configs[0]["graph_id"])
```

## Scope

This release intentionally includes only the files used by active paper experiments. It excludes toy single-graph JSON files, smoke tests, backup/copy/tmp files, missing-fill fragments, and commented-out legacy Oracle materials. See `docs/experiment_file_mapping.md` for the experiment-to-file mapping.

## Responsible AI And Privacy

The data are fully synthetic graph configurations. They contain no personal data, no human subjects data, and no author, institution, account, or local path metadata. The benchmark is intended for controlled evaluation of causal reasoning, intervention planning, and target-frequency prediction in synthetic environments; results should not be treated as real-world scientific discovery claims.
