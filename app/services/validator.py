from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, List, Set

from app.models.sem_graph import (
    EdgeRelation,
    NodeType,
    SemGraph,
    Severity,
)


# ============================================================
# Public API
# ============================================================

def validate_sem_graph(graph: SemGraph) -> SemGraph:
    """
    Run a semantic validation pass over the SEM graph.

    This function mutates the graph by appending validation messages
    and metadata, then returns it.

    Validation philosophy
    ---------------------
    We distinguish between:
    - errors: graph is internally inconsistent or structurally invalid
    - warnings: graph may be estimationally risky or conceptually odd
    - info: useful notes for GUI / debugging / teaching

    This validator does not fit the model and does not fully determine
    identifiability in the formal SEM sense.
    """
    _validate_empty_graph(graph)
    _validate_duplicate_node_names(graph)
    _validate_edge_endpoint_existence(graph)
    _validate_duplicate_edge_keys(graph)
    _validate_edge_relation_semantics(graph)

    _validate_latent_indicator_structure(graph)
    _validate_measurement_scaling(graph)
    _validate_latent_variance_structure(graph)
    _validate_indicator_cross_loading_patterns(graph)
    _validate_structural_role_consistency(graph)

    _validate_intercept_structure(graph)
    _validate_residual_structure(graph)
    _validate_variance_and_covariance_structure(graph)

    _validate_isolated_nodes(graph)
    _validate_regression_cycles(graph)

    _validate_defined_parameter_references(graph)
    _validate_constraint_references(graph)

    _annotate_validation_metadata(graph)
    return graph


# ============================================================
# Basic graph integrity
# ============================================================

def _validate_empty_graph(graph: SemGraph) -> None:
    if not graph.statements and not graph.defined_parameters and not graph.constraints:
        graph.add_message(
            Severity.ERROR,
            "graph_has_no_content",
            "Graph contains no statements, defined parameters, or constraints.",
        )

    if not graph.nodes and graph.statements:
        graph.add_message(
            Severity.ERROR,
            "graph_has_no_nodes",
            "Graph contains statements but no nodes were built.",
        )

    if not graph.edges and graph.statements:
        real_stmt_types = {"loading", "regression", "covariance", "variance", "intercept"}
        if any(stmt.stmt_type.value in real_stmt_types for stmt in graph.statements):
            graph.add_message(
                Severity.ERROR,
                "graph_has_no_edges",
                "Graph contains SEM statements but no semantic edges were built.",
            )


def _validate_duplicate_node_names(graph: SemGraph) -> None:
    counts = Counter(node.name for node in graph.nodes)
    for name, count in counts.items():
        if count > 1:
            graph.add_message(
                Severity.ERROR,
                "duplicate_node_name",
                f"Node '{name}' appears {count} times in the graph.",
            )


def _validate_edge_endpoint_existence(graph: SemGraph) -> None:
    node_names = {node.name for node in graph.nodes}

    for edge in graph.edges:
        if edge.source not in node_names:
            graph.add_message(
                Severity.ERROR,
                "missing_edge_source",
                f"Edge source '{edge.source}' does not exist as a node.",
                context=str(edge.to_dict()),
            )
        if edge.target not in node_names:
            graph.add_message(
                Severity.ERROR,
                "missing_edge_target",
                f"Edge target '{edge.target}' does not exist as a node.",
                context=str(edge.to_dict()),
            )


def _validate_duplicate_edge_keys(graph: SemGraph) -> None:
    counts = Counter(edge.key() for edge in graph.edges)
    for key, count in counts.items():
        if count > 1:
            graph.add_message(
                Severity.WARNING,
                "duplicate_semantic_edge",
                f"Semantic edge '{key}' appears {count} times.",
            )


def _validate_edge_relation_semantics(graph: SemGraph) -> None:
    """
    Catch obvious semantic mismatches between relation types and edge forms.
    """
    directed_relations = {
        EdgeRelation.LOADING,
        EdgeRelation.REGRESSION,
        EdgeRelation.INTERCEPT,
        EdgeRelation.RESIDUAL,
    }

    for edge in graph.edges:
        if edge.relation == EdgeRelation.COVARIANCE:
            if not edge.bidirectional:
                graph.add_message(
                    Severity.WARNING,
                    "covariance_not_bidirectional",
                    f"Covariance edge '{edge.key()}' is not marked bidirectional.",
                    context=str(edge.to_dict()),
                )

        if edge.relation in directed_relations and not edge.directed:
            graph.add_message(
                Severity.WARNING,
                "directed_relation_not_directed",
                f"Directed relation '{edge.key()}' is not marked directed.",
                context=str(edge.to_dict()),
            )

        if edge.source == edge.target and edge.relation not in {EdgeRelation.VARIANCE}:
            graph.add_message(
                Severity.WARNING,
                "unexpected_self_loop",
                f"Edge '{edge.key()}' is a self-loop but relation is '{edge.relation.value}'.",
                context=str(edge.to_dict()),
            )


