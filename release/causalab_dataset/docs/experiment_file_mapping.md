# Experiment To File Mapping

This document maps the active experiments in `causal_game_paper/new_paper` to the JSONL files included in this dataset release.

## Included Files

All files are under `data/` in this release and under `causal_graph_configs/` in the source tree.

| File | Records | Paper role |
| --- | ---: | --- |
| `3nodes.jsonl` | 50 | Main 3-node suite |
| `4nodes.jsonl` | 50 | Main 4-node suite; 4-node scaling; baseline for multiple ablations |
| `5nodes.jsonl` | 50 | Main 5-node suite; over-confidence diagnostics |
| `6nodes.jsonl` | 50 | Main 6-node suite; 6-node scaling |
| `7nodes.jsonl` | 50 | Main 7-node suite |
| `4nodes_quad_hard.jsonl` | 50 | Hard-quadratic mechanism ablation |
| `4nodes_hidden_n1.jsonl` | 50 | Hidden-noise count sweep, 1 affected node |
| `4nodes_hidden_n2.jsonl` | 50 | Hidden-noise count sweep, 2 affected nodes |
| `4nodes_hidden_n3.jsonl` | 50 | Hidden-noise count sweep, 3 affected nodes |
| `4nodes_hidden_vrange_pm0p5.jsonl` | 50 | Hidden-noise range sweep, +/-0.5 |
| `4nodes_hidden_vrange_pm5.jsonl` | 50 | Hidden-noise range sweep, +/-5 |
| `4nodes_hidden_vrange_pm50.jsonl` | 50 | Hidden-noise range sweep, +/-50 |
| `4nodes_hidden_freqnode_n1.jsonl` | 50 | Hidden-freqnode sweep, 1 affected node including frequency |
| `4nodes_hidden_freqnode_n2.jsonl` | 50 | Hidden-freqnode sweep, 2 affected nodes including frequency |
| `4nodes_hidden_freqnode_n3.jsonl` | 50 | Hidden-freqnode sweep, 3 affected nodes including frequency |
| `4nodes_freqparent.jsonl` | 50 | 4-node FreqParent follow-up |
| `6nodes_freqparent.jsonl` | 50 | 6-node FreqParent follow-up |
| `4nodes_golden.jsonl` | 50 | 4-node Golden low-MEC trace follow-up |
| `6nodes_golden.jsonl` | 50 | 6-node Golden low-MEC trace follow-up |

Total: 19 JSONL files and 950 graph configurations.

## Active Paper Mapping

| Paper item | Experiment | Files |
| --- | --- | --- |
| `fig:model_comparison`, `fig:model_metric_support`, `tab:main_model_metrics` | GPT-5-mini and GPT-5.2-high main model comparison on 3--7 nodes | `3nodes.jsonl`, `4nodes.jsonl`, `5nodes.jsonl`, `6nodes.jsonl`, `7nodes.jsonl` |
| `fig:disambiguation_gap_summary`, `fig:scaling_curves`, `fig:reeval_scaling`, scaling appendix tables | Observation/intervention scaling on 4-node and 6-node suites | `4nodes.jsonl`, `6nodes.jsonl` |
| `fig:golden_followup_metrics`, `tab:golden_followup_metrics` | Static low-MEC intervention traces compared with main baselines | `4nodes.jsonl`, `6nodes.jsonl`, `4nodes_golden.jsonl`, `6nodes_golden.jsonl` |
| `fig:linear_vs_quad_4nodes`, `tab:linear_quad_metrics` | Matched linear vs hard-quadratic 4-node mechanisms | `4nodes.jsonl`, `4nodes_quad_hard.jsonl` |
| `fig:overconfidence_diagnostics`, `fig:false_positive_signals` | Early stopping, hypothesis-data consistency, verification-step diagnostics | `4nodes.jsonl`, `5nodes.jsonl` |
| `fig:hidden_variables`, `tab:hidden_metrics` | Hidden-noise count/range/freqnode robustness | `4nodes.jsonl`, `4nodes_hidden_n1.jsonl`, `4nodes_hidden_n2.jsonl`, `4nodes_hidden_n3.jsonl`, `4nodes_hidden_vrange_pm0p5.jsonl`, `4nodes_hidden_vrange_pm5.jsonl`, `4nodes_hidden_vrange_pm50.jsonl`, `4nodes_hidden_freqnode_n1.jsonl`, `4nodes_hidden_freqnode_n2.jsonl`, `4nodes_hidden_freqnode_n3.jsonl` |
| `fig:freqparent_followup_metrics`, `tab:freqparent_followup_metrics` | Frequency-as-parent follow-up | `4nodes.jsonl`, `6nodes.jsonl`, `4nodes_freqparent.jsonl`, `6nodes_freqparent.jsonl` |

## Exclusions

Single-graph `.json` example files, copy/backup/tmp/smoke files, missing-fill fragments, and commented-out Oracle materials are excluded because they are not active-paper graph suites.
