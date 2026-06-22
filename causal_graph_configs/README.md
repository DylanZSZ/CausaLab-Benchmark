# Causal Graph Configuration Files

This directory contains JSON configuration files for creating various causal graph structures in the DiscoveryWorld reactor lab scenarios.

## Overview

The configuration-based causal graph system allows you to:
- Define arbitrary causal relationships between crystal properties
- Support different numbers of nodes (2, 3, 4, 5, ...)
- Create various graph structures (chains, forks, colliders, diamonds, etc.)
- Batch load and test multiple causal structures

## Configuration File Format

Each JSON file defines a causal graph with the following structure:

```json
{
  "graph_id": "unique_identifier",
  "description": "Human-readable description",
  "nodes": {
    "node_name": {
      "is_controllable": true/false,
      "property_name": "crystal_property_name",
      "base_value": {...},  // For controllable nodes
      "computation": "expression"  // For derived nodes
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

### Node Types

The system supports three types of nodes:

**1. Pure Controllable Nodes**: Directly manipulable, no causal dependencies
- Must have `"is_controllable": true`
- Must have `"base_value"` configuration
- No `"computation"` expression
- Examples: temperature, density
- Value = base_value

**2. Pure Derived Nodes**: Computed entirely from parent nodes
- Must have `"is_controllable": false`
- Must have `"computation"` expression
- No `"base_value"` configuration
- Examples: resonance frequency
- Value = computation(parents)

**3. Hybrid Nodes**: Both manipulable AND influenced by parents
- Must have `"is_controllable": true`
- Must have both `"base_value"` AND `"computation"`
- The base_value can be referenced in computation as `base`
- Examples: moisture affected by both base level and temperature
- Value = computation(base, parents)

Example hybrid node:
```json
"B": {
  "is_controllable": true,
  "property_name": "moisture",
  "computation": "base + 0.5 * A",
  "base_value": {
    "type": "uniform",
    "min": 5.0,
    "max": 15.0
  }
}
```
In this example:
- Agent can manipulate B's base_value through PropertyManipulator
- B's final value = base_value + 0.5 * A
- This allows studying both direct manipulation and causal effects

### Base Value Types

For controllable nodes, specify how values are generated:

```json
"base_value": {
  "type": "uniform",
  "min": 10.0,
  "max": 50.0
}
```

Supported types:
- `"uniform"`: Uniform random in [min, max]
- `"fixed"`: Fixed value
- `"normal"`: Normal distribution with mean and std

### Computation Expressions

For derived and hybrid nodes, use mathematical expressions:

```json
"computation": "base + coeff * A"
```

Variables available in expressions:
- `base`: The node's own base_value (only for hybrid nodes)
- All parent node names (e.g., `A`, `B`, `C`)
- All parameter names from `params` (e.g., `coeff`, `offset`)

Expression examples:
- Hybrid node: `"base + coeff * A"` (node has both base_value and parent influence)
- Simple linear: `"offset + coeff * A"` (pure derived node)
- Multi-parent: `"offset + coeff_a * A + coeff_b * B"`
- With reference: `"base + coeff * (A - ref)"`
- Custom: `"A * B / 100"`, `"(A + B) / 2"`

**Important for Hybrid Nodes:**
- The `base` variable in computation refers to the node's base_value
- This allows the node to have a manipulable baseline affected by parents
- Example: `"base + 0.5 * Temperature"` means the value starts at `base` and increases with Temperature

### Property Mapping

The `"property_name"` field maps causal nodes to crystal attributes:

Available crystal properties:
- `"temperatureC"` - Temperature in Celsius
- `"moisture"` - Moisture level
- `"moistureBase"` - Base moisture (controllable)
- `"density"` - Crystal density
- `"quantumSize"` - Quantum size
- `"resonanceFreq"` - Resonance frequency

## Example Structures

### Chain Structures

**2-node chain** (`chain_2_nodes.json`): A → B
- Simple causal relationship
- Example: Temperature → Frequency

**3-node chain** (`chain_3_nodes.json`): A → B → C
- Sequential causation
- Example: Temperature → Moisture → Frequency

**4-node chain** (`chain_4_nodes.json`): A → B → C → D
- Long causal chain
- Tests indirect causal inference

### Fork Structures

**3-node fork** (`fork_3_nodes.json`): A → B, A → C
- Common cause structure
- Example: Temperature affects both Frequency and Moisture

**Fork with base** (`fork_with_base_4_nodes.json`): A → B, A → C, Base_C → C
- Fork with additional controllable variable
- Tests confounding vs. direct manipulation

### Collider Structures

**3-node collider** (`collider_3_nodes.json`): A → C, B → C
- Common effect structure
- Example: Temperature and Density both affect Frequency

**Multi-root collider** (`multi_root_collider.json`): A → D, B → D, C → D
- Multiple independent causes
- Tests additive causal effects

### Complex Structures

**Diamond** (`diamond_4_nodes.json`): A → B, A → C, B → D, C → D
- Combines fork and collider
- Tests mediated causation paths

**Complex 5-node** (`complex_5_nodes.json`)
- Multiple paths and independent variables
- Comprehensive causal discovery challenge

## Usage

### Method 1: Load from Configuration File

```python
from discoveryworld.scenarios.reactor_lab import load_causal_graph_from_file