# ============================================================
# Measurement structure
# ============================================================

def _validate_latent_variance_structure(graph: SemGraph) -> None:
    """
    Warn when a latent variable has no explicit variance edge and no obvious
    scale-setting information beyond loadings.

    This is heuristic, not a full identification check.
    """
    latent_names = {n.name for n in graph.nodes if n.node_type == NodeType.LATENT}

    variance_self_loops = {
        e.source
        for e in graph.edges
        if e.relation == EdgeRelation.VARIANCE and e.source == e.target
    }

    loading_edges = [e for e in graph.edges if e.relation == EdgeRelation.LOADING]
    by_factor: Dict[str, List] = defaultdict(list)
    for edge in loading_edges:
        by_factor[edge.source].append(edge)

    for latent_name in latent_names:
        if latent_name in variance_self_loops:
            continue

        edges = by_factor.get(latent_name, [])
        has_fixed_loading = any(e.parameter.fixed is not None for e in edges)
        has_na_modifier = any(
            bool(e.metadata.get("na_modifier", False))
            or bool(e.metadata.get("statement_metadata", {}).get("na_modifier", False))
            for e in edges
        )

        if not has_fixed_loading and not has_na_modifier:
            graph.add_message(
                Severity.INFO,
                "latent_without_explicit_variance",
                f"Latent variable '{latent_name}' has no explicit variance edge.",
            )

def _validate_latent_indicator_structure(graph: SemGraph) -> None:
    loading_edges = [e for e in graph.edges if e.relation == EdgeRelation.LOADING]

    by_factor: Dict[str, List] = defaultdict(list)
    for edge in loading_edges:
        by_factor[edge.source].append(edge)

    latent_names = {n.name for n in graph.nodes if n.node_type == NodeType.LATENT}

    for latent_name in latent_names:
        factor_loadings = by_factor.get(latent_name, [])
        n_indicators = len(factor_loadings)

        if n_indicators == 0:
            graph.add_message(
                Severity.WARNING,
                "latent_without_indicators",
                f"Latent variable '{latent_name}' has no indicators.",
            )
        elif n_indicators == 1:
            graph.add_message(
                Severity.WARNING,
                "latent_with_one_indicator",
                f"Latent variable '{latent_name}' has only one indicator.",
            )
        elif n_indicators == 2:
            graph.add_message(
                Severity.INFO,
                "latent_with_two_indicators",
                f"Latent variable '{latent_name}' has two indicators; identification may depend on additional constraints.",
            )

    for edge in loading_edges:
        source = graph.get_node(edge.source)
        target = graph.get_node(edge.target)

        if source is None or target is None:
            continue

        if source.node_type != NodeType.LATENT:
            graph.add_message(
                Severity.ERROR,
                "loading_source_not_latent",
                f"Loading edge source '{source.name}' is not latent.",
                context=str(edge.to_dict()),
            )

        if target.node_type == NodeType.LATENT:
            graph.add_message(
                Severity.WARNING,
                "latent_as_indicator",
                f"Loading target '{target.name}' is also typed latent. This may indicate a higher-order structure or a node-typing problem.",
                context=str(edge.to_dict()),
            )


def _validate_measurement_scaling(graph: SemGraph) -> None:
    loading_edges = [e for e in graph.edges if e.relation == EdgeRelation.LOADING]

    by_factor: Dict[str, List] = defaultdict(list)
    for edge in loading_edges:
        by_factor[edge.source].append(edge)

    latent_names = {n.name for n in graph.nodes if n.node_type == NodeType.LATENT}

    for latent_name in latent_names:
        edges = by_factor.get(latent_name, [])
        if not edges:
            continue

        has_fixed_loading = any(e.parameter.fixed is not None for e in edges)
        has_na_modifier = any(
            bool(e.metadata.get("na_modifier", False))
            or bool(e.metadata.get("statement_metadata", {}).get("na_modifier", False))
            for e in edges
        )

        if not has_fixed_loading and not has_na_modifier:
            graph.add_message(
                Severity.INFO,
                "latent_scale_not_explicit",
                f"Latent variable '{latent_name}' has no explicit fixed loading or NA marker in the parsed syntax. Scale-setting may be implicit.",
            )

        fixed_to_one = sum(1 for e in edges if e.parameter.fixed == 1.0)
        if fixed_to_one > 1:
            graph.add_message(
                Severity.WARNING,
                "multiple_marker_loadings",
                f"Latent variable '{latent_name}' has multiple loadings fixed to 1.0.",
            )


