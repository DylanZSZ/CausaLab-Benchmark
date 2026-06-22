# Causal Graph Configuration System - Implementation Summary

## Overview

This document summarizes the configuration-based causal graph system for the DiscoveryWorld Reactor Lab Causal scenario. The system allows you to define arbitrary causal structures through JSON configuration files, without modifying code.

## Key Features

### 1. Three Types of Nodes

The system supports flexible node types that can represent different causal relationships:

#### Pure Controllable Nodes
- **Definition**: Variables that can be directly manipulated by agents
- **Configuration**: `"is_controllable": true`, has `"base_value"`, no `"computation"`
- **Example**: Temperature that can be set to any value
- **Formula**: `value = base_value`

```json
"T": {
  "is_controllable": true,
  "property_name": "temperatureC",
  "base_value": {"type": "uniform", "min": 10.0, "max": 50.0}
}
```

#### Pure Derived Nodes
- **Definition**: Variables computed entirely from parent nodes
- **Configuration**: `"is_controllable": false`, has `"computation"`, no `"base_value"`
- **Example**: Resonance frequency determined by temperature
- **Formula**: `value = f(parents, params)`

```json
"F": {
  "is_controllable": false,
  "property_name": "resonanceFreq",
  "computation": "F_0 + k_f * T"
}
```

#### Hybrid Nodes (New Feature)
- **Definition**: Variables with a manipulable baseline that are also influenced by parent nodes
- **Configuration**: `"is_controllable": true`, has both `"base_value"` AND `"computation"`
- **Example**: Moisture that has a base level but is affected by temperature
- **Formula**: `value = f(base, parents, params)` where `base` is the manipulable base_value
- **Key insight**: Agents manipulate the `base` parameter, but observe the computed `value`

```json
"M": {
  "is_controllable": true,
  "property_name": "moisture",
  "computation": "base + k_d * T",
  "base_value": {"type": "uniform", "min": 5.0, "max": 15.0}
}
```

**Why Hybrid Nodes Are Important:**
- They represent real-world scenarios where a quantity has both an inherent baseline and external influences
- Example: Moisture content = base moisture + dehydration due to temperature
- Allows studying confounding effects and intervention vs. observation
- Agents must discover that manipulating the base only changes part of the final value

### 2. Configuration File Structure

```json
{
  "graph_id": "unique_identifier",
  "description": "Human-readable description",
  "nodes": {
    "node_name": {
      "is_controllable": true/false,
      "property_name": "crystal_attribute_name",
      "base_value": {...},      // For controllable nodes
      "computation": "expression" // For derived/hybrid nodes
    }
  },
  "edges": [
    {"from": "parent", "to": "child"}
  ],
  "params": {
    "param_name": value
  }
}
```

### 3. Environment Variable Configuration

The system reads configuration from environment variables (no code changes needed):

```bash
# Option 1: Use a graph ID from configs directory
export CAUSAL_GRAPH_ID="chain_3_nodes"

# Option 2: Use a full path to custom config
export CAUSAL_GRAPH_CONFIG="/path/to/config.json"

# Option 3: Legacy env vars (for backward compatibility)
export CAUSAL_T_REF=20.0
export CAUSAL_F_0=1000.0
# ... etc
```

**Priority order:**
1. `CAUSAL_GRAPH_CONFIG` (full path)
2. `CAUSAL_GRAPH_ID` (graph from configs directory)
3. Legacy environment variables
4. Config parameter (programmatic)
5. Seed-based generation
6. Random generation (default)

## Implementation Details

### Code Changes in reactor_lab.py

#### 1. Enhanced CausalGraph.compute_values()
- Now supports hybrid nodes with both base_value and computation
- Generates base_value first, makes it available as `base` in computation
- Stores base_values separately in `_last_base_values` for PropertyManipulator access

```python
def compute_node(node_name):
    # Generate base value if controllable
    base_value = None
    if node.is_controllable:
        base_value = node.base_value(rng)
        base_values[node_name] = base_value
    
    # If no computation, use base value directly
    if node.computation_fn is None:
        return base_value
    
    # Compute from parents and/or base value
    parent_values = {...}
    if base_value is not None:
        parent_values['base'] = base_value  # Available in computation!
    
    return node.computation_fn(parent_values, params)
```

#### 2. Updated load_causal_graph_from_config()
- Checks for both `has_base_value` and `has_computation`
- Creates nodes with appropriate configuration for all three types
- Validates that non-controllable nodes have computation

#### 3. Environment Variable Integration in mkReactorLabCausal()
- Checks `CAUSAL_GRAPH_CONFIG` environment variable first
- Falls back to `CAUSAL_GRAPH_ID` (looks in default directory)
- Falls back to legacy configuration system
- Logs which configuration source was used

#### 4. Dynamic Critical Hypotheses Generation
- Generates hypotheses based on graph structure
- Lists all causal edges
- Lists controllable vs. derived variables
- Generates appropriate scoring questions

### PropertyManipulator Integration

The PropertyManipulator needs to access base values for hybrid nodes:
- Hybrid nodes store their base_value in `graph._last_base_values`
- When agent manipulates a hybrid node, they change the base_value
- The final observed value is recomputed using the new base_value

## Usage Examples

### Example 1: Simple Chain (A → B → C)

```json
{
  "graph_id": "chain_3_nodes",
  "nodes": {
    "A": {
      "is_controllable": true,
      "property_name": "temperatureC",
      "base_value": {"type": "uniform", "min": 10.0, "max": 50.0}
    },
    "B": {
      "is_controllable": false,
      "property_name": "moisture",
      "computation": "base_b + coeff_ab * A"
    },
    "C": {
      "is_controllable": false,
      "property_name": "resonanceFreq",
      "computation": "base_c + coeff_bc * B"
    }
  },
  "edges": [
    {"from": "A", "to": "B"},
    {"from": "B", "to": "C"}
  ],
  "params": {"base_b": 10.0, "coeff_ab": 0.5, "base_c": 1000.0, "coeff_bc": 40.0}
}
```

