# reactor_lab.py

import random
import os
import json
from discoveryworld.Agent import (
    Agent,
    NPCChef1,
    NPCColonistAuto2,
    NPCFarmer1,
    FrequencyEstimator,
    PropertyManipulator,
)
from discoveryworld.DialogTree import DialogMaker
from discoveryworld.Layer import Layer
from discoveryworld.buildings.cave import mkCave
from discoveryworld.buildings.colony import (
    mkBarracks,
    mkCafeteria,
    mkInfirmary,
    mkScienceLab,
)
from discoveryworld.buildings.farm import mkFarm

from discoveryworld.buildings.terrain import (
    mkFenceX,
    mkFenceY,
    mkGrassFill,
    mkPathX,
    mkPathY,
    mkSignVillage,
    mkTallTree,
    mkTownSquare,
)

from discoveryworld.buildings.house import (
    mkBuildingDivided,
    mkBuildingOneRoom,
    mkTableAndChairs,
)


#
#   Causal Configuration System
#   Allows both random generation and manual specification of causal parameters
#


class CausalConfig:
    """
    Configuration class for causal relationship parameters.

    This class allows you to either:
    1. Use random generation (default behavior)
    2. Manually specify parameters for debugging/testing

    Example usage:
        # Random generation (default):
        config = CausalConfig()

        # Manual specification:
        config = CausalConfig(
            T_ref=20.0,
            F_0=1000.0,
            k_f=50.0,
            k_d=0.5,
            T_range=(10.0, 50.0),
            M_0_range=(5.0, 25.0)
        )
    """

    def __init__(
        self,
        T_ref=None,  # Reference temperature
        F_0=None,  # Base frequency
        k_f=None,  # Temperature-to-frequency coefficient
        k_d=None,  # Temperature-to-moisture coefficient (dehydration rate)
        T_range=None,  # Range for random temperature generation: (min, max)
        M_0_range=None,  # Range for random base moisture generation: (min, max)
        T_fixed=None,  # Fixed temperature for all crystals (overrides T_range)
        M_0_fixed=None,  # Fixed base moisture for all crystals (overrides M_0_range)
        mode="random",  # "random" or "manual"
    ):
        """
        Initialize causal configuration.

        Args:
            T_ref: Reference temperature (default: random if None)
            F_0: Base frequency (default: random if None)
            k_f: Temperature-to-frequency coefficient (default: random if None)
            k_d: Temperature-to-moisture coefficient (default: random if None)
            T_range: Tuple (min, max) for temperature range (default: (10.0, 50.0))
            M_0_range: Tuple (min, max) for base moisture range (default: (5.0, 25.0))
            T_fixed: Fixed temperature value for all crystals (overrides T_range if set)
            M_0_fixed: Fixed base moisture value for all crystals (overrides M_0_range if set)
            mode: "random" or "manual" - determines default behavior
        """
        # Store mode
        self.mode = mode

        # Set defaults for ranges
        self.T_range = T_range if T_range is not None else (10.0, 50.0)
        self.M_0_range = M_0_range if M_0_range is not None else (5.0, 25.0)

        # Store fixed values (if provided, these override ranges)
        self.T_fixed = T_fixed
        self.M_0_fixed = M_0_fixed

        # Store parameters (None means they should be randomly generated)
        self.T_ref = T_ref
        self.F_0 = F_0
        self.k_f = k_f
        self.k_d = k_d

        # If any parameter is specified, switch to manual mode
        if any(p is not None for p in [T_ref, F_0, k_f, k_d, T_fixed, M_0_fixed]):
            self.mode = "manual"

    def get_params(self, rng=None):
        """
        Get the causal parameters, generating random values if needed.

        Args:
            rng: Random number generator (required if mode is "random")

        Returns:
            dict: Dictionary containing all causal parameters
        """
        # Default values (used if manual mode and parameter not specified)
        default_T_ref = 20.0
        default_F_0 = 1000.0
        default_k_f = 50.0
        default_k_d = 0.5

        if self.mode == "random" and rng is not None:
            # Generate random parameters if not specified
            return {
                "T_ref": self.T_ref if self.T_ref is not None else default_T_ref,
                "F_0": self.F_0 if self.F_0 is not None else default_F_0,
                "k_f": self.k_f if self.k_f is not None else default_k_f,
                "k_d": self.k_d if self.k_d is not None else default_k_d,
                "T_range": self.T_range,
                "M_0_range": self.M_0_range,
                "T_fixed": self.T_fixed,
                "M_0_fixed": self.M_0_fixed,
            }
        else:
            # Use specified values or defaults
            return {
                "T_ref": self.T_ref if self.T_ref is not None else default_T_ref,
                "F_0": self.F_0 if self.F_0 is not None else default_F_0,
                "k_f": self.k_f if self.k_f is not None else default_k_f,
                "k_d": self.k_d if self.k_d is not None else default_k_d,
                "T_range": self.T_range,
                "M_0_range": self.M_0_range,
                "T_fixed": self.T_fixed,
                "M_0_fixed": self.M_0_fixed,
            }

    def __str__(self):
        """String representation of the configuration."""
        params = self.get_params()
        fixed_str = ""
        if self.T_fixed is not None:
            fixed_str += f", T_fixed={self.T_fixed}"
        if self.M_0_fixed is not None:
            fixed_str += f", M_0_fixed={self.M_0_fixed}"
        return (
            f"CausalConfig(mode={self.mode}, "
            f"T_ref={params['T_ref']}, F_0={params['F_0']}, "
            f"k_f={params['k_f']}, k_d={params['k_d']}, "
            f"T_range={params['T_range']}, M_0_range={params['M_0_range']}{fixed_str})"
        )


#
#   Causal Graph Framework
#   A generic, extensible system for defining and computing causal relationships between properties
#


class CausalNode:
    """Represents a node in the causal graph (a property/variable)"""

    def __init__(
        self,
        name,
        is_controllable=False,
        base_value=None,
        computation_fn=None,
        computation_expression=None,
    ):
        """
        Args:
            name: The name of the property (e.g., 'temperature', 'frequency', 'moisture')
            is_controllable: Whether this property can be directly set/controlled
            base_value: The base/initial value if controllable (can be callable for random generation)
            computation_fn: Function to compute this property from its parents (signature: fn(parent_values, params))
            computation_expression: Optional string expression for the computation (for prompt display/debugging)
        """
        self.name = name
        self.is_controllable = is_controllable
        self.base_value = base_value
        self.computation_fn = computation_fn
        self.computation_expression = computation_expression
        self.parents = []  # List of parent node names this depends on
        self.children = []  # List of child node names that depend on this


class CausalGraph:
    """
    A generic causal graph that can represent arbitrary causal relationships.

    Example usage for T->F, T->M:
        graph = CausalGraph()
        # T is controllable
        graph.add_node('T', is_controllable=True, base_value=lambda rng: rng.uniform(10, 50))
        # M_0 is controllable
        graph.add_node('M_0', is_controllable=True, base_value=lambda rng: rng.uniform(5, 25))
        # F depends on T: F = F_0 + k_f(T - T_ref)
        graph.add_node('F', computation_fn=lambda parents, params:
                       params['F_0'] + params['k_f'] * (parents['T'] - params['T_ref']))
        # M depends on T and M_0: M = M_0 + k_d(T - T_ref)
        graph.add_node('M', computation_fn=lambda parents, params:
                       parents['M_0'] + params['k_d'] * (parents['T'] - params['T_ref']))
        graph.add_edge('T', 'F')
        graph.add_edge('T', 'M')
        graph.add_edge('M_0', 'M')
    """

    def __init__(self):
        self.nodes = {}  # name -> CausalNode
        self.computation_params = (
            {}
        )  # Parameters for computation functions (e.g., k_f, k_d, T_ref, F_0)
        self.node_property_mapping = {}
        self.node_observable = {}
        self.node_display_names = {}

    def add_node(
        self,
        name,
        is_controllable=False,
        base_value=None,
        computation_fn=None,
        computation_expression=None,
    ):
        """Add a node to the causal graph"""
        node = CausalNode(
            name,
            is_controllable,
            base_value,
            computation_fn,
            computation_expression=computation_expression,
        )
        self.nodes[name] = node
        return node

    def add_edge(self, parent_name, child_name):
        """Add a causal edge from parent to child (parent -> child)"""
        if parent_name not in self.nodes:
            raise ValueError(f"Parent node '{parent_name}' not found in graph")
        if child_name not in self.nodes:
            raise ValueError(f"Child node '{child_name}' not found in graph")

        self.nodes[parent_name].children.append(child_name)
        self.nodes[child_name].parents.append(parent_name)

    def set_params(self, **params):
        """Set computation parameters (e.g., k_f=100, T_ref=20, F_0=1000)"""
        self.computation_params.update(params)

    def compute_values(self, rng, precision=2, override_base_values=None):
        """
        Compute all property values based on the causal graph structure.
        Returns a dictionary of {property_name: value}

        Supports three types of nodes:
        1. Pure controllable: only base_value, no computation
        2. Pure derived: only computation_fn, no base_value
        3. Hybrid: both base_value and computation_fn
           - base_value is generated first
           - computation_fn can reference it as 'base' variable
           - useful for nodes that have a base level but are influenced by others

        Args:
            rng: Random number generator
            precision: Decimal precision for rounding
            override_base_values: Optional dict of {node_name: value} to override
                                 controllable node values instead of generating them
        """
        values = {}
        base_values = {}  # Store base values separately for hybrid nodes
        computed = set()

        # Use provided overrides if available
        if override_base_values is None:
            override_base_values = {}

        # Topological sort to ensure we compute in the right order
        def compute_node(node_name):
            if node_name in computed:
                return values[node_name]

            node = self.nodes[node_name]

            # First, generate base value if this is a controllable node
            base_value = None
            if node.is_controllable:
                # Check if we have an override value
                if node_name in override_base_values:
                    base_value = override_base_values[node_name]
                elif callable(node.base_value):
                    base_value = node.base_value(rng)
                else:
                    base_value = node.base_value
                base_values[node_name] = base_value

            # If no computation function, use base value directly
            if node.computation_fn is None:
                if base_value is None:
                    raise ValueError(
                        f"Node '{node_name}' has no base_value and no computation function"
                    )
                values[node_name] = round(base_value, precision)
                computed.add(node_name)
                return values[node_name]

            # Compute from parents and/or base value
            parent_values = {}
            for parent_name in node.parents:
                parent_values[parent_name] = compute_node(parent_name)

            # Add base value to computation environment if available
            if base_value is not None:
                parent_values["base"] = base_value
                # Also add with node name for backward compatibility
                parent_values[f"{node_name}_base"] = base_value

            value = node.computation_fn(parent_values, self.computation_params)
            values[node_name] = round(value, precision)
            computed.add(node_name)
            return values[node_name]

        # Compute all nodes
        for node_name in self.nodes:
            compute_node(node_name)

        # Store base values in a separate field for PropertyManipulator access
        self._last_base_values = base_values

        return values

    def get_causal_description(self):
        """Get a human-readable description of the causal relationships"""
        descriptions = []
        for node_name, node in self.nodes.items():
            if node.parents:
                parents_str = ", ".join(node.parents)
                descriptions.append(f"{node_name} depends on: {parents_str}")
            if node.is_controllable:
                descriptions.append(f"{node_name} is controllable")
        return descriptions

    def get_formula_descriptions(self, use_display_names: bool = True):
        """Return human-readable formulas for nodes that have computation expressions."""
        formulas = []
        for node_name, node in self.nodes.items():
            expr = getattr(node, "computation_expression", None)
            if not expr:
                continue

            lhs = (
                self.node_display_names.get(
                    node_name, self.node_property_mapping.get(node_name, node_name)
                )
                if use_display_names
                else node_name
            )
            formulas.append(f"{lhs} = {expr}")
        return formulas


#
#   Configuration-based Causal Graph Builder
#   Supports batch creation of diverse causal structures
#