def _validate_indicator_cross_loading_patterns(graph: SemGraph) -> None:
    loading_edges = [e for e in graph.edges if e.relation == EdgeRelation.LOADING]

    by_indicator: Dict[str, List] = defaultdict(list)
    for edge in loading_edges:
        by_indicator[edge.target].append(edge)

    for indicator, edges in by_indicator.items():
        parents = sorted({e.source for e in edges})
        if len(parents) > 1:
            graph.add_message(
                Severity.INFO,
                "cross_loading_indicator",
                f"Indicator '{indicator}' loads on multiple latent variables: {', '.join(parents)}.",
            )


# ============================================================
# Structural consistency
# ============================================================

def _validate_structural_role_consistency(graph: SemGraph) -> None:
    regression_edges = [e for e in graph.edges if e.relation == EdgeRelation.REGRESSION]
    loading_edges = [e for e in graph.edges if e.relation == EdgeRelation.LOADING]

    indicator_names = {e.target for e in loading_edges}

    for edge in regression_edges:
        source = graph.get_node(edge.source)
        target = graph.get_node(edge.target)

        if source is None or target is None:
            continue

        if source.name in indicator_names:
            graph.add_message(
                Severity.INFO,
                "indicator_as_structural_predictor",
                f"Indicator '{source.name}' is used as a structural predictor.",
            )

        if target.name in indicator_names:
            graph.add_message(
                Severity.INFO,
                "indicator_as_structural_outcome",
                f"Indicator '{target.name}' is used as a structural outcome.",
            )

        if source.node_type == NodeType.INTERCEPT or target.node_type == NodeType.INTERCEPT:
            graph.add_message(
                Severity.ERROR,
                "intercept_node_in_regression",
                "Intercept node participates in a regression edge, which is not expected.",
                context=str(edge.to_dict()),
            )

        if source.node_type == NodeType.ERROR or target.node_type == NodeType.ERROR:
            graph.add_message(
                Severity.ERROR,
                "error_node_in_regression",
                "Residual/error node participates in a regression edge, which is not expected.",
                context=str(edge.to_dict()),
            )


# ============================================================
# Intercepts
# ============================================================

def _validate_intercept_structure(graph: SemGraph) -> None:
    intercept_nodes = [n for n in graph.nodes if n.node_type == NodeType.INTERCEPT]
    intercept_edges = [e for e in graph.edges if e.relation == EdgeRelation.INTERCEPT]

    by_target: Dict[str, List] = defaultdict(list)
    for edge in intercept_edges:
        by_target[edge.target].append(edge)

    for node in intercept_nodes:
        target = node.metadata.get("target")
        if not target:
            graph.add_message(
                Severity.WARNING,
                "intercept_node_missing_target_metadata",
                f"Intercept node '{node.name}' has no target metadata.",
            )

        outgoing = [e for e in intercept_edges if e.source == node.name]
        if len(outgoing) == 0:
            graph.add_message(
                Severity.WARNING,
                "intercept_node_without_edge",
                f"Intercept node '{node.name}' has no outgoing intercept edge.",
            )
        elif len(outgoing) > 1:
            graph.add_message(
                Severity.WARNING,
                "intercept_node_multiple_edges",
                f"Intercept node '{node.name}' has multiple outgoing intercept edges.",
            )

    for target, edges in by_target.items():
        if len(edges) > 1:
            graph.add_message(
                Severity.WARNING,
                "multiple_intercepts_for_target",
                f"Target '{target}' has multiple intercept edges.",
            )


# ============================================================
# Residuals
# ============================================================