**Causal Discovery Challenge:** Agent must discover the indirect effect A → B → C

### Example 2: Fork with Hybrid Node

```json
{
  "graph_id": "fork_with_hybrid",
  "nodes": {
    "T": {
      "is_controllable": true,
      "property_name": "temperatureC",
      "base_value": {"type": "uniform", "min": 10.0, "max": 50.0}
    },
    "M": {
      "is_controllable": true,
      "property_name": "moisture",
      "computation": "base + 0.5 * T",
      "base_value": {"type": "uniform", "min": 5.0, "max": 15.0}
    },
    "F": {
      "is_controllable": false,
      "property_name": "resonanceFreq",
      "computation": "1000.0 + 50.0 * T"
    }
  },
  "edges": [
    {"from": "T", "to": "M"},
    {"from": "T", "to": "F"}
  ],
  "params": {}
}
```

**Causal Discovery Challenge:** 
- Agent observes correlation between M and F
- Must discover that T is the common cause
- Must discover that M has both a controllable base and temperature influence
- Must distinguish between direct manipulation (changing M base) vs. indirect effect (changing T)

### Example 3: Collider (A → C, B → C)

```json
{
  "graph_id": "collider_3_nodes",
  "nodes": {
    "A": {"is_controllable": true, "property_name": "temperatureC", ...},
    "B": {"is_controllable": true, "property_name": "density", ...},
    "C": {
      "is_controllable": false,
      "property_name": "resonanceFreq",
      "computation": "base + coeff_a * A + coeff_b * B"
    }
  },
  "edges": [
    {"from": "A", "to": "C"},
    {"from": "B", "to": "C"}
  ],
  "params": {"base": 500.0, "coeff_a": 30.0, "coeff_b": 10.0}
}
```

**Causal Discovery Challenge:** Agent must discover that C depends on both A and B independently

## Running Experiments

### Single Graph Test
```bash
export CAUSAL_GRAPH_ID="chain_3_nodes"
sbatch agents/recoma/run_single_causal_graph.slurm
```

### Batch Testing Multiple Graphs
```bash
sbatch agents/recoma/run_batch_causal_graphs.slurm
```

### Custom Graph
```bash
export CAUSAL_GRAPH_CONFIG="/path/to/custom.json"
sbatch agents/recoma/run_single_causal_graph.slurm
```

## File Structure

```
discoveryworld/
├── causal_graph_configs/          # Configuration files
│   ├── README.md                  # User documentation
│   ├── USAGE.md                   # SLURM usage guide
│   ├── IMPLEMENTATION_SUMMARY.md  # This file
│   ├── chain_2_nodes.json         # Simple chain
│   ├── chain_3_nodes.json         # 3-node chain
│   ├── chain_4_nodes.json         # 4-node chain with hybrids
│   ├── fork_3_nodes.json          # Fork structure
│   ├── fork_with_base_4_nodes.json # Fork with hybrid
│   ├── collider_3_nodes.json      # Collider structure
│   ├── multi_root_collider.json   # Multiple causes
│   ├── diamond_4_nodes.json       # Diamond structure
│   ├── complex_5_nodes.json       # Complex graph
│   └── hybrid_example.json        # Hybrid node demo
├── discoveryworld/scenarios/
│   └── reactor_lab.py             # Main implementation
├── agents/recoma/
│   ├── run_single_causal_graph.slurm   # Test single graph
│   ├── run_batch_causal_graphs.slurm   # Batch test
│   └── run_react_simple-mem_parallel.slurm  # Original script
└── test_causal_configs.py         # Validation script
```

## Validation

Test configurations with:
```bash
python test_causal_configs.py                           # Test all configs
python test_causal_configs.py causal_graph_configs/chain_3_nodes.json  # Test specific
```

This validates:
- JSON syntax
- Graph structure
- Property value ranges
- Computation expressions
- Sample value generation

## Benefits of This System

1. **No Code Changes**: Define new causal structures entirely through config files
2. **Reproducibility**: Configuration files are version-controlled and self-documenting
3. **Flexibility**: Support for pure controllable, pure derived, and hybrid nodes
4. **Batch Testing**: Easy to test multiple causal structures in parallel
5. **Environment-Based**: Use environment variables, no parameter passing through functions
6. **Backward Compatible**: Legacy T→F, T→M system still works
7. **Extensible**: Easy to add new graph structures for new research questions

## Research Applications

This system enables studying:
1. **Causal discovery**: Can agents discover chains, forks, colliders, diamonds?
2. **Intervention vs. observation**: Do agents use PropertyManipulator effectively?
3. **Confounding**: Can agents distinguish correlation from causation?
4. **Indirect effects**: Can agents discover mediated relationships?
5. **Hybrid influences**: Can agents decompose direct and indirect effects?
6. **Complexity scaling**: How does performance scale with graph complexity?

## Future Extensions

Potential enhancements:
1. **Non-linear relationships**: Quadratic, exponential, etc.
2. **Conditional dependencies**: Relationships that depend on variable values
3. **Temporal dynamics**: Properties that change over time
4. **Stochastic relationships**: Noisy causal effects
5. **Feedback loops**: Cyclic causal relationships (requires special handling)
6. **Multi-valued properties**: Discrete or categorical variables
7. **Property constraints**: Hard bounds, mutual exclusions, etc.