def create_computation_fn_from_expression(expression, node_name):
    """
    Create a computation function from a string expression.

    Supported expression formats:
    - Simple linear: "base + coeff * A" -> params['base'] + params['coeff'] * parents['A']
    - Multi-parent: "base + coeff1 * A + coeff2 * B"
    - Quadratic: "base + c2 * A^2 + c1 * A" or "base + c2 * (A ** 2) + c1 * A"
    - With reference: "base + coeff * (A - ref)" -> params['base'] + params['coeff'] * (parents['A'] - params['ref'])
    - Custom: "A + B", "A * B / 100", etc.

    For hybrid nodes, the expression can use:
    - 'base' variable (from parent_values, dynamically set from crystal's {prop}_base attribute)
    - 'base_{prop_name}' parameter (from params, static from config)
    - Both will be available, with 'base' taking precedence for dynamic adjustments

    Args:
        expression: String expression describing the computation
        node_name: Name of the node (for error messages)

    Returns:
        A lambda function that takes (parents, params) and returns the computed value
    """
    normalized_expression = expression.replace("^", "**")

    def computation_fn(parents, params):
        # Create a safe evaluation environment
        # Available: all parent values and all parameters
        env = {}
        env.update(parents)
        env.update(params)

        # For hybrid nodes: if 'base' is in parent_values (dynamically set),
        # also make it available as base_{prop_name} for backward compatibility
        # This allows expressions like "base_moisture + coeff * temp" to work
        # while still supporting dynamic base adjustments
        if "base" in parents:
            # Extract property name from node_name (e.g., "moisture" from "moisture" node)
            # and create parameter name like "base_moisture"
            prop_base_param = f"base_{node_name}"
            # Always use dynamic 'base' value (from crystal's {prop}_base attribute)
            # when available, overriding the static param value
            env[prop_base_param] = parents["base"]

        try:
            return eval(normalized_expression, {"__builtins__": {}}, env)
        except Exception as e:
            raise ValueError(
                f"Error evaluating computation for node '{node_name}': {expression}\n{e}"
            )

    computation_fn._expression = expression  # Helpful for debugging and prompts
    return computation_fn


def create_base_value_generator(value_config):
    """
    Create a base value generator from configuration.

    Supported types:
    - "uniform": uniform random in [min, max]
    - "fixed": fixed value
    - "normal": normal distribution with mean and std

    Args:
        value_config: Dictionary with 'type' and type-specific parameters

    Returns:
        A lambda function that takes rng and returns a value
    """
    value_type = value_config.get("type", "uniform")

    if value_type == "uniform":
        min_val = value_config.get("min", 10.0)
        max_val = value_config.get("max", 50.0)
        return lambda rng: rng.uniform(min_val, max_val)

    elif value_type == "fixed":
        fixed_val = value_config.get("value", 20.0)
        return lambda rng: fixed_val

    elif value_type == "normal":
        mean = value_config.get("mean", 30.0)
        std = value_config.get("std", 5.0)
        min_val = value_config.get("min", 0.0)  # Optional clipping
        max_val = value_config.get("max", 100.0)
        return lambda rng: max(min_val, min(max_val, rng.gauss(mean, std)))

    else:
        raise ValueError(f"Unknown base value type: {value_type}")


def load_causal_graph_from_config(config_dict, rng):
    """
    Load a causal graph from a configuration dictionary.

    Configuration format:
    {
        "graph_id": "unique_identifier",
        "description": "Human-readable description",
        "nodes": {
            "node_name": {
                "is_controllable": true/false,
                "property_name": "temperatureC",  # Maps to crystal attribute
                "base_value": {  # Only for controllable nodes
                    "type": "uniform",
                    "min": 10.0,
                    "max": 50.0
                },
                "computation": "expression"  # Only for non-controllable nodes
            }
        },
        "edges": [
            {"from": "parent", "to": "child"}
        ],
        "params": {
            "param_name": value
        }
    }

    Args:
        config_dict: Configuration dictionary
        rng: Random number generator

    Returns:
        CausalGraph instance configured according to the specification
    """
    graph = CausalGraph()

    # Parse nodes
    nodes_config = config_dict.get("nodes", {})
    for node_name, node_config in nodes_config.items():
        is_controllable = node_config.get("is_controllable", False)
        has_computation = "computation" in node_config
        has_base_value = "base_value" in node_config

        # Generate base_value function if specified
        base_value_fn = None
        if has_base_value:
            base_value_config = node_config.get("base_value", {"type": "uniform"})
            base_value_fn = create_base_value_generator(base_value_config)

        # Generate computation function if specified
        computation_fn = None
        computation_expression = None
        if has_computation:
            expression = node_config.get("computation", "0")
            computation_expression = expression
            computation_fn = create_computation_fn_from_expression(
                expression, node_name
            )

        # Add node with appropriate configuration
        # Supports three cases:
        # 1. Pure controllable: has base_value, no computation
        # 2. Pure derived: has computation, no base_value
        # 3. Hybrid: has both base_value and computation
        #    - base_value is accessible in computation as 'base' variable
        if is_controllable:
            # Controllable but no base_value specified - use default
            if base_value_fn is None:
                base_value_fn = create_base_value_generator({"type": "uniform"})
            graph.add_node(
                node_name,
                is_controllable=True,
                base_value=base_value_fn,
                computation_fn=computation_fn,
                computation_expression=computation_expression,
            )
        else:
            # Non-controllable node: only computation
            if computation_fn is None:
                raise ValueError(
                    f"Node '{node_name}' is not controllable and has no computation"
                )
            graph.add_node(
                node_name,
                is_controllable=False,
                base_value=None,
                computation_fn=computation_fn,
                computation_expression=computation_expression,
            )

    # Parse edges
    edges_config = config_dict.get("edges", [])
    for edge in edges_config:
        parent = edge.get("from")
        child = edge.get("to")
        graph.add_edge(parent, child)

    # Set parameters
    params = config_dict.get("params", {})
    graph.set_params(**params)

    # Store metadata
    graph.graph_id = config_dict.get("graph_id", "unknown")
    graph.description = config_dict.get("description", "")
    graph.equation_family = config_dict.get("equation_family")
    graph.quadratic_mode = config_dict.get("quadratic_mode")
    graph.quadratic_metadata = config_dict.get("quadratic_metadata", {})
    graph.frequency_can_be_parent = bool(
        config_dict.get("frequency_can_be_parent", False)
    )
    bootstrap_past_data = config_dict.get("bootstrap_past_data", [])
    if isinstance(bootstrap_past_data, list):
        graph.bootstrap_past_data = bootstrap_past_data
    else:
        graph.bootstrap_past_data = []
    graph.node_property_mapping = {}
    graph.node_observable = {}
    graph.node_display_names = {}
    for node_name, node_config in nodes_config.items():
        if "property_name" in node_config:
            graph.node_property_mapping[node_name] = node_config["property_name"]
        # Store observable flag (default to True for backward compatibility)
        graph.node_observable[node_name] = node_config.get("observable", True)
        # Store display name (default to property name or node name)
        if "display_name" in node_config:
            graph.node_display_names[node_name] = node_config["display_name"]
        elif "property_name" in node_config:
            graph.node_display_names[node_name] = node_config["property_name"]
        else:
            graph.node_display_names[node_name] = node_name

    # Optional hidden variable metadata (used by PropertyManipulator only).
    # This variable is intentionally not added as a visible/intervenable graph node.
    hidden_variable = config_dict.get("hidden_variable")
    graph.hidden_variable = None
    if isinstance(hidden_variable, dict):
        affected_nodes = hidden_variable.get("affected_nodes", [])
        if isinstance(affected_nodes, list):
            affected_nodes = [n for n in affected_nodes if n in graph.nodes]
        else:
            affected_nodes = []

        if affected_nodes:
            value_space = hidden_variable.get("value_space", [-1, 0, 1])
            if not isinstance(value_space, list) or not value_space:
                value_space = [-1, 0, 1]

            graph.hidden_variable = {
                "enabled": bool(hidden_variable.get("enabled", True)),
                "name": hidden_variable.get("name", "h"),
                "observable": False,
                "is_controllable": False,
                "initial_value": float(hidden_variable.get("initial_value", 0.0)),
                "edge_weight": float(hidden_variable.get("edge_weight", 0.5)),
                "value_space": value_space,
                "affected_nodes": affected_nodes,
            }

    # Store budget for PropertyManipulator (if specified in config).
    # Allow experiment-time overrides without mutating the source graph file.
    graph.budget = config_dict.get("budget", None)
    budget_override = os.environ.get("CAUSAL_GRAPH_BUDGET_OVERRIDE")
    if budget_override not in (None, ""):
        try:
            graph.budget = int(budget_override)
            print(
                f"[load_causal_graph_from_config] Overriding graph budget with "
                f"CAUSAL_GRAPH_BUDGET_OVERRIDE={graph.budget}"
            )
        except ValueError:
            print(
                "[load_causal_graph_from_config] WARNING: invalid "
                f"CAUSAL_GRAPH_BUDGET_OVERRIDE={budget_override!r}; "
                "falling back to graph config budget"
            )

    return graph


def load_causal_graph_from_file(filepath, rng):
    """
    Load a causal graph from a JSON configuration file.

    Args:
        filepath: Path to JSON configuration file
        rng: Random number generator

    Returns:
        CausalGraph instance
    """
    with open(filepath, "r") as f:
        config = json.load(f)
    return load_causal_graph_from_config(config, rng)


def load_all_causal_graphs_from_directory(directory_path, rng):
    """
    Load all causal graph configurations from a directory.

    Args:
        directory_path: Path to directory containing JSON config files
        rng: Random number generator

    Returns:
        Dictionary mapping graph_id to CausalGraph instances
    """
    import glob

    graphs = {}
    json_files = glob.glob(os.path.join(directory_path, "*.json"))

    for filepath in json_files:
        try:
            graph = load_causal_graph_from_file(filepath, rng)
            graphs[graph.graph_id] = graph
            print(f"Loaded causal graph: {graph.graph_id} from {filepath}")
        except Exception as e:
            print(f"Error loading {filepath}: {e}")

    return graphs


def get_hard_quadratic_presets(causal_graph):
    """Return deterministic hard-quadratic presets when the graph declares them."""
    if getattr(causal_graph, "quadratic_mode", None) != "hard":
        return None

    quadratic_metadata = getattr(causal_graph, "quadratic_metadata", None)
    if not isinstance(quadratic_metadata, dict):
        return None

    observation_presets = quadratic_metadata.get("observation_presets")
    property_manipulator = quadratic_metadata.get("property_manipulator")
    reactor = quadratic_metadata.get("reactor")
    if (
        isinstance(observation_presets, list)
        and len(observation_presets) >= 2
        and isinstance(property_manipulator, dict)
        and isinstance(reactor, dict)
    ):
        return {
            "observation_presets": observation_presets,
            "property_manipulator": property_manipulator,
            "reactor": reactor,
        }

    # Backward compatibility for older hard-quad graph files.
    lows = quadratic_metadata.get("source_low_by_node", {})
    highs = quadratic_metadata.get("source_high_by_node", {})
    order = quadratic_metadata.get("controllable_node_order")
    if not isinstance(order, list):
        order = [
            node_name
            for node_name, node in causal_graph.nodes.items()
            if node.is_controllable
        ]

    if not all(node_name in lows and node_name in highs for node_name in order):
        return None

    observation_low = {node_name: float(lows[node_name]) for node_name in order}
    observation_high = {node_name: float(highs[node_name]) for node_name in order}
    property_manipulator = {}
    reactor = {}
    for idx, node_name in enumerate(order):
        low = float(lows[node_name])
        high = float(highs[node_name])
        if idx % 2 == 0:
            property_manipulator[node_name] = low
            reactor[node_name] = high
        else:
            property_manipulator[node_name] = high
            reactor[node_name] = low

    return {
        "observation_presets": [observation_low, observation_high],
        "property_manipulator": property_manipulator,
        "reactor": reactor,
    }