# Load a specific graph
graph = load_causal_graph_from_file("causal_graph_configs/chain_3_nodes.json", world.rng)

# Use it to generate crystal properties
crystal = world.createObject("QuantumCrystal")
mkCrystalPropertiesCausal(crystal, world.rng, graph)
```

### Method 2: Load All Graphs from Directory

```python
from discoveryworld.scenarios.reactor_lab import load_all_causal_graphs_from_directory

# Load all graphs
graphs = load_all_causal_graphs_from_directory("causal_graph_configs", world.rng)

# Access by graph_id
graph = graphs["chain_3_nodes"]
```

### Method 3: Programmatic Configuration

```python
from discoveryworld.scenarios.reactor_lab import load_causal_graph_from_config

config = {
    "graph_id": "custom_graph",
    "description": "My custom causal structure",
    "nodes": {
        "T": {
            "is_controllable": True,
            "property_name": "temperatureC",
            "base_value": {"type": "uniform", "min": 10.0, "max": 50.0}
        },
        "F": {
            "is_controllable": False,
            "property_name": "resonanceFreq",
            "computation": "1000 + 50 * T"
        }
    },
    "edges": [{"from": "T", "to": "F"}],
    "params": {}
}

graph = load_causal_graph_from_config(config, world.rng)
```

## Integration with Reactor Lab Causal Scenario

To use a configuration file in the scenario:

```python
# In makeScenarioReactorLabCausal or similar function
import os

# Set environment variable to specify which config to use
os.environ["CAUSAL_GRAPH_CONFIG"] = "causal_graph_configs/chain_3_nodes.json"

# Or load programmatically
graph = load_causal_graph_from_file("causal_graph_configs/fork_3_nodes.json", world.rng)

# Pass to mkReactorLabCausal via scoringInfo or similar mechanism
```

## Creating New Configurations

To create a new causal graph configuration:

1. **Define your causal structure** (draw it out if helpful)
2. **Identify controllable vs. derived variables**
3. **Create JSON file** following the format above
4. **Specify computation expressions** for derived nodes
5. **Set parameter values** that make sense for crystal properties
6. **Test the configuration** (see Testing section below)

### Tips for Good Configurations

- **Resonance frequency** should typically be in range [500, 3000] Hz
- **Temperature** typically in range [10, 50] °C
- **Moisture** typically in range [5, 30]
- **Density** typically in range [10, 70] g/cm³
- **Quantum size** typically in range [10, 70] nm

- Keep coefficients reasonable so properties stay in valid ranges
- Use base values that prevent negative or extreme values
- Test with multiple random seeds to ensure stability

## Testing Configurations

Use the provided test script to validate configurations:

```python
python test_causal_configs.py
```

This will:
- Load all configuration files
- Generate sample crystals with each graph
- Verify that all properties are within valid ranges
- Display the causal structure and sample values

## Troubleshooting

**Error: "Node 'X' not found in graph"**
- Check that all edges reference existing node names
- Ensure node names match exactly (case-sensitive)

**Error: "Error evaluating computation for node 'X'"**
- Verify that all variables in the expression are defined
- Check that parameter names match those in `params`
- Ensure mathematical operations are valid

**Properties out of range**
- Adjust coefficients and base values
- Use min/max clipping for uniform distributions
- Consider using reference values (e.g., `A - ref`)

## Advanced Features

### Custom Computation Functions

For complex causal relationships not expressible as simple equations, you can extend the system by modifying `create_computation_fn_from_expression()` in `reactor_lab.py`.

### Dynamic Parameter Generation

Parameters can be made seed-dependent by modifying the configuration loading logic to accept a seed parameter and generate parameter values accordingly.

### Property Constraints

To add constraints (e.g., "frequency must always be positive"), modify `mkCrystalPropertiesCausal()` to apply post-processing to computed values.

## File Inventory

This directory contains the following example configurations:

1. **chain_2_nodes.json** - Simple A→B chain
2. **chain_3_nodes.json** - A→B→C sequential chain
3. **chain_4_nodes.json** - A→B→C→D long chain
4. **fork_3_nodes.json** - A→B, A→C fork structure
5. **fork_with_base_4_nodes.json** - Fork with controllable base
6. **collider_3_nodes.json** - A→C, B→C collider
7. **multi_root_collider.json** - A→D, B→D, C→D multiple causes
8. **diamond_4_nodes.json** - Diamond structure with mediation
9. **complex_5_nodes.json** - Complex 5-node graph

## Support

For questions or issues:
- Check the docstrings in `reactor_lab.py`
- Review example configurations in this directory
- Test with the provided test script