def _validate_residual_structure(graph: SemGraph) -> None:
    error_nodes = [n for n in graph.nodes if n.node_type == NodeType.ERROR]
    residual_edges = [e for e in graph.edges if e.relation == EdgeRelation.RESIDUAL]

    by_target: Dict[str, List] = defaultdict(list)
    for edge in residual_edges:
        by_target[edge.target].append(edge)

    for node in error_nodes:
        target = node.metadata.get("target")
        if not target:
            graph.add_message(
                Severity.WARNING,
                "error_node_missing_target_metadata",
                f"Error node '{node.name}' has no target metadata.",
            )

        outgoing = [e for e in residual_edges if e.source == node.name]
        if len(outgoing) == 0:
            graph.add_message(
                Severity.WARNING,
                "error_node_without_edge",
                f"Error node '{node.name}' has no outgoing residual edge.",
            )
        elif len(outgoing) > 1:
            graph.add_message(
                Severity.WARNING,
                "error_node_multiple_edges",
                f"Error node '{node.name}' has multiple outgoing residual edges.",
            )

    for target, edges in by_target.items():
        if len(edges) > 1:
            graph.add_message(
                Severity.WARNING,
                "multiple_residuals_for_target",
                f"Target '{target}' has multiple residual edges.",
            )

    for edge in residual_edges:
        source = graph.get_node(edge.source)
        target = graph.get_node(edge.target)

        if source is None or target is None:
            continue

        if source.node_type != NodeType.ERROR:
            graph.add_message(
                Severity.ERROR,
                "residual_source_not_error",
                f"Residual edge source '{source.name}' is not an error node.",
                context=str(edge.to_dict()),
            )

        if target.node_type == NodeType.INTERCEPT:
            graph.add_message(
                Severity.ERROR,
                "residual_target_is_intercept",
                f"Residual edge target '{target.name}' is an intercept node.",
                context=str(edge.to_dict()),
            )


# ============================================================
# Variance / covariance checks
# ============================================================

def _validate_variance_and_covariance_structure(graph: SemGraph) -> None:
    covariance_edges = [e for e in graph.edges if e.relation == EdgeRelation.COVARIANCE]
    variance_edges = [e for e in graph.edges if e.relation == EdgeRelation.VARIANCE]

    for edge in covariance_edges:
        s = graph.get_node(edge.source)
        t = graph.get_node(edge.target)

        if s is None or t is None:
            continue

        if s.node_type == NodeType.INTERCEPT or t.node_type == NodeType.INTERCEPT:
            graph.add_message(
                Severity.WARNING,
                "covariance_with_intercept_node",
                "Covariance involving an intercept node is unusual.",
                context=str(edge.to_dict()),
            )

        if s.node_type == NodeType.ERROR or t.node_type == NodeType.ERROR:
            graph.add_message(
                Severity.INFO,
                "covariance_with_error_node",
                "Covariance involving an error node may be intentional (correlated residuals), but is worth checking.",
                context=str(edge.to_dict()),
            )

        if edge.source == edge.target:
            graph.add_message(
                Severity.WARNING,
                "covariance_self_edge",
                "Covariance edge is a self-edge; variance relation may have been intended.",
                context=str(edge.to_dict()),
            )

    variance_counts = Counter(e.source for e in variance_edges if e.source == e.target)
    for node_name, count in variance_counts.items():
        if count > 1:
            graph.add_message(
                Severity.WARNING,
                "multiple_variances_for_node",
                f"Node '{node_name}' has {count} variance edges.",
            )


# ============================================================
# Isolation / connectivity
# ============================================================

def _validate_isolated_nodes(graph: SemGraph) -> None:
    incident_counts = Counter()

    for edge in graph.edges:
        incident_counts[edge.source] += 1
        incident_counts[edge.target] += 1

    for node in graph.nodes:
        if incident_counts[node.name] == 0:
            graph.add_message(
                Severity.INFO,
                "isolated_node",
                f"Node '{node.name}' is isolated (no incident edges).",
            )


# ============================================================
# Regression cycles
# ============================================================