def mkCrystalPropertiesCausal(
    quantumCrystalIn, rng, causal_graph, override_base_values=None
):
    """
    Generate quantum crystal properties using a causal graph.

    This function demonstrates how to use the CausalGraph framework to generate
    crystal properties with arbitrary causal relationships.

    Args:
        quantumCrystalIn: The quantum crystal object to populate
        rng: Random number generator
        causal_graph: A CausalGraph instance defining the causal relationships
        override_base_values: Optional dict of {node_name: value} to override
                             controllable node values instead of generating them

    Returns:
        The populated quantum crystal
    """
    precision = 2

    # Compute all property values according to the causal graph
    values = causal_graph.compute_values(
        rng, precision, override_base_values=override_base_values
    )

    # Map computed values to crystal attributes using property mapping
    # If graph has node_property_mapping, use it; otherwise fall back to legacy mapping
    # if (
    #     hasattr(causal_graph, "node_property_mapping")
    #     and causal_graph.node_property_mapping
    # ):
    for node_name, property_name in causal_graph.node_property_mapping.items():
        if node_name in values:
            quantumCrystalIn.attributes[property_name] = values[node_name]

            # For hybrid nodes, also store the base value
            node = causal_graph.nodes.get(node_name)
            if node and node.is_controllable and node.computation_fn is not None:
                # This is a hybrid node - store its base value
                if (
                    hasattr(causal_graph, "_last_base_values")
                    and node_name in causal_graph._last_base_values
                ):
                    base_value = causal_graph._last_base_values[node_name]
                    quantumCrystalIn.attributes[f"{property_name}_base"] = base_value
                    print(
                        f"[mkCrystalPropertiesCausal] Hybrid node {property_name}: value={values[node_name]}, base={base_value}"
                    )
    # else:
    #     # Legacy mapping for backward compatibility (T->F, T->M graph)
    #     if "T" in values:
    #         quantumCrystalIn.attributes["temperatureC"] = values["T"]
    #     if "M" in values:
    #         quantumCrystalIn.attributes["moisture"] = values["M"]
    #     if "M_0" in values:
    #         quantumCrystalIn.attributes["moistureBase"] = values["M_0"]
    #     if "F" in values:
    #         quantumCrystalIn.attributes["resonanceFreq"] = values["F"]

    # Set standard properties if not already set by causal graph
    if "density" not in quantumCrystalIn.attributes:
        quantumCrystalIn.attributes["density"] = round(
            rng.uniform(15.0, 45.0), precision
        )
    if "quantumSize" not in quantumCrystalIn.attributes:
        quantumCrystalIn.attributes["quantumSize"] = round(
            rng.uniform(15.0, 45.0), precision
        )
    if "temperatureC" not in quantumCrystalIn.attributes:
        quantumCrystalIn.attributes["temperatureC"] = round(
            rng.uniform(15.0, 45.0), precision
        )

    # Add a faux material
    fauxMaterial = {}
    # If radiation was computed by causal graph, use that value; otherwise generate one
    if "radiation" in quantumCrystalIn.attributes:
        fauxMaterial["radiationusvh"] = quantumCrystalIn.attributes["radiation"]
    else:
        fauxMaterial["radiationusvh"] = round(rng.uniform(15.0, 45.0), precision)
    spectrum = []
    for i in range(0, 5):
        channelValue = round(rng.uniform(15.0, 45.0), precision)
        spectrum.append(channelValue)
    fauxMaterial["spectrum"] = spectrum
    fauxMaterial["microscopeDesc"] = (
        "The quantum gap of this crystal appears to be "
        + str(quantumCrystalIn.attributes["quantumSize"])
        + " nm"
    )
    quantumCrystalIn.attributes["materials"] = [fauxMaterial]

    # Create a key measurement description for scoring
    # Build description from all causal graph values
    if values:
        desc_parts = []
        for node_name, value in sorted(values.items()):
            property_name = (
                causal_graph.node_property_mapping.get(node_name, node_name)
                if hasattr(causal_graph, "node_property_mapping")
                else node_name
            )
            desc_parts.append(f"{property_name}={value}")
        quantumCrystalIn.attributes["keyMeasurement"] = ", ".join(desc_parts)

    return quantumCrystalIn


# Helper to create a reactor
def mkGenerator(x, y, world, linkedObjects, reactorLength=3):
    # Left side
    world.addObject(x, y, Layer.OBJECTS, world.createObject("GeneratorSideLeft"))
    # Right side
    world.addObject(
        x + reactorLength, y, Layer.OBJECTS, world.createObject("GeneratorSideRight")
    )
    # Middle
    for i in range(1, reactorLength):
        reactorCenterPiece = world.createObject("GeneratorCenter")
        # Add the linked objects, so the reactor activates when they activate
        reactorCenterPiece.addLinkedObjectsActivationState(linkedObjects)

        world.addObject(x + i, y, Layer.OBJECTS, reactorCenterPiece)


