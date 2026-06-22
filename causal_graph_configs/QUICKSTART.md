# Quick Start Guide - Causal Graph Configuration System

## 30-Second Start

```bash
# 1. Choose a causal graph structure
export CAUSAL_GRAPH_ID="chain_3_nodes"

# 2. Run experiment
sbatch agents/recoma/run_single_causal_graph.slurm
```

That's it! Your agent will now explore the chain_3_nodes causal structure.

## Available Graphs

| Graph ID | Nodes | Structure | Complexity |
|----------|-------|-----------|------------|
| `chain_2_nodes` | 2 | A→B | Simple |
| `chain_3_nodes` | 3 | A→B→C | Easy |
| `fork_3_nodes` | 3 | A→B, A→C | Easy |
| `collider_3_nodes` | 3 | A→C, B→C | Medium |
| `chain_4_nodes` | 4 | A→B→C→D | Medium |
| `diamond_4_nodes` | 4 | A→B/C→D | Hard |
| `fork_with_base_4_nodes` | 4 | Fork + Hybrid | Hard |
| `complex_5_nodes` | 5 | Complex | Very Hard |

## Testing Multiple Graphs

```bash
# Edit run_batch_causal_graphs.slurm to select which graphs to test
sbatch agents/recoma/run_batch_causal_graphs.slurm
```

## Creating Your Own Graph

### Step 1: Create Config File

Create `causal_graph_configs/my_graph.json`:

```json
{
  "graph_id": "my_graph",
  "description": "My custom causal structure",
  "nodes": {
    "A": {
      "is_controllable": true,
      "property_name": "temperatureC",
      "base_value": {"type": "uniform", "min": 10.0, "max": 50.0}
    },
    "B": {
      "is_controllable": false,
      "property_name": "resonanceFreq",
      "computation": "1000.0 + 50.0 * A"
    }
  },
  "edges": [
    {"from": "A", "to": "B"}
  ],
  "params": {}
}
```

### Step 2: Test It

```bash
python test_causal_configs.py causal_graph_configs/my_graph.json
```

### Step 3: Run Experiment

```bash
export CAUSAL_GRAPH_ID="my_graph"
sbatch agents/recoma/run_single_causal_graph.slurm
```

## Node Types Cheat Sheet

### Pure Controllable (Agent can set directly)
```json
"T": {
  "is_controllable": true,
  "property_name": "temperatureC",
  "base_value": {"type": "uniform", "min": 10.0, "max": 50.0}
}
```

### Pure Derived (Computed from parents)
```json
"F": {
  "is_controllable": false,
  "property_name": "resonanceFreq",
  "computation": "1000.0 + 50.0 * T"
}
```

### Hybrid (Has base + parent influence)
```json
"M": {
  "is_controllable": true,
  "property_name": "moisture",
  "computation": "base + 0.5 * T",
  "base_value": {"type": "uniform", "min": 5.0, "max": 15.0}
}
```

**Key**: In hybrid nodes, `base` in computation refers to the node's base_value!

## Property Names

Use these for `property_name` field:
- `temperatureC` - Temperature (°C)
- `moisture` - Moisture level
- `moistureBase` - Base moisture (for M_0)
- `density` - Density (g/cm³)
- `quantumSize` - Quantum size (nm)
- `resonanceFreq` - Resonance frequency (Hz)

## Computation Expression Examples

```json
// Simple linear
"computation": "1000.0 + 50.0 * A"

// With base value (hybrid node)
"computation": "base + 0.5 * A"

// Multiple parents
"computation": "500.0 + 30.0 * A + 10.0 * B"

// With parameters
"computation": "F_0 + k_f * (T - T_ref)"
// params: {"F_0": 1000.0, "k_f": 50.0, "T_ref": 20.0}

// Complex expression
"computation": "(A + B) / 2"
```

## Common Issues

### "Config file not found"
- Check that JSON file is in `causal_graph_configs/` directory
- Check that `graph_id` matches filename (without .json)

### "Error evaluating computation"
- Check that all parent nodes are listed in `edges`
- Check that all parameter names are defined in `params`
- For hybrid nodes, use `base` (not the node name) in computation

### "Properties out of range"
- Adjust coefficients to keep values reasonable
- Temperature: typically 10-50°C
- Moisture: typically 5-30
- Density: typically 10-70 g/cm³
- Frequency: typically 500-3000 Hz

## Output Location

Results are saved to:
```
output_dir/causal_{GRAPH_ID}_{MODEL}_{HINT_LEVEL}_{TIMESTAMP}/seed_{1-5}/
```

Check:
- Console logs for causal graph loading messages
- `*_data.json` files for crystal properties and causal structure
- Agent trajectories for causal discovery attempts

## Next Steps

1. **Read detailed docs**: See `README.md` for full documentation
2. **Understand implementation**: See `IMPLEMENTATION_SUMMARY.md`
3. **Learn SLURM usage**: See `USAGE.md`
4. **Create complex graphs**: See existing JSON files for examples

## Support

If something doesn't work:
1. Test config with: `python test_causal_configs.py your_config.json`
2. Check console output for `[mkReactorLabCausal]` messages
3. Verify environment variables are set: `echo $CAUSAL_GRAPH_ID`
4. Check SLURM logs in `slurm_log/` directory