def _validate_regression_cycles(graph: SemGraph) -> None:
    regression_edges = [e for e in graph.edges if e.relation == EdgeRelation.REGRESSION]

    adjacency: Dict[str, List[str]] = defaultdict(list)
    nodes_in_reg = set()

    for edge in regression_edges:
        adjacency[edge.source].append(edge.target)
        nodes_in_reg.add(edge.source)
        nodes_in_reg.add(edge.target)

    visited: Set[str] = set()
    active: Set[str] = set()
    cycle_paths: List[List[str]] = []

    def dfs(node: str, path: List[str]) -> None:
        visited.add(node)
        active.add(node)
        path.append(node)

        for nxt in adjacency.get(node, []):
            if nxt not in visited:
                dfs(nxt, path.copy())
            elif nxt in active:
                try:
                    start_idx = path.index(nxt)
                    cycle = path[start_idx:] + [nxt]
                except ValueError:
                    cycle = path + [nxt]
                cycle_paths.append(cycle)

        active.remove(node)

    for node in nodes_in_reg:
        if node not in visited:
            dfs(node, [])

    if cycle_paths:
        seen = set()
        for cyc in cycle_paths:
            cyc_str = " -> ".join(cyc)
            if cyc_str not in seen:
                seen.add(cyc_str)
                graph.add_message(
                    Severity.WARNING,
                    "regression_cycle_detected",
                    f"Directed cycle detected among regression paths: {cyc_str}",
                )


# ============================================================
# Defined parameter reference checks
# ============================================================

def _validate_defined_parameter_references(graph: SemGraph) -> None:
    known_labels = {
        edge.parameter.label
        for edge in graph.edges
        if edge.parameter.label
    }

    if not graph.defined_parameters:
        return

    for dp in graph.defined_parameters:
        tokens = _extract_identifier_tokens(dp.expression)

        unknown = sorted(
            tok for tok in tokens
            if tok not in known_labels
            and not _looks_like_builtin_math_name(tok)
        )

        if unknown:
            graph.add_message(
                Severity.WARNING,
                "defined_parameter_unknown_labels",
                f"Defined parameter '{dp.name}' refers to unknown label(s): {', '.join(unknown)}.",
                line_no=dp.line_no,
                context=dp.raw,
            )


# ============================================================
# Constraint reference checks
# ============================================================

def _validate_constraint_references(graph: SemGraph) -> None:
    if not graph.constraints:
        return

    known_labels = {
        edge.parameter.label
        for edge in graph.edges
        if edge.parameter.label
    }
    known_nodes = {node.name for node in graph.nodes}
    known_defined = {dp.name for dp in graph.defined_parameters}

    known_symbols = known_labels | known_nodes | known_defined

    for c in graph.constraints:
        tokens = _extract_identifier_tokens(c.expression)
        unknown = sorted(
            tok for tok in tokens
            if tok not in known_symbols
            and not _looks_like_builtin_math_name(tok)
        )

        if unknown:
            graph.add_message(
                Severity.INFO,
                "constraint_unknown_symbols",
                f"Constraint '{c.expression}' refers to symbol(s) not found in current graph objects: {', '.join(unknown)}.",
                line_no=c.line_no,
                context=c.raw,
            )


# ============================================================
# Metadata annotation
# ============================================================

def _annotate_validation_metadata(graph: SemGraph) -> None:
    msg_counts = Counter(msg.severity.value for msg in graph.messages)

    validation_summary = {
        "n_info": msg_counts.get("info", 0),
        "n_warning": msg_counts.get("warning", 0),
        "n_error": msg_counts.get("error", 0),
        "has_errors": any(msg.severity == Severity.ERROR for msg in graph.messages),
        "has_warnings": any(msg.severity == Severity.WARNING for msg in graph.messages),
    }

    latent_names = [n.name for n in graph.nodes if n.node_type == NodeType.LATENT]
    observed_names = [n.name for n in graph.nodes if n.node_type == NodeType.OBSERVED]
    intercept_names = [n.name for n in graph.nodes if n.node_type == NodeType.INTERCEPT]
    error_names = [n.name for n in graph.nodes if n.node_type == NodeType.ERROR]

    edge_relation_counts = Counter(edge.relation.value for edge in graph.edges)

    validation_details = {
        "latent_names": latent_names,
        "observed_names": observed_names,
        "intercept_names": intercept_names,
        "error_names": error_names,
        "edge_relation_counts": dict(edge_relation_counts),
    }

    graph.metadata.setdefault("validation", {})
    graph.metadata["validation"]["summary"] = validation_summary
    graph.metadata["validation"]["details"] = validation_details


# ============================================================
# Helper functions
# ============================================================

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_\.]*\b")


def _extract_identifier_tokens(expression: str) -> Set[str]:
    return set(_IDENTIFIER_RE.findall(expression))


def _looks_like_builtin_math_name(name: str) -> bool:
    builtins = {
        "exp", "log", "sqrt", "sin", "cos", "tan",
        "abs", "min", "max", "pow", "ifelse",
        "NA", "Inf", "pi",
    }
    return name in builtins