# Make random properties of a quantum crystal
# Linear function (y=mx+b)
def mkCrystalProperties(
    quantumCrystalIn,
    rng,
    keyDimension: int = 0,
    slope: float = 100.0,
    offset: float = 100,
):
    # Resonance Frequency of the crystal (a set property for a given crystal)
    # quantumCrystalIn.attributes['resonanceFreq'] = 5000                    # The resonance frequency of the crystal
    precision = 2  # Number of decimal places to round to

    # Quantities that the crystal depends on
    quantumCrystalIn.attributes["density"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The density of the crystal (in g/cm^3)
    quantumCrystalIn.attributes["temperatureC"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The temperature of the crystal (in degrees C)
    quantumCrystalIn.attributes["quantumSize"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The quantum size of the crystal (in nm)
    # Add a faux material, with a given radiation and spectrum
    fauxMaterial = {}
    fauxMaterial["radiationusvh"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The radiation of the crystal (in mSv)
    spectrum = []
    for i in range(0, 5):
        channelValue = round(rng.uniform(15.0, 45.0), precision)
        spectrum.append(channelValue)
    fauxMaterial["spectrum"] = (
        spectrum  # The spectrum of the crystal (on 5 spectral channels)
    )
    fauxMaterial["microscopeDesc"] = (
        "The quantum gap of this crystal appears to be "
        + str(quantumCrystalIn.attributes["quantumSize"])
        + " nm"
    )  # The description of the crystal under a microscope
    ##quantumCrystalIn.attributes['materials'].append(fauxMaterial)     ## OLD -- adds a new material, so there are two materials (the default, and this one) -- generates lots of bugs with instruments.
    quantumCrystalIn.attributes["materials"] = [
        fauxMaterial
    ]  ## NEW -- replaces the default material with this generated one

    # Pick one dimension (density, temperature, quantumSize, radiation, or spectrum) to be the "key" dimension.  Dimensions are numbered (0, 1, 2, 3, 4)
    keyValue = 0
    if keyDimension == 0:
        keyValue = quantumCrystalIn.attributes["density"]
        quantumCrystalIn.attributes["keyMeasurement"] = "density"
    elif keyDimension == 1:
        keyValue = quantumCrystalIn.attributes["temperatureC"]
        quantumCrystalIn.attributes["keyMeasurement"] = "temperature"
    elif keyDimension == 2:
        keyValue = quantumCrystalIn.attributes["quantumSize"]
        quantumCrystalIn.attributes["keyMeasurement"] = "quantum size"
    elif keyDimension == 3:
        keyValue = fauxMaterial["radiationusvh"]
        quantumCrystalIn.attributes["keyMeasurement"] = "radiation"
    elif keyDimension == 4:
        keyValue = fauxMaterial["spectrum"][4]
        quantumCrystalIn.attributes["keyMeasurement"] = "spectrum (channel 4)"
    else:
        print("Error: mkCrystalProperties(): keyDimension must be between 0 and 4")

    # The value of 'resonanceFreq' will be a linear function of the keyValue, with the specified slope and offset
    resonanceFreq = (slope * keyValue) + offset
    # NOTE, resonance frequency is now a float, rounded to 2 decimal places
    resonanceFreq = round(resonanceFreq, 2)
    quantumCrystalIn.attributes["resonanceFreq"] = resonanceFreq
    quantumCrystalIn.attributes["keyMeasurement"] += " of " + str(keyValue)

    # Return
    return quantumCrystalIn


# Make random properties of a quantum crystal
# Quadratic function (y=ax^2 + bx + c)
def mkCrystalPropertiesQuadratic(
    quantumCrystalIn,
    rng,
    keyDimension: int = 0,
    a: float = 100.0,
    b: float = 100,
    c: float = 0,
):
    # Resonance Frequency of the crystal (a set property for a given crystal)
    # quantumCrystalIn.attributes['resonanceFreq'] = 5000                    # The resonance frequency of the crystal
    precision = 2  # Number of decimal places to round to

    # Quantities that the crystal depends on
    quantumCrystalIn.attributes["density"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The density of the crystal (in g/cm^3)
    quantumCrystalIn.attributes["temperatureC"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The temperature of the crystal (in degrees C)
    quantumCrystalIn.attributes["quantumSize"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The quantum size of the crystal (in nm)
    # Add a faux material, with a given radiation and spectrum
    fauxMaterial = {}
    fauxMaterial["radiationusvh"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The radiation of the crystal (in mSv)
    spectrum = []
    for i in range(0, 5):
        channelValue = round(rng.uniform(15.0, 45.0), precision)
        spectrum.append(channelValue)
    fauxMaterial["spectrum"] = (
        spectrum  # The spectrum of the crystal (on 5 spectral channels)
    )
    fauxMaterial["microscopeDesc"] = (
        "The quantum gap of this crystal appears to be "
        + str(quantumCrystalIn.attributes["quantumSize"])
        + " nm"
    )  # The description of the crystal under a microscope
    ##quantumCrystalIn.attributes['materials'].append(fauxMaterial)     ## OLD -- adds a new material, so there are two materials (the default, and this one) -- generates lots of bugs with instruments.
    quantumCrystalIn.attributes["materials"] = [
        fauxMaterial
    ]  ## NEW -- replaces the default material with this generated one

    # Pick one dimension (density, temperature, quantumSize, radiation, or spectrum) to be the "key" dimension.  Dimensions are numbered (0, 1, 2, 3, 4)
    keyValue = 0
    if keyDimension == 0:
        keyValue = quantumCrystalIn.attributes["temperatureC"]
        quantumCrystalIn.attributes["keyMeasurement"] = "temperature"
    elif keyDimension == 1:
        keyValue = quantumCrystalIn.attributes["density"]
        quantumCrystalIn.attributes["keyMeasurement"] = "density"
    elif keyDimension == 2:
        keyValue = quantumCrystalIn.attributes["quantumSize"]
        quantumCrystalIn.attributes["keyMeasurement"] = "quantum size"
    elif keyDimension == 3:
        keyValue = fauxMaterial["spectrum"][4]
        quantumCrystalIn.attributes["keyMeasurement"] = "spectrum (channel 4)"
    elif keyDimension == 4:
        keyValue = fauxMaterial["radiationusvh"]
        quantumCrystalIn.attributes["keyMeasurement"] = "radiation"
    else:
        print("Error: mkCrystalProperties(): keyDimension must be between 0 and 4")

    # The value of 'resonanceFreq' will be a quadratic function of the keyValue, with the specified slope and offset

    # resonanceFreq = (slope * keyValue) + offset                # Linear
    resonanceFreq = (a * (keyValue**2)) + (b * keyValue) + c  # Quadratic
    # NOTE, resonance frequency is now a float, rounded to 2 decimal places
    resonanceFreq = round(resonanceFreq, 2)
    quantumCrystalIn.attributes["resonanceFreq"] = resonanceFreq
    quantumCrystalIn.attributes["keyMeasurement"] += " of " + str(keyValue)

    # Return
    return quantumCrystalIn


# Make random properties of a quantum crystal
def mkCrystalPropertiesEasy(
    quantumCrystalIn,
    rng,
    keyDimension: int = 0,
    slope: float = 100.0,
    offset: float = 100,
):
    # Resonance Frequency of the crystal (a set property for a given crystal)
    # quantumCrystalIn.attributes['resonanceFreq'] = 5000                    # The resonance frequency of the crystal
    precision = 2  # Number of decimal places to round to

    # Quantities that the crystal depends on
    quantumCrystalIn.attributes["density"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The density of the crystal (in g/cm^3)
    quantumCrystalIn.attributes["temperatureC"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The temperature of the crystal (in degrees C)
    quantumCrystalIn.attributes["quantumSize"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The quantum size of the crystal (in nm)
    # Add a faux material, with a given radiation and spectrum
    fauxMaterial = {}
    fauxMaterial["radiationusvh"] = round(
        rng.uniform(15.0, 45.0), precision
    )  # The radiation of the crystal (in mSv)
    spectrum = []
    for i in range(0, 5):
        channelValue = round(rng.uniform(15.0, 45.0), precision)
        if (i == 0) or (i == 4):
            spectrum.append(channelValue)
        else:
            spectrum.append(0)
    fauxMaterial["spectrum"] = (
        spectrum  # The spectrum of the crystal (on 5 spectral channels)
    )
    fauxMaterial["microscopeDesc"] = (
        "The quantum gap of this crystal appears to be "
        + str(quantumCrystalIn.attributes["quantumSize"])
        + " nm"
    )  # The description of the crystal under a microscope
    ##quantumCrystalIn.attributes['materials'].append(fauxMaterial)     ## OLD -- adds a new material, so there are two materials (the default, and this one) -- generates lots of bugs with instruments.
    quantumCrystalIn.attributes["materials"] = [
        fauxMaterial
    ]  ## NEW -- replaces the default material with this generated one

    # Pick one dimension (density, temperature, quantumSize, radiation, or spectrum) to be the "key" dimension.  Dimensions are numbered (0, 1, 2, 3, 4)
    keyValue = 0
    # NOTE: These key dimensions are different between Easy and Normal
    if keyDimension == 0:
        keyValue = quantumCrystalIn.attributes["quantumSize"]
        quantumCrystalIn.attributes["keyMeasurement"] = "quantum size"
    elif keyDimension == 1:
        keyValue = quantumCrystalIn.attributes["density"]
        quantumCrystalIn.attributes["keyMeasurement"] = "density"
    elif keyDimension == 2:
        keyValue = fauxMaterial["spectrum"][0]
        quantumCrystalIn.attributes["keyMeasurement"] = "spectrum (channel 0)"
    elif keyDimension == 3:
        keyValue = quantumCrystalIn.attributes["temperatureC"]
        quantumCrystalIn.attributes["keyMeasurement"] = "temperature"
    elif keyDimension == 4:
        keyValue = fauxMaterial["radiationusvh"]
        quantumCrystalIn.attributes["keyMeasurement"] = "radiation"
    else:
        print("Error: mkCrystalProperties(): keyDimension must be between 0 and 4")

    # The value of 'resonanceFreq' will be a linear function of the keyValue, with the specified slope and offset
    resonanceFreq = (slope * keyValue) + offset
    # NOTE, resonance frequency is now a float, rounded to 2 decimal places
    resonanceFreq = round(resonanceFreq, 2)
    quantumCrystalIn.attributes["resonanceFreq"] = resonanceFreq
    quantumCrystalIn.attributes["keyMeasurement"] += " of " + str(keyValue)

    # Return
    return quantumCrystalIn


def mkPlaza(x, y, world):
    # Add statue
    statue = world.createObject("Statue")
    statue.addReadableText("A statue of the colony founder.")
    world.addObject(x + 1, y + 1, Layer.OBJECTS, statue)

    # Create a square that's made out of "Path" tiles
    for i in range(0, 3):
        for j in range(0, 3):
            if not world.hasObj(x + i, y + j, "path"):
                world.addObject(x + i, y + j, Layer.WORLD, world.createObject("Path"))


#
#   Reactor Lab Building
#


def mkReactorLab(x, y, world, rng, randomSeed, scoringInfo):
    # Create a building (science lab)
    # buildingMaker.mkBuildingOneRoom(world, x=x, y=y, width=5, height=5)
    mkBuildingDivided(
        world,
        x=x,
        y=y,
        width=13,
        height=6,
        dividerX=6,
        apertureX=3,
        dividerY=0,
        apertureY=0,
        doorX=3,
        signText="Quantum Reactor Lab",
    )

    instruments = []
    instrumentMicroscope = world.createObject("Microscope")
    instrumentSpectrometer = world.createObject("Spectrometer")
    instrumentRadiationMeter = world.createObject("RadiationMeter")
    instrumentThermometer = world.createObject("Thermometer")
    instrumentDensitometer = world.createObject("Densitometer")
    instruments.append(instrumentDensitometer)
    instruments.append(instrumentSpectrometer)
    instruments.append(instrumentMicroscope)
    instruments.append(instrumentThermometer)
    instruments.append(instrumentRadiationMeter)

    scoringInfo["instruments"] = instruments

    # Shuffle
    rng.shuffle(instruments)

    # Removed: placing instruments on benches; tools are now provided in agent inventory
    for i in range(0, 5):
        bench = world.createObject("Table")
        # bench.addObject( instruments[i] )
        world.addObject(x + 1 + i, y + 1, Layer.FURNITURE, bench)

    # Reactor portion
    quantumCrystals = []
    # keyDimension = rng.randint(0, 4)        # Which dimension (temperature, density, quantum size, radiation, spectrum) will be the "key" dimension that the resonance frequency depends on
    keyDimension = (
        randomSeed % 5
    )  # Makes sure that random seeds 1-5 cycle through all available dimensions
    randomSlope = int(rng.uniform(90, 110))
    randomOffset = int(rng.uniform(90, 110))

    # Store the critical instrument (note, the 0-4 alignment is the same as in mkCrystalProperties)
    scoringInfo["criticalInstrument"] = None
    if keyDimension == 0:
        scoringInfo["criticalInstrument"] = instrumentDensitometer
    elif keyDimension == 1:
        scoringInfo["criticalInstrument"] = instrumentThermometer
    elif keyDimension == 2:
        scoringInfo["criticalInstrument"] = instrumentMicroscope
    elif keyDimension == 3:
        scoringInfo["criticalInstrument"] = instrumentRadiationMeter
    elif keyDimension == 4:
        scoringInfo["criticalInstrument"] = instrumentSpectrometer

    scoringInfo["criticalHypotheses"] = []
    scoringInfo["criticalQuestions"] = []
    # Add the critical hypotheses
    # scoringInfo["criticalHypotheses"].append("The resonance frequency of the quantum crystal is a linear function of the " + scoringInfo['criticalInstrument'].name + " reading.")
    functionStr = (
        "That is, the resonance frequency = ("
        + str(randomSlope)
        + " * "
        + scoringInfo["criticalInstrument"].name
        + " reading) + "
        + str(randomOffset)
        + "."
    )
    scoringInfo["criticalHypotheses"].append(
        "The resonance frequency of the quantum crystal is a linear function of the "
        + scoringInfo["criticalInstrument"].name
        + " reading, with a slope of "
        + str(randomSlope)
        + " and an offset of "
        + str(randomOffset)
        + ". "
        + functionStr
    )

    scoringInfo["criticalQuestions"].append(
        "Does it clearly state that the resonance frequency of the crystals is dependent upon the "
        + scoringInfo["criticalInstrument"].name
        + " reading?"
    )
    scoringInfo["criticalQuestions"].append(
        "Does it clearly state that the relationship is linear, with the crystal resonance frequency = ("
        + str(randomSlope)
        + " * "
        + scoringInfo["criticalInstrument"].name
        + " reading) + "
        + str(randomOffset)
        + " (i.e. a slope of "
        + str(randomSlope)
        + " and an offset of "
        + str(randomOffset)
        + ")?"
    )

    # Generate the quantum crystals
    for i in range(0, 4):
        quantumCrystal = world.createObject("QuantumCrystal")
        # quantumCrystal.attributes['density'] = random.uniform(0.5, 1.5)
        # Make random quantum crystal values
        quantumCrystal = mkCrystalProperties(
            quantumCrystal,
            rng=rng,
            keyDimension=keyDimension,
            slope=randomSlope,
            offset=randomOffset,
        )
        quantumCrystals.append(quantumCrystal)

    scoringInfo["quantumCrystals"] = quantumCrystals

    # Shuffle
    rng.shuffle(quantumCrystals)
    # Give the crystals a number
    for i in range(0, 4):
        quantumCrystals[i].name = "quantum crystal " + str(i + 1)
        # print("Quantum Crystal " + str(i+1) + " resonance frequency: " + str(quantumCrystals[i].attributes['resonanceFreq']) + " Hz")
        scoringInfo["criticalHypotheses"].append(
            "A critical measurement for "
            + quantumCrystals[i].name
            + " is: "
            + str(quantumCrystals[i].attributes["keyMeasurement"])
            + "."
        )
        scoringInfo["criticalHypotheses"].append(
            "The resonance frequency of "
            + quantumCrystals[i].name
            + " is "
            + str(quantumCrystals[i].attributes["resonanceFreq"])
            + " Hz."
        )

    # import time
    # time.sleep(10)
    # exit(1)

    # Add the tables and a quantum crystal reactor to each
    crystalReactors = []
    scoringInfo["reactorsToChange"] = []
    for i in range(0, 4):
        reactorBench = world.createObject("Table")
        reactor = world.createObject("CrystalReactor")
        reactor.setReactorNum(i + 1)
        crystalReactors.append(reactor)
        reactorBench.addObject(reactor)
        # TODO: Set first 2 reactors to appropriate state
        if i < 2:
            # Add a crystal to the contents of this reactor
            reactor.addObject(quantumCrystals[i])
            # Set the reactor to the appropriate frequency
            reactor.attributes["resonanceFreq"] = quantumCrystals[i].attributes[
                "resonanceFreq"
            ]
        else:
            scoringInfo["reactorsToChange"].append(reactor)

        # Note the default resonance frequency
        reactor.attributes["resonanceFreqDefault"] = reactor.attributes["resonanceFreq"]
        # Add the reactor to the bench
        world.addObject(x + 8 + i, y + 2, Layer.FURNITURE, reactorBench)

    scoringInfo["reactors"] = crystalReactors

    # Add the Frequency Estimator device on its own bench; configure relation to match task (linear slope/offset or quadratic)
    if os.environ.get("FREQ_ESTIMATOR", "1") == "1":
        freqBench = world.createObject("Table")
        freqEstimator = FrequencyEstimator(world)
        # configure using same keyDimension and slope/offset as crystals so the device is "correct"
        freqEstimator.attributes["keyDimension"] = keyDimension
        freqEstimator.attributes["_key_mapping_mode"] = (
            "normal"  # Set Normal mode mapping
        )
        freqEstimator.attributes["slope"] = randomSlope
        freqEstimator.attributes["offset"] = randomOffset
        # NOTE: This mapping must match mkCrystalProperties() used in Normal mode
        allowed_map_normal = {
            0: "density",  # Normal: keyDimension 0 → density
            1: "temperatureC",  # Normal: keyDimension 1 → temperature
            2: "quantumSize",  # Normal: keyDimension 2 → quantum size
            3: "radiationusvh",  # Normal: keyDimension 3 → radiation
            4: "spectrum[4]",  # Normal: keyDimension 4 → spectrum channel 4
        }
        key_property = allowed_map_normal.get(keyDimension, "temperatureC")
        freqEstimator.attributes["allowedPropertyKeysHint"] = (
            f"{key_property} (other properties available but not relevant)"
        )
        # build dialog
        relation_desc = (
            "I estimate frequency from the key property using a known relation."
        )
        DialogMaker().mkDialogFrequencyEstimator(freqEstimator, relation_desc)
        freqBench.addObject(freqEstimator)
        world.addObject(x + 6, y + 2, Layer.FURNITURE, freqBench)
        # Mark environment capability
        world.attributes["hasFrequencyEstimator"] = True
    else:
        world.attributes["hasFrequencyEstimator"] = False

    # Put the other 2 quantum crystals on tables on the other side of the room
    for i in range(0, 2):
        bench = world.createObject("Table")
        bench.addObject(quantumCrystals[i + 2])
        world.addObject(x + 4 + i, y + 4, Layer.FURNITURE, bench)

    # Add the generator
    mkGenerator(x + 8, y + 1, world, linkedObjects=crystalReactors, reactorLength=3)

    # Add a radioactive check source
    # world.addObject(x+6, y+1, Layer.OBJECTS, world.createObject("radioactivechecksource"))

    # Add NPK meter
    # world.addObject(x+5, y+4, Layer.OBJECTS, world.createObject("NPKMeter"))


#
#   Reactor Lab Scenario
#
def makeScenarioReactorLab(world, numUserAgents=1):
    scoringInfo = {}
    scoringInfo["criticalHypotheses"] = []
    scoringInfo["criticalQuestions"] = []

    # Set a limit for the number of user agents
    MAX_NUM_AGENTS = 3
    if numUserAgents > MAX_NUM_AGENTS:
        numUserAgents = MAX_NUM_AGENTS

    # Populate with structures/objects

    # Fill with grass
    mkGrassFill(world)
    # Randomly place a few plants (plant1, plant2, plant3)
    for i in range(0, 10):
        randX = world.rng.randint(0, world.sizeX - 1)
        randY = world.rng.randint(0, world.sizeY - 1)

    # Buildings
    # mkHouse(4, 4, world)

    # Reactor Lab
    mkReactorLab(
        10,
        15,
        world,
        rng=world.rng,
        randomSeed=world.randomSeed,
        scoringInfo=scoringInfo,
    )

    # Plaza
    mkPlaza(15, 22, world)

    # Paths
    mkPathX(10, 23, 5, world)
    mkPathX(18, 23, 5, world)
    mkPathY(16, 25, 5, world)  # Down from plaza
    mkPathY(13, 21, 2, world)  # Down from plaza

    # Trees
    mkTallTree(9, 23, world)
    mkTallTree(23, 23, world)

    mkTallTree(9, 20, world)
    mkTallTree(23, 20, world)

    mkTallTree(9, 17, world)
    mkTallTree(23, 17, world)

    # Fences
    # Top-left corner
    mkFenceY(6, 12, 14, world)
    mkFenceX(6, 12, 20, world)

    mkFenceY(26, 12, 14, world)

    mkFenceX(6, 25, 9, world)
    mkFenceX(18, 25, 9, world)

    # Add big village sign
    mkSignVillage(15, 27, world)

    # Add some plants
    world.addObject(15, 1, Layer.OBJECTS, world.createObject("PlantGeneric"))

    plantCount = 0
    minPlants = 15
    while plantCount < minPlants:
        # Pick a random location
        randX = world.rng.randint(0, world.sizeX - 1)
        randY = world.rng.randint(0, world.sizeY - 1)

        # Check to see if there are any objects other than grass there
        objs = world.getObjectsAt(randX, randY)
        # Get types of objects
        objTypes = [obj.type for obj in objs]
        # Check to see that there is grass here
        if "grass" in objTypes:
            # Check that there is not other things here
            if len(objTypes) == 1:
                # Add a plant
                world.addObject(
                    randX, randY, Layer.OBJECTS, world.createObject("PlantGeneric")
                )
                plantCount += 1

    # DialogMaker
    dialogMaker = DialogMaker()

    # Add some number of user agents
    for userAgentIdx in range(0, numUserAgents):
        userAgent = Agent(world)
        # TODO: Add starting tools for agent
        # userAgent.addObject(world.createObject("Shovel"))
        # userAgent.addObject(world.createObject("Seed"))
        # Provide science instruments directly in inventory for immediate use
        userAgent.addObject(world.createObject("Microscope"))
        userAgent.addObject(world.createObject("Spectrometer"))
        userAgent.addObject(world.createObject("RadiationMeter"))
        userAgent.addObject(world.createObject("Thermometer"))
        userAgent.addObject(world.createObject("Densitometer"))
        # Add the agent to a specfic location
        # world.addObject(14+userAgentIdx, 14, Layer.AGENT, userAgent)      # In farm field
        world.addObject(12 + userAgentIdx, 18, Layer.AGENT, userAgent)  # Near farm
        # Register the agent with the World so we can keep track of it
        world.addAgent(userAgent)

    # Add teleport locations to world
    # TODO
    world.addTeleportLocation("science lab (instruments)", 13, 17)
    world.addTeleportLocation("science lab (crystal bench)", 14, 18)
    world.addTeleportLocation("reactor lab", 20, 18)

    # Return scoring info
    return scoringInfo


#
#   Reactor Lab (Easy/Distilled version)
#


def mkReactorLabEasy(x, y, world, rng, randomSeed, scoringInfo):
    # Create a building (science lab)
    # buildingMaker.mkBuildingOneRoom(world, x=x, y=y, width=5, height=5)
    # mkBuildingDivided(world, x=x, y=y, width=13, height=6, dividerX=6, apertureX=3, dividerY=0, apertureY=0, doorX=3, signText="Quantum Reactor Lab")
    mkBuildingOneRoom(
        world,
        x=x,
        y=y,
        width=5,
        height=6,
        signText="Quantum Reactor Lab",
        doorKeyID=123,
    )

    instruments = []
    instrumentMicroscope = world.createObject("Microscope")
    instrumentSpectrometer = world.createObject("Spectrometer")
    instrumentRadiationMeter = world.createObject("RadiationMeter")
    instrumentThermometer = world.createObject("Thermometer")
    instrumentDensitometer = world.createObject("Densitometer")
    instruments.append(instrumentDensitometer)
    instruments.append(instrumentSpectrometer)
    instruments.append(instrumentMicroscope)
    instruments.append(instrumentThermometer)
    instruments.append(instrumentRadiationMeter)

    scoringInfo["instruments"] = instruments

    # Shuffle
    rng.shuffle(instruments)

    # Add the tables and an instrument to each
    # for i in range(0, 5):
    #    bench = world.createObject("Table")
    #    bench.addObject( instruments[i] )
    #    world.addObject(x+1+i, y+4, Layer.FURNITURE, bench)

    # Reactor portion
    quantumCrystals = []
    # keyDimension = rng.randint(0, 4)        # Which dimension (temperature, density, quantum size, radiation, spectrum) will be the "key" dimension that the resonance frequency depends on
    keyDimension = (
        randomSeed % 5
    )  # Makes sure that random seeds 1-5 cycle through all available dimensions
    randomSlope = int(rng.uniform(50, 80))
    # randomOffset = int(rng.uniform(20, 50))
    randomOffset = 0

    # Store the critical instrument (note, the 0-4 alignment is the same as in mkCrystalProperties)
    scoringInfo["criticalInstrument"] = None
    if keyDimension == 0:
        scoringInfo["criticalInstrument"] = instrumentMicroscope
    elif keyDimension == 1:
        scoringInfo["criticalInstrument"] = instrumentDensitometer
    elif keyDimension == 2:
        scoringInfo["criticalInstrument"] = instrumentSpectrometer
    elif keyDimension == 3:
        scoringInfo["criticalInstrument"] = instrumentThermometer
    elif keyDimension == 4:
        scoringInfo["criticalInstrument"] = instrumentRadiationMeter

    # Removed: placing the single critical instrument on a bench; tools are now provided in agent inventory
    bench = world.createObject("Table")
    # bench.addObject( scoringInfo["criticalInstrument"] )
    world.addObject(x + 1, y + 4, Layer.FURNITURE, bench)

    scoringInfo["criticalHypotheses"] = []
    scoringInfo["criticalQuestions"] = []
    # Add the critical hypotheses
    # scoringInfo["criticalHypotheses"].append("The resonance frequency of the quantum crystal is a linear function of the " + scoringInfo['criticalInstrument'].name + " reading.")
    functionStr = (
        "That is, the resonance frequency = ("
        + str(randomSlope)
        + " * "
        + scoringInfo["criticalInstrument"].name
        + " reading) + "
        + str(randomOffset)
        + "."
    )
    scoringInfo["criticalHypotheses"].append(
        "The resonance frequency of the quantum crystal is a linear function of the "
        + scoringInfo["criticalInstrument"].name
        + " reading, with a slope of "
        + str(randomSlope)
        + " and an offset of "
        + str(randomOffset)
        + ". "
        + functionStr
    )

    scoringInfo["criticalQuestions"].append(
        "Does it clearly state that the resonance frequency of the crystals is dependent upon the "
        + scoringInfo["criticalInstrument"].name
        + " reading?"
    )
    scoringInfo["criticalQuestions"].append(
        "Does it clearly state that the relationship is linear, with the crystal resonance frequency = ("
        + str(randomSlope)
        + " * "
        + scoringInfo["criticalInstrument"].name
        + " reading) "
        + " (i.e. a slope of "
        + str(randomSlope)
        + ", and no offset)?"
    )

    # Generate the quantum crystals
    for i in range(0, 3):
        quantumCrystal = world.createObject("QuantumCrystal")
        # quantumCrystal.attributes['density'] = random.uniform(0.5, 1.5)
        # Make random quantum crystal values
        quantumCrystal = mkCrystalPropertiesEasy(
            quantumCrystal,
            rng=rng,
            keyDimension=keyDimension,
            slope=randomSlope,
            offset=randomOffset,
        )
        quantumCrystals.append(quantumCrystal)

    scoringInfo["quantumCrystals"] = quantumCrystals

    # Shuffle
    rng.shuffle(quantumCrystals)
    # Give the crystals a number
    for i in range(0, 3):
        quantumCrystals[i].name = "quantum crystal " + str(i + 1)
        # print("Quantum Crystal " + str(i+1) + " resonance frequency: " + str(quantumCrystals[i].attributes['resonanceFreq']) + " Hz")
        scoringInfo["criticalHypotheses"].append(
            "A critical measurement for "
            + quantumCrystals[i].name
            + " is: "
            + str(quantumCrystals[i].attributes["keyMeasurement"])
            + "."
        )
        scoringInfo["criticalHypotheses"].append(
            "The resonance frequency of "
            + quantumCrystals[i].name
            + " is "
            + str(quantumCrystals[i].attributes["resonanceFreq"])
            + " Hz."
        )
    # import time
    # time.sleep(10)
    # exit(1)

    # Add the tables and a quantum crystal reactor to each
    crystalReactors = []
    scoringInfo["reactorsToChange"] = []
    for i in range(0, 3):
        reactorBench = world.createObject("Table")
        reactor = world.createObject("CrystalReactor")
        reactor.setReactorNum(i + 1)
        crystalReactors.append(reactor)
        reactorBench.addObject(reactor)
        # TODO: Set first 2 reactors to appropriate state
        if i < 2:
            # Add a crystal to the contents of this reactor
            reactor.addObject(quantumCrystals[i])
            # Set the reactor to the appropriate frequency
            reactor.attributes["resonanceFreq"] = quantumCrystals[i].attributes[
                "resonanceFreq"
            ]
        else:
            scoringInfo["reactorsToChange"].append(reactor)

        # Note the default resonance frequency
        reactor.attributes["resonanceFreqDefault"] = reactor.attributes["resonanceFreq"]
        # Add the reactor to the bench
        world.addObject(x + 1 + i, y + 2, Layer.FURNITURE, reactorBench)

    scoringInfo["reactors"] = crystalReactors

    # Add the Frequency Estimator device for Easy mode (use task relation)
    if os.environ.get("FREQ_ESTIMATOR", "1") == "1":
        freqBench = world.createObject("Table")
        freqEstimator = FrequencyEstimator(world)
        freqEstimator.attributes["keyDimension"] = keyDimension
        freqEstimator.attributes["_key_mapping_mode"] = "easy"  # Set Easy mode mapping
        # Easy uses linear with zero offset in this setup
        freqEstimator.attributes["slope"] = randomSlope
        freqEstimator.attributes["offset"] = randomOffset
        # Easy mode: restrict allowed keys to the single keyDimension
        # NOTE: This mapping must match mkCrystalPropertiesEasy()
        allowed_map_easy = {
            0: "quantumSize",  # Easy: keyDimension 0 → quantum size
            1: "density",  # Easy: keyDimension 1 → density
            2: "spectrum[0]",  # Easy: keyDimension 2 → spectrum channel 0
            3: "temperatureC",  # Easy: keyDimension 3 → temperature
            4: "radiationusvh",  # Easy: keyDimension 4 → radiation
        }
        freqEstimator.attributes["allowedPropertyKeysHint"] = allowed_map_easy.get(
            keyDimension, "temperatureC"
        )
        DialogMaker().mkDialogFrequencyEstimator(
            freqEstimator, "Provide properties JSON to estimate frequency (Easy)."
        )
        freqBench.addObject(freqEstimator)
        world.addObject(x + 3, y + 2, Layer.FURNITURE, freqBench)
        world.attributes["hasFrequencyEstimator"] = True
    else:
        world.attributes["hasFrequencyEstimator"] = False

    # Put the other 2 quantum crystals on tables on the other side of the room
    for i in range(0, 1):
        bench = world.createObject("Table")
        bench.addObject(quantumCrystals[i + 2])
        world.addObject(x + 3 + i, y + 4, Layer.FURNITURE, bench)

    # Add the generator
    mkGenerator(x + 1, y + 1, world, linkedObjects=crystalReactors, reactorLength=2)

    # Add a radioactive check source
    # world.addObject(x+6, y+1, Layer.OBJECTS, world.createObject("radioactivechecksource"))

    # Add NPK meter
    # world.addObject(x+5, y+4, Layer.OBJECTS, world.createObject("NPKMeter"))


def makeScenarioReactorLabEasy(world, numUserAgents=1):
    scoringInfo = {}
    scoringInfo["criticalHypotheses"] = []
    scoringInfo["criticalQuestions"] = []

    # Set a limit for the number of user agents
    MAX_NUM_AGENTS = 3
    if numUserAgents > MAX_NUM_AGENTS:
        numUserAgents = MAX_NUM_AGENTS

    # Populate with structures/objects

    # Fill with grass
    mkGrassFill(world)
    # Randomly place a few plants (plant1, plant2, plant3)
    for i in range(0, 10):
        randX = world.rng.randint(0, world.sizeX - 1)
        randY = world.rng.randint(0, world.sizeY - 1)

    # Buildings
    # mkHouse(4, 4, world)

    # Reactor Lab
    mkReactorLabEasy(
        14,
        15,
        world,
        rng=world.rng,
        randomSeed=world.randomSeed,
        scoringInfo=scoringInfo,
    )

    # Plaza
    mkPlaza(15, 22, world)

    # Paths
    mkPathX(10, 23, 5, world)
    mkPathX(18, 23, 5, world)
    mkPathY(16, 21, 1, world)  # Down from building
    mkPathY(16, 25, 5, world)  # Down from plaza

    # Trees
    mkTallTree(9, 23, world)
    mkTallTree(23, 23, world)

    mkTallTree(9, 20, world)
    mkTallTree(23, 20, world)

    mkTallTree(9, 17, world)
    mkTallTree(23, 17, world)

    # Fences
    # Top-left corner
    mkFenceY(6, 12, 14, world)
    mkFenceX(6, 12, 20, world)

    mkFenceY(26, 12, 14, world)

    mkFenceX(6, 25, 9, world)
    mkFenceX(18, 25, 9, world)

    # Add big village sign
    mkSignVillage(15, 27, world)

    # Add some plants
    world.addObject(15, 1, Layer.OBJECTS, world.createObject("PlantGeneric"))

    plantCount = 0
    minPlants = 15
    while plantCount < minPlants:
        # Pick a random location
        randX = world.rng.randint(0, world.sizeX - 1)
        randY = world.rng.randint(0, world.sizeY - 1)

        # Check to see if there are any objects other than grass there
        objs = world.getObjectsAt(randX, randY)
        # Get types of objects
        objTypes = [obj.type for obj in objs]
        # Check to see that there is grass here
        if "grass" in objTypes:
            # Check that there is not other things here
            if len(objTypes) == 1:
                # Add a plant
                world.addObject(
                    randX, randY, Layer.OBJECTS, world.createObject("PlantGeneric")
                )
                plantCount += 1

    # DialogMaker
    dialogMaker = DialogMaker()

    # Add some number of user agents
    for userAgentIdx in range(0, numUserAgents):
        userAgent = Agent(world)
        # TODO: Add starting tools for agent
        # userAgent.addObject(world.createObject("Shovel"))
        # userAgent.addObject(world.createObject("Seed"))
        # Provide only the single critical instrument in inventory for immediate use
        if ("criticalInstrument" in scoringInfo) and (
            scoringInfo["criticalInstrument"] is not None
        ):
            userAgent.addObject(scoringInfo["criticalInstrument"])
        # Add the agent to a specfic location
        world.addObject(
            16 + userAgentIdx, 18, Layer.AGENT, userAgent
        )  # Middle of reactor room
        # Register the agent with the World so we can keep track of it
        world.addAgent(userAgent)

    # Add teleport locations to world
    # TODO
    world.addTeleportLocation("start location", 16, 18)

    # Return scoring info
    return scoringInfo


#
#   Challenge
#


def mkReactorLabChallenge(x, y, world, rng, randomSeed, scoringInfo):
    # Create a building (science lab)
    # buildingMaker.mkBuildingOneRoom(world, x=x, y=y, width=5, height=5)
    mkBuildingDivided(
        world,
        x=x,
        y=y,
        width=13,
        height=6,
        dividerX=6,
        apertureX=3,
        dividerY=0,
        apertureY=0,
        doorX=3,
        signText="Quantum Reactor Lab",
    )

    instruments = []
    instrumentMicroscope = world.createObject("Microscope")
    instrumentSpectrometer = world.createObject("Spectrometer")
    instrumentRadiationMeter = world.createObject("RadiationMeter")
    instrumentThermometer = world.createObject("Thermometer")
    instrumentDensitometer = world.createObject("Densitometer")
    instruments.append(instrumentDensitometer)
    instruments.append(instrumentSpectrometer)
    instruments.append(instrumentMicroscope)
    instruments.append(instrumentThermometer)
    instruments.append(instrumentRadiationMeter)

    scoringInfo["instruments"] = instruments

    # Shuffle
    rng.shuffle(instruments)

    # Removed: placing instruments on benches; tools are now provided in agent inventory
    for i in range(0, 5):
        bench = world.createObject("Table")
        # bench.addObject( instruments[i] )
        world.addObject(x + 1 + i, y + 1, Layer.FURNITURE, bench)

    # Reactor portion
    quantumCrystals = []
    # keyDimension = rng.randint(0, 4)        # Which dimension (temperature, density, quantum size, radiation, spectrum) will be the "key" dimension that the resonance frequency depends on
    keyDimension = (
        randomSeed % 5
    )  # Makes sure that random seeds 1-5 cycle through all available dimensions

    # Store the critical instrument (note, the 0-4 alignment is the same as in mkCrystalProperties)
    scoringInfo["criticalInstrument"] = None
    if keyDimension == 0:
        scoringInfo["criticalInstrument"] = instrumentThermometer
    elif keyDimension == 1:
        scoringInfo["criticalInstrument"] = instrumentDensitometer
    elif keyDimension == 2:
        scoringInfo["criticalInstrument"] = instrumentMicroscope
    elif keyDimension == 3:
        scoringInfo["criticalInstrument"] = instrumentSpectrometer
    elif keyDimension == 4:
        scoringInfo["criticalInstrument"] = instrumentRadiationMeter

    done = False
    while not done:
        done = True
        quantumCrystals = []
        randomA = int(rng.uniform(10, 20))
        randomB = int(rng.uniform(20, 40))
        randomC = int(rng.uniform(20, 850))

        # Generate the quantum crystals
        for i in range(0, 5):
            quantumCrystal = world.createObject("QuantumCrystal")
            # quantumCrystal.attributes['density'] = random.uniform(0.5, 1.5)
            # Make random quantum crystal values
            quantumCrystal = mkCrystalPropertiesQuadratic(
                quantumCrystal,
                rng=rng,
                keyDimension=keyDimension,
                a=randomA,
                b=randomB,
                c=randomC,
            )
            quantumCrystals.append(quantumCrystal)

            # Check to see if the resonance frequency is out of range, and should be regenerated
            if (quantumCrystal.attributes["resonanceFreq"] < 500.0) or (
                quantumCrystal.attributes["resonanceFreq"] >= 9999.0
            ):
                print("Crystal out of range -- regenerating")
                done = False
                break
            print(
                "Crystal in range: " + str(quantumCrystal.attributes["resonanceFreq"])
            )

    scoringInfo["quantumCrystals"] = quantumCrystals

    # Critical hypothesis
    scoringInfo["criticalHypotheses"] = []
    scoringInfo["criticalQuestions"] = []
    # Add the critical hypotheses
    functionStr = (
        "That is, the resonance frequency = "
        + str(randomA)
        + " * ("
        + scoringInfo["criticalInstrument"].name
        + " reading)^2 + "
        + str(randomB)
        + " * "
        + scoringInfo["criticalInstrument"].name
        + " reading + "
        + str(randomC)
        + "."
    )
    criticalHypothesis = (
        "The resonance frequency of the quantum crystal is a quadtratic function of the "
        + scoringInfo["criticalInstrument"].name
        + " reading, "
    )
    criticalHypothesis += (
        "of the form `y = a*x^2 + b*x + c`, where `a` is "
        + str(randomA)
        + ", `b` is "
        + str(randomB)
        + ", and `c` is "
        + str(randomC)
        + ". "
    )
    criticalHypothesis += functionStr
    scoringInfo["criticalHypotheses"].append(criticalHypothesis)

    scoringInfo["criticalQuestions"].append(
        "Does it clearly state that the resonance frequency of the crystals is dependent upon the "
        + scoringInfo["criticalInstrument"].name
        + " reading?"
    )
    scoringInfo["criticalQuestions"].append(
        "Does it clearly state that the relationship is quadratic, with the crystal resonance frequency = ("
        + str(randomA)
        + " * "
        + scoringInfo["criticalInstrument"].name
        + " reading)^2 + ("
        + str(randomB)
        + " * "
        + scoringInfo["criticalInstrument"].name
        + " reading) + "
        + str(randomC)
        + " (i.e. `y = a*x^2 + b*x + c`, with `a` = "
        + str(randomA)
        + ", `b` = "
        + str(randomB)
        + ", and `c` = "
        + str(randomC)
        + ")?"
    )

    # Shuffle
    rng.shuffle(quantumCrystals)
    # Give the crystals a number
    for i in range(0, 5):
        quantumCrystals[i].name = "quantum crystal " + str(i + 1)
        # print("Quantum Crystal " + str(i+1) + " resonance frequency: " + str(quantumCrystals[i].attributes['resonanceFreq']) + " Hz")
        scoringInfo["criticalHypotheses"].append(
            "A critical measurement for "
            + quantumCrystals[i].name
            + " is: "
            + str(quantumCrystals[i].attributes["keyMeasurement"])
            + "."
        )
        scoringInfo["criticalHypotheses"].append(
            "The resonance frequency of "
            + quantumCrystals[i].name
            + " is "
            + str(quantumCrystals[i].attributes["resonanceFreq"])
            + " Hz."
        )
    # import time
    # time.sleep(10)
    # exit(1)

    # Add the tables and a quantum crystal reactor to each
    crystalReactors = []
    scoringInfo["reactorsToChange"] = []
    for i in range(0, 5):
        reactorBench = world.createObject("Table")
        reactor = world.createObject("CrystalReactor")
        reactor.setReactorNum(i + 1)
        crystalReactors.append(reactor)
        reactorBench.addObject(reactor)
        # TODO: Set first 3 reactors to appropriate state
        if i < 3:
            # Add a crystal to the contents of this reactor
            reactor.addObject(quantumCrystals[i])
            # Set the reactor to the appropriate frequency
            reactor.attributes["resonanceFreq"] = quantumCrystals[i].attributes[
                "resonanceFreq"
            ]
        else:
            scoringInfo["reactorsToChange"].append(reactor)

        # Note the default resonance frequency
        reactor.attributes["resonanceFreqDefault"] = reactor.attributes["resonanceFreq"]
        # Add the reactor to the bench
        world.addObject(x + 7 + i, y + 2, Layer.FURNITURE, reactorBench)

    scoringInfo["reactors"] = crystalReactors

    # Add the Frequency Estimator device for Challenge mode (quadratic)
    if os.environ.get("FREQ_ESTIMATOR", "1") == "1":
        freqBench = world.createObject("Table")
        freqEstimator = FrequencyEstimator(world)
        freqEstimator.attributes["keyDimension"] = keyDimension
        freqEstimator.attributes["_key_mapping_mode"] = (
            "challenge"  # Set Challenge mode mapping
        )
        freqEstimator.attributes["a"] = randomA
        freqEstimator.attributes["b"] = randomB
        freqEstimator.attributes["c"] = randomC
        # NOTE: This mapping must match mkCrystalPropertiesQuadratic() used in Challenge mode
        allowed_map_challenge = {
            0: "temperatureC",  # Challenge: keyDimension 0 → temperature
            1: "density",  # Challenge: keyDimension 1 → density
            2: "quantumSize",  # Challenge: keyDimension 2 → quantum size
            3: "spectrum[4]",  # Challenge: keyDimension 3 → spectrum channel 4
            4: "radiationusvh",  # Challenge: keyDimension 4 → radiation
        }
        key_property = allowed_map_challenge.get(keyDimension, "temperatureC")
        freqEstimator.attributes["allowedPropertyKeysHint"] = (
            f"{key_property} (quadratic relation)"
        )
        DialogMaker().mkDialogFrequencyEstimator(
            freqEstimator,
            "Quadratic estimator: y = a*x^2 + b*x + c. Provide properties JSON.",
        )
        freqBench.addObject(freqEstimator)
        world.addObject(x + 6, y + 2, Layer.FURNITURE, freqBench)
        world.attributes["hasFrequencyEstimator"] = True
    else:
        world.attributes["hasFrequencyEstimator"] = False

    # Put the other 2 quantum crystals on tables on the other side of the room
    for i in range(0, 2):
        bench = world.createObject("Table")
        bench.addObject(quantumCrystals[i + 3])
        world.addObject(x + 4 + i, y + 4, Layer.FURNITURE, bench)

    # Add the generator
    mkGenerator(x + 7, y + 1, world, linkedObjects=crystalReactors, reactorLength=4)

    # Add a radioactive check source
    # world.addObject(x+6, y+1, Layer.OBJECTS, world.createObject("radioactivechecksource"))

    # Add NPK meter
    # world.addObject(x+5, y+4, Layer.OBJECTS, world.createObject("NPKMeter"))


#
#   Reactor Lab Scenario
#
def makeScenarioReactorLabChallenge(world, numUserAgents=1):
    scoringInfo = {}
    scoringInfo["criticalHypotheses"] = []
    scoringInfo["criticalQuestions"] = []

    # Set a limit for the number of user agents
    MAX_NUM_AGENTS = 3
    if numUserAgents > MAX_NUM_AGENTS:
        numUserAgents = MAX_NUM_AGENTS

    # Populate with structures/objects

    # Fill with grass
    mkGrassFill(world)
    # Randomly place a few plants (plant1, plant2, plant3)
    for i in range(0, 10):
        randX = world.rng.randint(0, world.sizeX - 1)
        randY = world.rng.randint(0, world.sizeY - 1)

    # Buildings
    # mkHouse(4, 4, world)

    # Reactor Lab
    mkReactorLabChallenge(
        10,
        15,
        world,
        rng=world.rng,
        randomSeed=world.randomSeed,
        scoringInfo=scoringInfo,
    )

    # Plaza
    mkPlaza(15, 22, world)

    # Paths
    mkPathX(10, 23, 5, world)
    mkPathX(18, 23, 5, world)
    mkPathY(16, 25, 5, world)  # Down from plaza
    mkPathY(13, 21, 2, world)  # Down from plaza

    # Trees
    mkTallTree(9, 23, world)
    mkTallTree(23, 23, world)

    mkTallTree(9, 20, world)
    mkTallTree(23, 20, world)

    mkTallTree(9, 17, world)
    mkTallTree(23, 17, world)

    # Fences
    # Top-left corner
    mkFenceY(6, 12, 14, world)
    mkFenceX(6, 12, 20, world)

    mkFenceY(26, 12, 14, world)

    mkFenceX(6, 25, 9, world)
    mkFenceX(18, 25, 9, world)

    # Add big village sign
    mkSignVillage(15, 27, world)

    # Add some plants
    world.addObject(15, 1, Layer.OBJECTS, world.createObject("PlantGeneric"))

    plantCount = 0
    minPlants = 15
    while plantCount < minPlants:
        # Pick a random location
        randX = world.rng.randint(0, world.sizeX - 1)
        randY = world.rng.randint(0, world.sizeY - 1)

        # Check to see if there are any objects other than grass there
        objs = world.getObjectsAt(randX, randY)
        # Get types of objects
        objTypes = [obj.type for obj in objs]
        # Check to see that there is grass here
        if "grass" in objTypes:
            # Check that there is not other things here
            if len(objTypes) == 1:
                # Add a plant
                world.addObject(
                    randX, randY, Layer.OBJECTS, world.createObject("PlantGeneric")
                )
                plantCount += 1

    # DialogMaker
    dialogMaker = DialogMaker()

    # Add some number of user agents
    for userAgentIdx in range(0, numUserAgents):
        userAgent = Agent(world)
        # TODO: Add starting tools for agent
        # userAgent.addObject(world.createObject("Shovel"))
        # userAgent.addObject(world.createObject("Seed"))
        # Provide science instruments directly in inventory for immediate use
        userAgent.addObject(world.createObject("Microscope"))
        userAgent.addObject(world.createObject("Spectrometer"))
        userAgent.addObject(world.createObject("RadiationMeter"))
        userAgent.addObject(world.createObject("Thermometer"))
        userAgent.addObject(world.createObject("Densitometer"))
        # Add the agent to a specfic location
        # world.addObject(14+userAgentIdx, 14, Layer.AGENT, userAgent)      # In farm field
        world.addObject(12 + userAgentIdx, 18, Layer.AGENT, userAgent)  # Near farm
        # Register the agent with the World so we can keep track of it
        world.addAgent(userAgent)

    # Add teleport locations to world
    # TODO
    world.addTeleportLocation("science lab (instruments)", 13, 17)
    world.addTeleportLocation("science lab (crystal bench)", 14, 18)
    world.addTeleportLocation("reactor lab", 20, 18)

    # Return scoring info
    return scoringInfo


#
#   Reactor Lab with Causal Relationships (T->F, T->M)
#   This scenario demonstrates the extensible causal graph framework
#


def mkReactorLabCausal(x, y, world, rng, randomSeed, scoringInfo, config=None):
    """
    Create a causal discovery lab with configurable causal relationships.

    The causal structure can be specified in multiple ways (priority order):
    1. Environment variable CAUSAL_GRAPH_CONFIG: Path to JSON config file
    2. Environment variable CAUSAL_GRAPH_ID: Load from default config directory
    3. Legacy environment variables (CAUSAL_T_REF, CAUSAL_F_0, etc.)
    4. config parameter: CausalConfig object
    5. randomSeed: Seed-based generation
    6. Default: Random generation

    Example environment variable usage:
        export CAUSAL_GRAPH_CONFIG="/path/to/chain_3_nodes.json"
        # Or use a graph ID from the configs directory:
        export CAUSAL_GRAPH_ID="fork_3_nodes"

    Args:
        x, y: Position for the lab
        world: World object
        rng: Random number generator
        randomSeed: Random seed
        scoringInfo: Dictionary for scoring information
        config: Optional CausalConfig object for manual parameter specification
    """
    # Create a building (single room lab)
    mkBuildingOneRoom(
        world,
        x=x,
        y=y,
        width=5,
        height=6,
        signText="Causal Discovery Lab",
        doorKeyID=124,
    )

    # Create the causal graph with multiple configuration options
    # Priority: CAUSAL_GRAPH_CONFIG env var > CAUSAL_GRAPH_ID > legacy env vars > config param > seed-based > random

    causal_graph = None
    graph_source = "unknown"

    # Check for configuration file path in environment
    if os.environ.get("CAUSAL_GRAPH_CONFIG"):
        config_path = os.environ["CAUSAL_GRAPH_CONFIG"]
        try:
            causal_graph = load_causal_graph_from_file(config_path, rng)
            graph_source = f"config_file:{config_path}"
            print(f"[mkReactorLabCausal] Loaded causal graph from: {config_path}")
            print(f"[mkReactorLabCausal] Graph ID: {causal_graph.graph_id}")
            print(f"[mkReactorLabCausal] Description: {causal_graph.description}")
        except Exception as e:
            print(f"[mkReactorLabCausal] Error loading config file {config_path}: {e}")
            print(f"[mkReactorLabCausal] Falling back to default configuration")

    # Check for graph ID in environment (load from default configs directory)
    if causal_graph is None and os.environ.get("CAUSAL_GRAPH_ID"):
        print(111111)
        graph_id = os.environ["CAUSAL_GRAPH_ID"]
        # Try to find config file in default directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(os.path.dirname(script_dir))
        config_path = os.path.join(
            repo_root, "causal_graph_configs", f"{graph_id}.json"
        )

        if os.path.exists(config_path):
            try:
                print(222222)
                causal_graph = load_causal_graph_from_file(config_path, rng)
                graph_source = f"graph_id:{graph_id}"
                print(f"[mkReactorLabCausal] Loaded causal graph by ID: {graph_id}")
                print(f"[mkReactorLabCausal] Description: {causal_graph.description}")
            except Exception as e:
                print(f"[mkReactorLabCausal] Error loading graph ID {graph_id}: {e}")
        else:
            print(
                f"[mkReactorLabCausal] Config file not found for graph ID: {graph_id}"
            )
            print(f"[mkReactorLabCausal] Expected path: {config_path}")

    counterfactual_mode = os.environ.get("COUNTERFACTUAL", "false").lower() == "true"

    # Store causal graph info in scoringInfo for reference
    scoringInfo["causalGraph"] = causal_graph
    scoringInfo["causalGraphSource"] = graph_source
    scoringInfo["causalRelationships"] = causal_graph.get_causal_description()
    scoringInfo["counterfactualMode"] = counterfactual_mode

    # Dynamically create instruments based on observable properties
    # Map property names to instrument types
    property_to_instrument = {
        "temperatureC": "Thermometer",
        "moisture": "MoistureMeter",
        "density": "Densitometer",
        "quantumSize": "Microscope",
        "resonanceFreq": "Spectrometer",
        "radiation": "RadiationMeter",
        "pressure": "PressureMeter",  # Can reuse for pressure measurements
        "ph": "PHMeter",  # Can reuse for pH measurements
        "conductivity": "ConductivityMeter",  # Can reuse for conductivity measurements
    }

    instruments = []
    instrument_types = []  # Store the capitalized class names for creating instruments

    # Create instruments for observable properties
    for node_name, node_config in causal_graph.nodes.items():
        is_observable = causal_graph.node_observable.get(node_name, True)
        if is_observable:
            property_name = causal_graph.node_property_mapping.get(node_name, node_name)
            instrument_type = property_to_instrument.get(property_name)

            if instrument_type:
                instrument = world.createObject(instrument_type)
                instruments.append(instrument)
                instrument_types.append(
                    instrument_type
                )  # Store the capitalized class name
                print(
                    f"[mkReactorLabCausal] Created {instrument_type} for observable property: {property_name}"
                )
            else:
                print(
                    f"[mkReactorLabCausal] Warning: No instrument type found for property: {property_name}"
                )

    scoringInfo["instruments"] = instruments
    scoringInfo["instrumentTypes"] = instrument_types  # Store for creating copies later

    # Instruments will be provided in agent inventory (no bench needed)
    # instrument_bench_items will be added to agent inventory in makeScenarioReactorLabCausal()

    # Generate only two crystals: one for PropertyManipulator and one for Reactor
    # They should have different properties based on ENV_SEED
    # Get ENV_SEED from environment variable (default to 1 if not set)
    env_seed = int(os.environ.get("ENV_SEED", "1"))

    # Identify controllable properties in the causal graph
    controllable_properties = {}
    for node_name, node in causal_graph.nodes.items():
        if node.is_controllable:
            # Get the property name (use node_property_mapping if available)
            prop_name = (
                causal_graph.node_property_mapping.get(node_name, node_name)
                if hasattr(causal_graph, "node_property_mapping")
                and causal_graph.node_property_mapping
                else node_name
            )
            controllable_properties[node_name] = prop_name

    hard_presets = get_hard_quadratic_presets(causal_graph)
    if hard_presets is not None:
        prop_manip_override = dict(hard_presets["property_manipulator"])
        reactor_override = dict(hard_presets["reactor"])
    else:
        # Generate property values for propManipCrystal (0-100 integers)
        prop_manip_override = {}
        for node_name in controllable_properties.keys():
            # Generate different values for each property based on ENV_SEED
            # Use a hash-like approach to get different values for each property
            prop_seed = env_seed * 1000 + hash(node_name) % 1000
            prop_rng_local = random.Random(prop_seed)
            prop_manip_override[node_name] = prop_rng_local.randint(0, 100)

        # Generate property values for reactorCrystal (0-100 integers, different from propManipCrystal)
        reactor_override = {}
        for node_name in controllable_properties.keys():
            # Generate different values for each property based on ENV_SEED
            # Offset by a large number to ensure different values
            prop_seed = env_seed * 1000 + hash(node_name) % 1000 + 50000
            prop_rng_local = random.Random(prop_seed)
            reactor_override[node_name] = prop_rng_local.randint(0, 100)

    propManipCrystal = world.createObject("QuantumCrystal")
    propManipCrystal = mkCrystalPropertiesCausal(
        propManipCrystal,
        rng=rng,
        causal_graph=causal_graph,
        override_base_values=prop_manip_override,
    )
    propManipCrystal.name = "quantum crystal (for property manipulation)"

    reactorCrystal = world.createObject("QuantumCrystal")
    reactorCrystal = mkCrystalPropertiesCausal(
        reactorCrystal,
        rng=rng,
        causal_graph=causal_graph,
        override_base_values=reactor_override,
    )
    reactorCrystal.name = "quantum crystal (for reactor activation)"

    # Store crystals for reference
    quantumCrystals = [propManipCrystal, reactorCrystal]
    scoringInfo["quantumCrystals"] = quantumCrystals

    # Add critical hypotheses about the causal relationships
    scoringInfo["criticalHypotheses"] = []
    scoringInfo["criticalQuestions"] = []

    # Document the causal structure dynamically based on the graph
    if graph_source.startswith("legacy"):
        # Legacy T->F, T->M graph - use original format
        params = causal_graph.computation_params
        scoringInfo["criticalHypotheses"].append(
            f"Temperature (T) causally affects Frequency (F) via: F = {params['F_0']} + {params['k_f']} * (T - {params['T_ref']})"
        )
        scoringInfo["criticalHypotheses"].append(
            f"Temperature (T) causally affects Moisture (M) via: M = M_0 + {params['k_d']} * (T - {params['T_ref']})"
        )
        scoringInfo["criticalHypotheses"].append(
            "Temperature (T) and Base Moisture (M_0) are controllable variables"
        )
        scoringInfo["criticalHypotheses"].append(
            "There is NO direct causal relationship between Moisture (M) and Frequency (F)"
        )

        scoringInfo["criticalQuestions"].append(
            "Does it correctly identify that Temperature affects Frequency?"
        )
        scoringInfo["criticalQuestions"].append(
            "Does it correctly identify that Temperature affects Moisture?"
        )
        scoringInfo["criticalQuestions"].append(
            "Does it correctly identify that there is NO direct relationship between Moisture and Frequency?"
        )
    else:
        # Config-based graph - generate hypotheses from structure
        if hasattr(causal_graph, "description"):
            scoringInfo["criticalHypotheses"].append(
                f"Causal Structure: {causal_graph.description}"
            )

        # List all causal edges
        for node_name, node in causal_graph.nodes.items():
            if node.children:
                for child_name in node.children:
                    parent_prop = causal_graph.node_property_mapping.get(
                        node_name, node_name
                    )
                    child_prop = causal_graph.node_property_mapping.get(
                        child_name, child_name
                    )
                    scoringInfo["criticalHypotheses"].append(
                        f"Causal edge: {parent_prop} → {child_prop}"
                    )

        # List controllable variables
        controllable = [
            causal_graph.node_property_mapping.get(n, n)
            for n, node in causal_graph.nodes.items()
            if node.is_controllable
        ]
        if controllable:
            scoringInfo["criticalHypotheses"].append(
                f"Controllable variables: {', '.join(controllable)}"
            )

        # List derived variables
        derived = [
            causal_graph.node_property_mapping.get(n, n)
            for n, node in causal_graph.nodes.items()
            if not node.is_controllable
        ]
        if derived:
            scoringInfo["criticalHypotheses"].append(
                f"Derived variables: {', '.join(derived)}"
            )

        # Generate critical questions for each edge
        for node_name, node in causal_graph.nodes.items():
            if node.children:
                parent_prop = causal_graph.node_property_mapping.get(
                    node_name, node_name
                )
                for child_name in node.children:
                    child_prop = causal_graph.node_property_mapping.get(
                        child_name, child_name
                    )
                    scoringInfo["criticalQuestions"].append(
                        f"Does it correctly identify that {parent_prop} causally affects {child_prop}?"
                    )

    # Add crystal-specific measurements (works for any graph structure)
    unobservable_props = set(
        causal_graph.node_property_mapping.get(node_name, node_name)
        for node_name, is_obs in causal_graph.node_observable.items()
        if not is_obs
    )

    for crystal in quantumCrystals:
        measurements = []
        for attr_name in [
            "temperatureC",
            "moisture",
            "moistureBase",
            "density",
            "quantumSize",
            "resonanceFreq",
        ]:
            if attr_name in crystal.attributes and attr_name not in unobservable_props:
                value = crystal.attributes[attr_name]
                measurements.append(f"{attr_name}={value}")

        if measurements:
            scoringInfo["criticalHypotheses"].append(
                f"{crystal.name}: {', '.join(measurements)}"
            )

    # Table 2: Crystal Reactor
    reactorBench = world.createObject("Table")
    reactor = world.createObject("CrystalReactor")
    reactor.setReactorNum(1)

    # Set initial frequency to 0 (needs to be calibrated by the agent)
    reactor.attributes["resonanceFreq"] = 0.0
    reactor.attributes["resonanceFreqDefault"] = 0.0

    reactorBench.addObject(reactor)
    world.addObject(x + 2, y + 2, Layer.FURNITURE, reactorBench)

    # Store reactor in scoringInfo for task scoring
    scoringInfo["reactor"] = reactor

    # Table 3: Property Manipulator machine (with target crystal inside)
    propManipBench = world.createObject("Table")
    propManip = PropertyManipulator(world)

    # Configure the PropertyManipulator with causal graph
    # Store the causal graph reference so PropertyManipulator can use it dynamically
    propManip.attributes["causalGraph"] = causal_graph

    # Set budget from config if available
    if hasattr(causal_graph, "budget") and causal_graph.budget is not None:
        propManip.attributes["maxUses"] = causal_graph.budget
        print(
            f"[mkReactorLabCausal] Set PropertyManipulator budget from config: {causal_graph.budget}"
        )

    # Copy all computation parameters to PropertyManipulator
    # This supports arbitrary causal graphs with different parameters
    for param_name, param_value in causal_graph.computation_params.items():
        propManip.attributes[param_name] = param_value
        print(
            f"[mkReactorLabCausal] Set PropertyManipulator param: {param_name} = {param_value}"
        )

    # Store reactor reference in PropertyManipulator so it can check if reactor has been used
    propManip.attributes["reactor"] = reactor

    # Initialize the dialog tree
    DialogMaker().mkDialogPropertyManipulator(propManip)

    # Place the property manipulator crystal in PropertyManipulator
    # Place crystal in PropertyManipulator and make it non-movable
    propManip.addObject(propManipCrystal)
    propManipCrystal.attributes["isMovable"] = False

    # Place reactor crystal in reactor and make it non-movable
    reactor.addObject(reactorCrystal)
    reactorCrystal.attributes["isMovable"] = False

    # Place the property manipulator on a bench
    propManipBench.addObject(propManip)
    world.addObject(x + 3, y + 2, Layer.FURNITURE, propManipBench)

    scoringInfo["propertyManipulator"] = propManip
    scoringInfo["targetCrystal"] = reactorCrystal  # Reactor crystal is the target

    # Calculate target frequency from reactor crystal's physical properties using causal graph
    # This is similar to the original reactor logic where frequency is computed from crystal properties
    # Extract current property values from reactor crystal
    reactor_current_values = {}
    for node_name, node in causal_graph.nodes.items():
        if node.is_controllable:
            prop_name = causal_graph.node_property_mapping.get(node_name, node_name)
            is_hybrid = node.computation_fn is not None

            if is_hybrid:
                # For hybrid nodes, use the _base attribute if available
                base_attr = f"{prop_name}_base"
                if base_attr in reactorCrystal.attributes:
                    reactor_current_values[node_name] = reactorCrystal.attributes[
                        base_attr
                    ]
                elif prop_name in reactorCrystal.attributes:
                    reactor_current_values[node_name] = reactorCrystal.attributes[
                        prop_name
                    ]
            else:
                # For pure controllable nodes, use the property value directly
                if prop_name in reactorCrystal.attributes:
                    reactor_current_values[node_name] = reactorCrystal.attributes[
                        prop_name
                    ]

    # Compute all properties including resonanceFreq using causal graph
    reactor_computed_values = causal_graph.compute_values(
        rng, precision=2, override_base_values=reactor_current_values
    )

    # Find resonanceFreq node name
    resonanceFreq_node_name = None
    for node_name, node in causal_graph.nodes.items():
        prop_name = causal_graph.node_property_mapping.get(node_name, node_name)
        if prop_name == "resonanceFreq":
            resonanceFreq_node_name = node_name
            break

    # Get target frequency from computed values
    if resonanceFreq_node_name and resonanceFreq_node_name in reactor_computed_values:
        targetFrequency = reactor_computed_values[resonanceFreq_node_name]
        # Also update reactor crystal's resonanceFreq attribute
        reactorCrystal.attributes["resonanceFreq"] = targetFrequency
    else:
        # Fallback: use resonanceFreq from crystal if available
        targetFrequency = reactorCrystal.attributes.get("resonanceFreq", 1000.0)

    scoringInfo["targetFrequency"] = targetFrequency
    scoringInfo["initialFrequency"] = targetFrequency

    scoringInfo["frequencyTolerance"] = 5.0  # Hz tolerance for reactor activation

    # Print the target frequency at the start
    print("=" * 80)
    print(f"TARGET FREQUENCY: {scoringInfo['targetFrequency']} Hz")
    print(f"Target Crystal: {reactorCrystal.name}")
    print(f"Frequency Tolerance: {scoringInfo['frequencyTolerance']} Hz")
    print("=" * 80)

    return scoringInfo


def makeScenarioReactorLabCausal(world, numUserAgents=1, config=None):
    """
    Create a reactor lab scenario with causal relationships.

    This scenario demonstrates:
    - Causal graph framework usage
    - T->F and T->M relationships
    - Extensible design for other causal structures

    To create a different causal structure:
    1. Define a new causal graph using the CausalGraph class
    2. Example for chain (A->B->C):
       graph = create_alternative_causal_graphs(world.rng, graph_type='chain')
    3. Pass the graph to mkCrystalPropertiesCausal()
    4. Update the scoring info to reflect the new relationships

    Args:
        world: World object
        numUserAgents: Number of user agents to create (default: 1)
        config: Optional CausalConfig object for manual parameter specification.
                If None, uses random generation (default behavior).

                Example usage for debugging with specific parameters:
                    config = CausalConfig(T_ref=25.0, F_0=1200.0, k_f=60.0, k_d=0.6)
    """
    scoringInfo = {}
    scoringInfo["criticalHypotheses"] = []
    scoringInfo["criticalQuestions"] = []

    # Set a limit for the number of user agents
    MAX_NUM_AGENTS = 3
    if numUserAgents > MAX_NUM_AGENTS:
        numUserAgents = MAX_NUM_AGENTS

    # Fill with grass
    mkGrassFill(world)

    # Reactor Lab with Causal Relationships
    mkReactorLabCausal(
        14,
        15,
        world,
        rng=world.rng,
        randomSeed=world.randomSeed,
        scoringInfo=scoringInfo,
        config=config,
    )

    # Plaza
    mkPlaza(15, 22, world)

    # Paths
    mkPathX(10, 23, 5, world)
    mkPathX(18, 23, 5, world)
    mkPathY(16, 21, 1, world)  # Down from building
    mkPathY(16, 25, 5, world)  # Down from plaza

    # Trees
    mkTallTree(9, 23, world)
    mkTallTree(23, 23, world)
    mkTallTree(9, 20, world)
    mkTallTree(23, 20, world)
    mkTallTree(9, 17, world)
    mkTallTree(23, 17, world)

    # Fences
    mkFenceY(6, 12, 14, world)
    mkFenceX(6, 12, 20, world)
    mkFenceY(26, 12, 14, world)
    mkFenceX(6, 25, 9, world)
    mkFenceX(18, 25, 9, world)

    # Add village sign (rectangular, not diamond)
    sign = world.createObject("Sign", text="Welcome to the Causal Discovery Lab")
    world.addObject(15, 27, Layer.BUILDING, sign)

    # Add plants
    world.addObject(15, 1, Layer.OBJECTS, world.createObject("PlantGeneric"))
    plantCount = 0
    minPlants = 15
    while plantCount < minPlants:
        randX = world.rng.randint(0, world.sizeX - 1)
        randY = world.rng.randint(0, world.sizeY - 1)
        objs = world.getObjectsAt(randX, randY)
        objTypes = [obj.type for obj in objs]
        if ("grass" in objTypes) and (len(objTypes) == 1):
            world.addObject(
                randX, randY, Layer.OBJECTS, world.createObject("PlantGeneric")
            )
            plantCount += 1

    # Add user agents
    for userAgentIdx in range(0, numUserAgents):
        userAgent = Agent(world)

        # Provide dynamically created instruments in inventory based on causal graph
        # Retrieve instrument types from scoringInfo (created during mkReactorLabCausal)
        instrument_types = scoringInfo.get("instrumentTypes", [])

        # Add all required instruments to agent inventory
        for instrument_type in instrument_types:
            # Create a new instance of the instrument for this agent
            instrument_copy = world.createObject(instrument_type)
            userAgent.addObject(instrument_copy)
            print(
                f"[makeScenarioReactorLabCausal] Added {instrument_type} to agent inventory"
            )

        # Place agent in the causal discovery lab
        world.addObject(16 + userAgentIdx, 18, Layer.AGENT, userAgent)
        world.addAgent(userAgent)

    # Add teleport locations
    world.addTeleportLocation("causal reactor lab", 16, 18)

    # Return scoring info
    return scoringInfo
