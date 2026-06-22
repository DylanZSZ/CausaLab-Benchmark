# Causal Scaling Experiments

## 1. 这次新增了什么

- 一个可参数化的统一运行入口：`agents/recoma/run_react_simple-mem_experiment.sh`
- 四个专用 slurm：
  - `agents/recoma/run_react_simple-mem_scaling_observation.slurm`
  - `agents/recoma/run_react_simple-mem_scaling_intervention.slurm`
  - `agents/recoma/run_react_simple-mem_scaling_obs3_intervention.slurm`
  - `agents/recoma/run_react_simple-mem_causal_tool.slurm`
- 两个提交脚本：
  - `agents/recoma/submit_causal_scaling_suite.sh`
  - `agents/recoma/submit_causal_scaling_suite_subset.sh`
- 一个结果汇总与可视化脚本：
  - `agents/recoma/analyze_causal_experiments.py`

## 2. 最小框架改动

- `discoveryworld/TaskScorer.py`
  - 把原来硬编码的初始 `2` 个 observation 改成环境变量 `CAUSAL_INITIAL_OBSERVATIONS`
  - 默认值仍然是 `2`，所以原有逻辑兼容
- `discoveryworld/scenarios/reactor_lab.py`
  - 增加 `CAUSAL_GRAPH_BUDGET_OVERRIDE`
  - 这样不用改 graph jsonl 文件，就能直接覆盖 intervention budget
- `agents/recoma/react_controller.py`
  - 增加可选的 causal tool 在线推断
  - 默认关闭，不影响旧实验

## 3. Scaling 实验定义

### 实验 1A：纯 observation

- observation 数：`3, 6, 12, 24`
- intervention budget：`0`

### 实验 1B：纯 intervention

- initial observation 数：`0`
- intervention budget：`3, 6, 12, 24`

### 实验 1C：3 observation + intervention

- initial observation 数：`3`
- intervention budget：`3, 6, 12, 24`

### MAX_ENV_CALLS 规则

这里采用：

```text
MAX_ENV_CALLS = 38 + 2 * intervention_budget
```

原因：

- 当前 prompt 里的 initial observations 是任务描述中的先验观测，不消耗 environment steps
- 你要求“每多一次 intervention，MAX_ENV_CALLS +2”
- 现有 `2 observation + 12 intervention` 基线对应 `MAX_ENV_CALLS = 62`

因此：

- `0 intervention -> 38`
- `3 intervention -> 44`
- `6 intervention -> 50`
- `12 intervention -> 62`
- `24 intervention -> 86`

## 4. Causal Tool 实验

### 探索结论

我先检查了当前环境里的常见 Python causal discovery 依赖：

- `pgmpy`
- `causal-learn`
- `DoWhy`
- `numpy/pandas/sklearn`

当前环境里这些都不存在。并且这个 agent loop 需要的是：

- 在线更新，而不是离线一次性跑完
- 每一步都能给 agent 一个简洁摘要
- 尽量不引入重依赖

所以这里最后集成的不是打分式 heuristic，而是一个 deterministic candidate-graph filter：

- 输入：`past_data + experiment`
- 候选空间：当前 `CAUSAL_GRAPH_GROUP` 对应的全部 graph config
- 过滤规则：
  - observed property set 必须一致
  - 每条 intervention transition 都必须在“修改 target 的 base value”语义下被精确复现
- 输出：
  - 当前仍然可能的 graph 总数
  - 最多前 `20` 个候选 graph 的 `graph_id + edges`

它更适合你这里的设定，因为 graph family 本来就是离散枚举的，而且 intervention 语义不是标准 hard-do，而是“改 target 的 base 值后再沿图传播”。

### 运行设定

- 默认 causal tool 对比用：
  - baseline: `2 observation + 12 intervention + tool off`
  - tool: `2 observation + 12 intervention + tool on`

## 5. 如何运行

### 5.1 先准备环境变量

至少需要：

```bash
export OPENAI_API_KEY=...
export OPENAI_API_BASE=https://api.openai.com/v1
```

如果你想控制图集合：

```bash
export GRAPH_GROUP=5nodes.jsonl
```

### 5.2 跑整套 scaling + causal tool

```bash
bash agents/recoma/submit_causal_scaling_suite.sh --graph-group 4nodes.jsonl
```

可选参数：

- `--subset`：每组只跑一个 graph
- `--seeds N`
- `--batch-size N`
- `--model gpt-5-mini`

例如：

```bash
bash agents/recoma/submit_causal_scaling_suite.sh --graph-group 5nodes.jsonl --seeds 2 --batch-size 8
```

### 5.3 跑子集测试版

```bash
bash agents/recoma/submit_causal_scaling_suite_subset.sh --graph-group 4nodes.jsonl
```

这个脚本等价于主脚本加 `--subset`，即每组实验只取一个图，适合先测链路。

### 5.4 单独跑某一类 slurm

例如单独跑 observation-only 的 `12` observations：

```bash
sbatch --export=ALL,OUTPUT_TAG=scaling_observation_o12_i0,CAUSAL_GRAPH_GROUP=4nodes.jsonl,CAUSAL_INITIAL_OBSERVATIONS=12,INTERVENTION_BUDGET=0 agents/recoma/run_react_simple-mem_scaling_observation.slurm
```

