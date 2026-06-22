# Using Causal Graph Configurations with SLURM

## Quick Start

The easiest way to use different causal graph structures is through environment variables in your SLURM script.

### Method 1: Use a Graph ID (Recommended)

Set the `CAUSAL_GRAPH_ID` environment variable to use one of the pre-defined configurations:

```bash
# In your SLURM script (e.g., run_react_simple-mem_parallel.slurm)
export CAUSAL_GRAPH_ID="chain_3_nodes"
```

Available graph IDs:
- `chain_2_nodes` - Simple A→B chain (2 nodes)
- `chain_3_nodes` - A→B→C sequential chain (3 nodes)
- `chain_4_nodes` - A→B→C→D long chain (4 nodes)
- `fork_3_nodes` - A→B, A→C fork structure (3 nodes)
- `fork_with_base_4_nodes` - Fork with controllable base (4 nodes)
- `collider_3_nodes` - A→C, B→C collider (3 nodes)
- `multi_root_collider` - A→D, B→D, C→D multiple causes (4 nodes)
- `diamond_4_nodes` - Diamond structure with mediation (4 nodes)
- `complex_5_nodes` - Complex 5-node graph

### Method 2: Use a Custom Configuration File

If you have a custom configuration file, set the full path:

```bash
# In your SLURM script
export CAUSAL_GRAPH_CONFIG="/path/to/your/custom_config.json"
```

### Method 3: Legacy Environment Variables (Backward Compatible)

For the original T→F, T→M graph, you can still use the legacy variables:

```bash
export CAUSAL_T_REF=20.0
export CAUSAL_F_0=1000.0
export CAUSAL_K_F=50.0
export CAUSAL_K_D=0.5
```

## Example SLURM Script Modifications

### Single Causal Graph Experiment

```bash
#!/bin/bash
#SBATCH --job-name="causal_chain3"
# ... other SLURM parameters ...

# Set the causal graph
export CAUSAL_GRAPH_ID="chain_3_nodes"

# Run experiments
for ENV_SEED in 1 2 3 4 5; do
  python agents/recoma/run_recoma.py \
    --output_dir "$SUBDIR" \
    --config agents/recoma/configs/react-simple-memory.jsonnet \
    --debug
done
```

### Batch Testing Multiple Graphs

```bash
#!/bin/bash
# Test multiple causal structures

GRAPH_IDS=("chain_2_nodes" "chain_3_nodes" "fork_3_nodes" "collider_3_nodes" "diamond_4_nodes")

for GRAPH_ID in "${GRAPH_IDS[@]}"; do
  export CAUSAL_GRAPH_ID="$GRAPH_ID"
  
  TS=$(date +%Y%m%d-%H%M)
  ROOT_DIR="output_dir/causal_graphs/${GRAPH_ID}_${TS}"
  mkdir -p "$ROOT_DIR"
  
  echo "Running experiments with graph: $GRAPH_ID"
  
  for ENV_SEED in 1 2 3 4 5; do
    SUBDIR="$ROOT_DIR/seed_$ENV_SEED"
    mkdir -p "$SUBDIR"
    
    python agents/recoma/run_recoma.py \
      --output_dir "$SUBDIR" \
      --config agents/recoma/configs/react-simple-memory.jsonnet \
      --debug
  done
done
```

### Array Job for Parallel Graph Testing

```bash
#!/bin/bash
#SBATCH --array=0-8  # 9 different graphs

# Define graph IDs array
GRAPH_IDS=("chain_2_nodes" "chain_3_nodes" "chain_4_nodes" \
           "fork_3_nodes" "fork_with_base_4_nodes" \
           "collider_3_nodes" "multi_root_collider" \
           "diamond_4_nodes" "complex_5_nodes")

# Get graph ID for this array task
GRAPH_ID="${GRAPH_IDS[$SLURM_ARRAY_TASK_ID]}"
export CAUSAL_GRAPH_ID="$GRAPH_ID"

echo "Testing causal graph: $GRAPH_ID"

# Run experiments for this graph
# ... rest of your experiment code ...
```

## Verification

To verify which causal graph is being used, check the console output:

```
[mkReactorLabCausal] Loaded causal graph by ID: chain_3_nodes
[mkReactorLabCausal] Description: 3-node chain: A -> B -> C (e.g., Temperature -> Moisture -> Resonance)
```

Or check the scoring info in the output JSON files:

```json
{
  "causalGraphSource": "graph_id:chain_3_nodes",
  "causalRelationships": [
    "A depends on: ",
    "B depends on: A",
    "C depends on: B"
  ]
}
```

## Creating New Configurations

To create a new causal graph configuration:

1. Create a JSON file in `causal_graph_configs/`
2. Follow the format in the existing config files
3. Use the graph_id as the filename (e.g., `my_custom_graph.json`)
4. Set `export CAUSAL_GRAPH_ID="my_custom_graph"` in your SLURM script

Example custom configuration:

```json
{
  "graph_id": "my_custom_graph",
  "description": "Custom causal structure for my experiment",
  "nodes": {
    "T": {
      "is_controllable": true,
      "property_name": "temperatureC",
      "base_value": {
        "type": "uniform",
        "min": 15.0,
        "max": 45.0
      }
    },
    "F": {
      "is_controllable": false,
      "property_name": "resonanceFreq",
      "computation": "base + coeff * T"
    }
  },
  "edges": [
    {"from": "T", "to": "F"}
  ],
  "params": {
    "base": 1000.0,
    "coeff": 50.0
  }
}
```

## Troubleshooting

**Graph not loading:**
- Check that the graph ID matches the filename (without .json extension)
- Verify the JSON syntax is correct
- Check console output for error messages

**Properties not being manipulated:**
- Ensure the PropertyManipulator is configured for your graph structure
- Check that controllable nodes are properly marked in the config
- Verify property names match available crystal attributes

**Unexpected behavior:**
- Review the causal graph description in console output
- Check the criticalHypotheses in scoring output
- Verify computation expressions are correct




