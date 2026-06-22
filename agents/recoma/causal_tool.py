import json
import os
import random
from pathlib import Path

from discoveryworld.scenarios.reactor_lab import load_causal_graph_from_config


def _canonical_prop(name):
    if not isinstance(name, str):
        return None
    aliases = {
        "pH": "ph",
        "temperature": "temperatureC",
        "radiationusvh": "radiation",
    }
    return aliases.get(name, name)


def _entry_prop_map(entry):
    if not isinstance(entry, dict):
        return {}
    props = entry.get("props", {})
    if not isinstance(props, dict):
        props = {}
    normalized = {_canonical_prop(key): value for key, value in props.items()}
    normalized["resonanceFreq"] = entry.get("freq")
    return normalized


class OnlineInterventionCausalTool:
    """
    Deterministic candidate-graph filter.

    It enumerates candidate graphs from the current graph-config group and removes
    every graph that is inconsistent with:
    1. the observed variable set in past_data; or
    2. any intervention transition under the environment's base-value semantics.
    """

    def __init__(self, tolerance=1e-2):
        self.tolerance = float(tolerance)
        self.max_graphs_in_prompt = int(os.environ.get("CAUSAL_TOOL_MAX_GRAPHS", "20"))
        self.group_path = self._resolve_group_path()
        self.all_candidates = self._load_candidates()
        self.active_candidates = list(self.all_candidates)
        self.transition_count = 0
        self.last_observed_prop_set = None

    def _resolve_group_path(self):
        group_name = os.environ.get("CAUSAL_GRAPH_GROUP", "4nodes.jsonl")
        candidate = Path(group_name)
        if candidate.is_file():
            return candidate
        return Path.cwd() / "causal_graph_configs" / group_name

    def _load_candidates(self):
        candidates = []
        if not self.group_path.exists():
            return candidates
        with open(self.group_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                config = json.loads(line)
                candidates.append(
                    {
                        "config": config,
                        "graph": load_causal_graph_from_config(config, random.Random(0)),
                    }
                )
        return candidates

    @staticmethod
    def _graph_prop_set(graph):
        prop_set = {
            _canonical_prop(graph.node_property_mapping.get(node_name, node_name))
            for node_name in graph.nodes
            if node_name != "resonanceFreq"
        }
        prop_set.discard(None)
        return prop_set

    @staticmethod
    def _graph_node_for_prop(graph, prop_name):
        prop_name = _canonical_prop(prop_name)
        for node_name in graph.nodes:
            mapped = _canonical_prop(graph.node_property_mapping.get(node_name, node_name))
            if mapped == prop_name:
                return node_name
        return None

    def _infer_base_values(self, graph, entry):
        observed = _entry_prop_map(entry)
        base_values = {}
        computed = {}

        def compute_node_value(node_name):
            if node_name in computed:
                return computed[node_name]

            node = graph.nodes[node_name]
            prop_name = _canonical_prop(graph.node_property_mapping.get(node_name, node_name))
            observed_value = observed.get(prop_name)

            if node.is_controllable:
                if node.computation_fn is None:
                    base_values[node_name] = observed_value
                    computed[node_name] = observed_value
                    return observed_value

                parent_values = {}
                for parent_name in node.parents:
                    parent_values[parent_name] = compute_node_value(parent_name)

                without_base = node.computation_fn(
                    {
                        **parent_values,
                        "base": 0.0,
                        f"{node_name}_base": 0.0,
                    },
                    graph.computation_params,
                )
                inferred_base = round(float(observed_value) - float(without_base), 2)
                base_values[node_name] = inferred_base
                computed[node_name] = observed_value
                return observed_value

            for parent_name in node.parents:
                compute_node_value(parent_name)
            computed[node_name] = observed_value
            return observed_value

        for node_name in graph.nodes:
            prop_name = _canonical_prop(graph.node_property_mapping.get(node_name, node_name))
            if prop_name in observed:
                compute_node_value(node_name)

        return base_values

    def _simulate_transition(self, graph, before_entry, experiment):
        target_prop = _canonical_prop((experiment or {}).get("target_prop"))
        if target_prop is None:
            return None

        before_values = _entry_prop_map(before_entry)
        target_node = self._graph_node_for_prop(graph, target_prop)
        if target_node is None:
            return None

        expected_prop_set = set(before_values.keys()) - {"resonanceFreq"}
        if self._graph_prop_set(graph) != expected_prop_set:
            return None

        base_values = self._infer_base_values(graph, before_entry)
        node = graph.nodes[target_node]
        target_value = float(experiment.get("target_value"))
        current_final = float(before_values[target_prop])

        if node.computation_fn is None:
            base_values[target_node] = round(target_value, 2)
        else:
            current_base = float(base_values[target_node])
            contribution = current_final - current_base
            base_values[target_node] = round(target_value - contribution, 2)

        simulated = graph.compute_values(
            random.Random(0),
            precision=2,
            override_base_values=base_values,
        )
        return {
            _canonical_prop(graph.node_property_mapping.get(node_name, node_name)): value
            for node_name, value in simulated.items()
        }

    def _entry_matches_graph(self, graph, entry):
        entry_props = set(_entry_prop_map(entry).keys()) - {"resonanceFreq"}
        return self._graph_prop_set(graph) == entry_props

    def _transition_matches_graph(self, graph, before_entry, after_entry, experiment):
        simulated = self._simulate_transition(graph, before_entry, experiment)
        if simulated is None:
            return False

        observed_after = _entry_prop_map(after_entry)
        for prop_name, observed_value in observed_after.items():
            simulated_value = simulated.get(prop_name)
            if simulated_value is None:
                return False
            if abs(float(simulated_value) - float(observed_value)) > self.tolerance:
                return False
        return True

    def filter_with_entry(self, entry):
        prop_set = set(_entry_prop_map(entry).keys()) - {"resonanceFreq"}
        self.last_observed_prop_set = prop_set
        self.active_candidates = [
            candidate
            for candidate in self.active_candidates
            if self._entry_matches_graph(candidate["graph"], entry)
        ]

    def add_transition(self, before_entry, after_entry, experiment):
        self.filter_with_entry(before_entry)
        self.filter_with_entry(after_entry)
        self.active_candidates = [
            candidate
            for candidate in self.active_candidates
            if self._transition_matches_graph(
                candidate["graph"],
                before_entry,
                after_entry,
                experiment,
            )
        ]
        self.transition_count += 1
        return True

    def build_summary(self):
        shown = []
        for candidate in self.active_candidates[: self.max_graphs_in_prompt]:
            config = candidate["config"]
            shown.append(
                {
                    "graph_id": config.get("graph_id"),
                    "edges": config.get("edges", []),
                }
            )

        notes = [
            "Deterministic filter: only graphs consistent with observed variable names and all recorded intervention transitions are kept.",
            "Intervention semantics follow this environment: setting a variable changes its base value; hybrid nodes are adjusted so the post-intervention final value matches the chosen target before propagation.",
        ]
        if len(self.active_candidates) > len(shown):
            notes.append(
                f"Only the first {len(shown)} candidate graphs are shown in this prompt; "
                f"{len(self.active_candidates) - len(shown)} additional consistent graphs are omitted due to the display limit."
            )

        return {
            "graph_group": str(self.group_path),
            "candidate_graph_count": len(self.active_candidates),
            "candidate_graphs_shown": len(shown),
            "transition_constraints_used": self.transition_count,
            "observed_property_set": sorted(self.last_observed_prop_set or []),
            "candidate_graphs": shown,
            "notes": notes,
        }

    def format_summary(self, max_chars=8000):
        payload = json.dumps(self.build_summary(), indent=2, sort_keys=True)
        if len(payload) <= max_chars:
            return payload
        summary = self.build_summary()
        summary["candidate_graphs"] = summary["candidate_graphs"][:5]
        payload = json.dumps(summary, indent=2, sort_keys=True)
        return payload[:max_chars]
