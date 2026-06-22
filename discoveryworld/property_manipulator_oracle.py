from __future__ import annotations

from collections import defaultdict
from typing import Mapping, Sequence


def _values_differ(left, right, tolerance: float) -> bool:
    if left is None or right is None:
        return left != right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) > tolerance
    return left != right


def _build_children(edges: Sequence[tuple[str, str]]) -> dict[str, list[str]]:
    children: dict[str, set[str]] = defaultdict(set)
    for parent, child in edges:
        if parent == child:
            continue
        children[parent].add(child)
    return {
        parent: sorted(child_names)
        for parent, child_names in children.items()
    }


def _collect_descendants(
    start_node: str,
    children: Mapping[str, Sequence[str]],
) -> set[str]:
    visited: set[str] = set()
    stack = list(children.get(start_node, []))
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(children.get(node, []))
    return visited


def build_maximal_changed_paths(
    start_node: str,
    edges: Sequence[tuple[str, str]],
    before_values: Mapping[str, object],
    after_values: Mapping[str, object],
    tolerance: float = 1e-6,
) -> list[list[str]]:
    """
    Return all maximal directed paths from ``start_node`` through descendants whose
    no-hidden values changed because of the intervention.
    """
    children = _build_children(edges)
    reachable_descendants = _collect_descendants(start_node, children)
    changed_descendants = {
        node
        for node in reachable_descendants
        if _values_differ(
            before_values.get(node),
            after_values.get(node),
            tolerance=tolerance,
        )
    }
    if not changed_descendants:
        return []

    paths: list[list[str]] = []

    def dfs(node_name: str, path: list[str]) -> None:
        next_nodes = [
            child_name
            for child_name in children.get(node_name, [])
            if child_name in changed_descendants
        ]
        if not next_nodes:
            if len(path) > 1:
                paths.append(path)
            return

        for child_name in next_nodes:
            dfs(child_name, path + [child_name])

    dfs(start_node, [start_node])
    return paths


def format_oracle_chain_strings(
    paths: Sequence[Sequence[str]],
    node_labels: Mapping[str, str] | None = None,
) -> list[str]:
    labels = node_labels or {}
    rendered = []
    for path in paths:
        rendered.append("->".join(labels.get(node_name, node_name) for node_name in path))
    return rendered