例如单独跑 pure intervention 的 `24` interventions：

```bash
sbatch --export=ALL,OUTPUT_TAG=scaling_intervention_o0_i24,CAUSAL_GRAPH_GROUP=4nodes.jsonl,CAUSAL_INITIAL_OBSERVATIONS=0,INTERVENTION_BUDGET=24 agents/recoma/run_react_simple-mem_scaling_intervention.slurm
```

例如单独跑 causal tool：

```bash
sbatch --export=ALL,OUTPUT_TAG=causal_tool_o2_i12_enabled,CAUSAL_GRAPH_GROUP=4nodes.jsonl,CAUSAL_INITIAL_OBSERVATIONS=2,INTERVENTION_BUDGET=12,CAUSAL_TOOL_ENABLED=1 agents/recoma/run_react_simple-mem_causal_tool.slurm
```

## 6. 如何先做 dry-run

如果你只想检查参数展开和目录结构，不实际调用模型：

```bash
DRY_RUN=1 \
CAUSAL_GRAPH_GROUP=4nodes.jsonl \
GRAPH_LIMIT=1 \
CAUSAL_INITIAL_OBSERVATIONS=3 \
INTERVENTION_BUDGET=6 \
OUTPUT_TAG=dry_run_check \
bash agents/recoma/run_react_simple-mem_experiment.sh
```

## 7. 输出目录结构

每个 run 会在对应 seed 目录下写：

- `graph_config.json`
- `experiment_manifest.json`
- `source_config.json`
- `*_data.json`
- `*_tracking.jsonl`
- `recoma_execution.log`

4node scaling 默认根目录：

- `<repo>/output_dir/react_simple-mem/obs_Causal_gpt-5-mini/4nodes/scaling`

4node tool 默认根目录：

- `<repo>/output_dir/react_simple-mem/obs_Causal_gpt-5-mini/4nodes/tool`

每个 suite 根目录还会有：

- `suite_manifest.json`

## 8. 如何汇总结果和拿到可视化

### 8.1 运行汇总脚本

```bash
python agents/recoma/analyze_causal_experiments.py \
  output_dir/react_simple-mem \
  --output-dir output_dir/analysis/causal_experiments
```

### 8.2 输出文件

汇总脚本会生成：

- `aggregate_results.csv`
- `aggregate_results.json`
- `aggregate_results.md`
- `per_run_results.csv`
- `scaling_observation.svg`
- `intervention_scaling.svg`
- `causal_tool_comparison.svg`

### 8.3 怎么看图

- `*.svg` 可以直接用浏览器打开
- `aggregate_results.md` 可以直接贴进 paper 草稿或 README
- `aggregate_results.csv` 适合后续再做 LaTeX table

## 9. 对 paper 的实验补强建议

如果目标是让这篇 paper 更像 COLM oral 级别，我建议优先补下面几组：

### A. 预算效率与 Pareto 分析

- 不只报最终分数，还报：
  - score vs intervention budget
  - score vs total env calls
  - score vs token/cost
- 这能回答“增量预算到底换来多少有效因果发现”

### B. Tool / Prompt / Memory 分解 ablation

- baseline
- + validation prompt
- + causal tool
- + causal tool + validation
- 去掉 memory / 去掉 hypothesis / 去掉 experiment 字段

这会把“到底是 reasoning、memory、verification 还是 tool 在起作用”拆清楚。

### C. Structure recovery 指标补齐

- 不只报 task success
- 同时报：
  - edge precision / recall / F1
  - SHD 或 adjacency error
  - frequency parent set accuracy
  - coefficient error

这样可以把“结构错了”与“系数错了”分开。

### D. Stopping / calibration 分析

- agent 在第几次 intervention 提交
- 提交前 hypothesis 与 past_data 的一致率
- 提交时自评置信度 vs 实际正确率

这能把 paper 里现在的 over-confidence 失败模式做成一组更硬的实证。

### E. Intervention policy quality

- 干预变量覆盖率
- 重复干预率
- 对高价值变量的命中率
- 干预带来的平均信息增益代理指标

这能说明模型失败到底是“不会推理”还是“不会选实验”。

### F. Hidden variable robustness 曲线

- hidden strength 从弱到强
- affected nodes 从少到多
- 比较 baseline / validation / causal tool

这样 hidden variable 不再只是一个点，而是一条 robustness 曲线。

### G. Oracle 上界 / 下界

- oracle structure + model solve coefficients
- oracle coefficients + model decide structure
- oracle intervention planner + model summarize

这组实验最能定位瓶颈，非常值得补。

### H. Cross-graph generalization

- 同节点数不同 topology
- train/dev 式 prompt tuning 后测 unseen topology
- sparse vs dense graph 分层

这能回答 benchmark 是不是只在测某类图模板。

## 10. 我建议的优先级

如果只补 4 组，我建议先补：

1. observation/intervention scaling
2. causal tool ablation
3. stopping/calibration analysis
4. oracle bottleneck ablation

这四组最容易形成完整故事线：

- 数据预算不是唯一瓶颈
- 纯靠模型内隐推理不够
- 校验/工具能缓解过早收敛
- 真正瓶颈在 experiment design 还是 structure/parameter recovery，可以被明确拆开
