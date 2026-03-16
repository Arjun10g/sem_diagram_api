from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Set

from app.models.sem_graph import (
    Edge,
    EdgeRelation,
    NodeRole,
    NodeType,
    SemGraph,
    Severity,
    StatementType,
)


# ============================================================
# Public API
# ============================================================

def build_sem_graph(parsed_graph: SemGraph) -> SemGraph:
    """
    Build a semantic graph from parser output.

    Returns a new SemGraph carrying over parsed content/messages while
    rebuilding semantic nodes, edges, synthetic nodes, and graph-level metadata.

    Textbook SEM defaults:
    - observed-variable variances are represented as residual/error nodes
    - latent variances remain self-loop variance edges
    - intercepts are represented as synthetic intercept nodes
    """
    graph = _clone_graph_shell(parsed_graph)

    if _is_empty_parsed_graph(parsed_graph):
        graph.add_message(
            Severity.WARNING,
            "empty_parsed_graph",
            "Parsed graph contained no statements, defined parameters, or constraints.",
        )
        _populate_graph_metadata(graph)
        return graph

    _infer_nodes_from_statements(graph)
    _infer_node_roles(graph)

    # Synthetic nodes should exist before dependent edges are built.
    _ensure_intercept_nodes(graph)
    _ensure_error_nodes(graph)

    _build_edges_from_statements(graph)
    _build_intercept_edges(graph)
    _build_residual_edges(graph)

    _detect_duplicate_edges(graph)
    _populate_graph_metadata(graph)

    return graph


# ============================================================
# Initialization
# ============================================================

def _clone_graph_shell(parsed_graph: SemGraph) -> SemGraph:
    """
    Create a new SemGraph carrying over parser-stage content, but with
    semantic nodes/edges rebuilt from scratch.
    """
    return SemGraph(
        statements=list(parsed_graph.statements),
        defined_parameters=list(parsed_graph.defined_parameters),
        constraints=list(parsed_graph.constraints),
        messages=list(parsed_graph.messages),
        metadata=dict(parsed_graph.metadata),
    )


def _is_empty_parsed_graph(graph: SemGraph) -> bool:
    return not (
        graph.statements
        or graph.defined_parameters
        or graph.constraints
    )


# ============================================================
# Small helpers
# ============================================================

def _stmt_metadata(stmt) -> dict:
    return {
        "line_no": stmt.line_no,
        "raw": stmt.raw,
        "operator": stmt.operator,
    }


def _intercept_node_name(target: str) -> str:
    return f"INT__{target}"


def _error_node_name(target: str) -> str:
    return f"ERR__{target}"


def _add_edge(
    graph: SemGraph,
    *,
    source: str,
    target: str,
    relation: EdgeRelation,
    stmt,
    directed: bool,
    bidirectional: bool,
    extra_metadata: dict | None = None,
) -> None:
    metadata = _stmt_metadata(stmt)
    if extra_metadata:
        metadata.update(extra_metadata)

    graph.add_edge(
        Edge(
            source=source,
            target=target,
            relation=relation,
            parameter=stmt.parameter,
            directed=directed,
            bidirectional=bidirectional,
            label=stmt.parameter.label,
            metadata=metadata,
        )
    )


def _iter_statements_of_type(graph: SemGraph, stmt_type: StatementType):
    for stmt in graph.statements:
        if stmt.stmt_type == stmt_type:
            yield stmt


# ============================================================
# Node inference
# ============================================================

def _infer_nodes_from_statements(graph: SemGraph) -> None:
    """
    Infer nodes from parsed statements.

    Rules:
    - loading lhs -> latent
    - loading rhs -> observed indicator
    - intercept lhs -> ordinary variable node
    - regression/covariance/variance participants default to observed
      unless upgraded elsewhere
    """
    for stmt in graph.statements:
        if stmt.stmt_type == StatementType.LOADING:
            graph.ensure_node(
                name=stmt.lhs,
                node_type=NodeType.LATENT,
                role=NodeRole.LATENT,
            )
            graph.ensure_node(
                name=stmt.rhs,
                node_type=NodeType.OBSERVED,
                role=NodeRole.INDICATOR,
            )
            continue

        if stmt.stmt_type in {
            StatementType.REGRESSION,
            StatementType.COVARIANCE,
        }:
            graph.ensure_node(
                name=stmt.lhs,
                node_type=NodeType.OBSERVED,
                role=NodeRole.VARIABLE,
            )
            graph.ensure_node(
                name=stmt.rhs,
                node_type=NodeType.OBSERVED,
                role=NodeRole.VARIABLE,
            )
            continue

        if stmt.stmt_type in {
            StatementType.VARIANCE,
            StatementType.INTERCEPT,
        }:
            graph.ensure_node(
                name=stmt.lhs,
                node_type=NodeType.OBSERVED,
                role=NodeRole.VARIABLE,
            )
            continue

        graph.add_message(
            Severity.INFO,
            "unhandled_statement_type_in_node_inference",
            f"Statement type '{stmt.stmt_type.value}' was not explicitly handled during node inference.",
            line_no=stmt.line_no,
            context=stmt.raw,
        )


# ============================================================
# Role inference
# ============================================================

def _infer_node_roles(graph: SemGraph) -> None:
    """
    Refine node roles once all nodes are known.

    Current model stores one role per node. When multiple usage patterns
    apply, the node is marked as MIXED.
    """
    usage = _collect_node_usage(graph)

    for node in graph.nodes:
        if node.node_type == NodeType.INTERCEPT:
            node.role = NodeRole.INTERCEPT
            continue
        if node.node_type == NodeType.ERROR:
            node.role = NodeRole.ERROR
            continue
        if node.node_type == NodeType.CONSTANT:
            node.role = NodeRole.CONSTANT
            continue

        usage_roles: Set[NodeRole] = set()

        if node.name in usage["loading_lhs"]:
            usage_roles.add(NodeRole.LATENT)

        if node.name in usage["loading_rhs"]:
            usage_roles.add(NodeRole.INDICATOR)

        if (
            node.name in usage["regression_sources"]
            and node.name not in usage["regression_targets"]
        ):
            usage_roles.add(NodeRole.EXOGENOUS)

        if node.name in usage["regression_targets"]:
            usage_roles.add(NodeRole.ENDOGENOUS)

        if not usage_roles:
            node.role = (
                NodeRole.LATENT
                if node.node_type == NodeType.LATENT
                else NodeRole.VARIABLE
            )
        elif len(usage_roles) == 1:
            node.role = next(iter(usage_roles))
        else:
            node.role = NodeRole.MIXED


def _collect_node_usage(graph: SemGraph) -> Dict[str, Set[str]]:
    usage = {
        "loading_lhs": set(),
        "loading_rhs": set(),
        "regression_sources": set(),
        "regression_targets": set(),
    }

    for stmt in graph.statements:
        if stmt.stmt_type == StatementType.LOADING:
            usage["loading_lhs"].add(stmt.lhs)
            usage["loading_rhs"].add(stmt.rhs)

        elif stmt.stmt_type == StatementType.REGRESSION:
            usage["regression_sources"].add(stmt.rhs)
            usage["regression_targets"].add(stmt.lhs)

    return usage


# ============================================================
# Residual / variance policy
# ============================================================

def _should_render_as_residual_node(graph: SemGraph, node_name: str) -> bool:
    """
    Textbook SEM default policy:

    - observed variables -> residual/error node
    - latent variables -> keep self-loop variance

    This keeps CFA/path diagrams looking more textbook-like while
    avoiding overcomplicating latent variance rendering.
    """
    node = graph.get_node(node_name)
    if node is None:
        return False

    if node.node_type == NodeType.OBSERVED:
        return True

    return False


# ============================================================
# Synthetic nodes
# ============================================================

def _ensure_intercept_nodes(graph: SemGraph) -> None:
    """
    For each intercept statement x ~ 1, create a synthetic intercept node.
    """
    intercept_targets = sorted({
        stmt.lhs
        for stmt in _iter_statements_of_type(graph, StatementType.INTERCEPT)
    })

    for target in intercept_targets:
        graph.ensure_node(
            name=_intercept_node_name(target),
            node_type=NodeType.INTERCEPT,
            role=NodeRole.INTERCEPT,
            label="1",
            metadata={
                "target": target,
                "synthetic": True,
                "semantic_kind": "intercept",
            },
        )


def _ensure_error_nodes(graph: SemGraph) -> None:
    """
    For each variance statement eligible for textbook residual rendering,
    create a synthetic error node.

    Example:
      x1 ~~ x1  ->  ERR__x1
    """
    residual_targets = sorted({
        stmt.lhs
        for stmt in _iter_statements_of_type(graph, StatementType.VARIANCE)
        if _should_render_as_residual_node(graph, stmt.lhs)
    })

    for target in residual_targets:
        graph.ensure_node(
            name=_error_node_name(target),
            node_type=NodeType.ERROR,
            role=NodeRole.ERROR,
            label="",
            metadata={
                "target": target,
                "synthetic": True,
                "semantic_kind": "residual",
            },
        )


# ============================================================
# Edge construction
# ============================================================

def _build_edges_from_statements(graph: SemGraph) -> None:
    """
    Build semantic edges for:
    - loadings
    - regressions
    - covariances
    - variances

    Notes:
    - intercept edges are built later after synthetic intercept nodes exist
    - observed-variable variances are not rendered here as self-loops;
      they are rendered later as textbook residual/error edges
    """
    for stmt in graph.statements:
        if stmt.stmt_type == StatementType.LOADING:
            _add_edge(
                graph,
                source=stmt.lhs,
                target=stmt.rhs,
                relation=EdgeRelation.LOADING,
                stmt=stmt,
                directed=True,
                bidirectional=False,
            )
            continue

        if stmt.stmt_type == StatementType.REGRESSION:
            _add_edge(
                graph,
                source=stmt.rhs,
                target=stmt.lhs,
                relation=EdgeRelation.REGRESSION,
                stmt=stmt,
                directed=True,
                bidirectional=False,
            )
            continue

        if stmt.stmt_type == StatementType.COVARIANCE:
            _add_edge(
                graph,
                source=stmt.lhs,
                target=stmt.rhs,
                relation=EdgeRelation.COVARIANCE,
                stmt=stmt,
                directed=False,
                bidirectional=True,
            )
            continue

        if stmt.stmt_type == StatementType.VARIANCE:
            if _should_render_as_residual_node(graph, stmt.lhs):
                continue

            _add_edge(
                graph,
                source=stmt.lhs,
                target=stmt.lhs,
                relation=EdgeRelation.VARIANCE,
                stmt=stmt,
                directed=True,
                bidirectional=False,
            )
            continue

        if stmt.stmt_type == StatementType.INTERCEPT:
            continue

        graph.add_message(
            Severity.INFO,
            "unhandled_statement_type_in_edge_builder",
            f"Statement type '{stmt.stmt_type.value}' was not explicitly handled during edge building.",
            line_no=stmt.line_no,
            context=stmt.raw,
        )


# ============================================================
# Intercept edges
# ============================================================

def _build_intercept_edges(graph: SemGraph) -> None:
    """
    Build directed edges from synthetic intercept nodes to their targets.
    """
    for stmt in _iter_statements_of_type(graph, StatementType.INTERCEPT):
        intercept_name = _intercept_node_name(stmt.lhs)

        if graph.get_node(intercept_name) is None:
            graph.add_message(
                Severity.ERROR,
                "missing_intercept_node",
                f"Expected synthetic intercept node '{intercept_name}' but it was not found.",
                line_no=stmt.line_no,
                context=stmt.raw,
            )
            continue

        if graph.get_node(stmt.lhs) is None:
            graph.add_message(
                Severity.ERROR,
                "missing_intercept_target_node",
                f"Expected intercept target node '{stmt.lhs}' but it was not found.",
                line_no=stmt.line_no,
                context=stmt.raw,
            )
            continue

        _add_edge(
            graph,
            source=intercept_name,
            target=stmt.lhs,
            relation=EdgeRelation.INTERCEPT,
            stmt=stmt,
            directed=True,
            bidirectional=False,
            extra_metadata={
                "synthetic_source": True,
                "semantic_kind": "intercept",
            },
        )


# ============================================================
# Residual edges
# ============================================================

def _build_residual_edges(graph: SemGraph) -> None:
    """
    Build textbook-style residual/error edges for observed-variable variances.

    Example:
      x1 ~~ x1  becomes  ERR__x1 -> x1

    We currently keep relation=VARIANCE for compatibility, but mark the edge
    with metadata semantic_kind='residual' so the renderer can style it
    differently from a self-loop variance edge.
    """
    for stmt in _iter_statements_of_type(graph, StatementType.VARIANCE):
        if not _should_render_as_residual_node(graph, stmt.lhs):
            continue

        error_name = _error_node_name(stmt.lhs)

        if graph.get_node(error_name) is None:
            graph.add_message(
                Severity.ERROR,
                "missing_error_node",
                f"Expected synthetic error node '{error_name}' but it was not found.",
                line_no=stmt.line_no,
                context=stmt.raw,
            )
            continue

        if graph.get_node(stmt.lhs) is None:
            graph.add_message(
                Severity.ERROR,
                "missing_residual_target_node",
                f"Expected residual target node '{stmt.lhs}' but it was not found.",
                line_no=stmt.line_no,
                context=stmt.raw,
            )
            continue

        _add_edge(
            graph,
            source=error_name,
            target=stmt.lhs,
            relation=EdgeRelation.RESIDUAL,
            stmt=stmt,
            directed=True,
            bidirectional=False,
            extra_metadata={
                "synthetic_source": True,
                "semantic_kind": "residual",
            },
        )


# ============================================================
# Duplicate detection
# ============================================================

def _detect_duplicate_edges(graph: SemGraph) -> None:
    """
    Flag duplicate semantic edges without removing them.
    """
    grouped: Dict[str, list[Edge]] = defaultdict(list)

    for edge in graph.edges:
        grouped[edge.key()].append(edge)

    for key, edges in grouped.items():
        if len(edges) < 2:
            continue

        raw_context = " ; ".join(
            e.metadata.get("raw", "").strip()
            for e in edges
            if e.metadata.get("raw", "").strip()
        )

        graph.add_message(
            Severity.WARNING,
            "duplicate_edge",
            f"Duplicate semantic edge detected: {key}",
            context=raw_context or None,
        )


# ============================================================
# Metadata
# ============================================================

def _populate_graph_metadata(graph: SemGraph) -> None:
    """
    Add graph-level summary metadata.
    """
    node_type_counts = Counter(node.node_type.value for node in graph.nodes)
    role_counts = Counter(node.role.value for node in graph.nodes)
    edge_relation_counts = Counter(edge.relation.value for edge in graph.edges)

    graph.metadata["summary"] = {
        "n_nodes": len(graph.nodes),
        "n_edges": len(graph.edges),
        "n_statements": len(graph.statements),
        "n_defined_parameters": len(graph.defined_parameters),
        "n_constraints": len(graph.constraints),
        "node_type_counts": dict(node_type_counts),
        "role_counts": dict(role_counts),
        "edge_relation_counts": dict(edge_relation_counts),
        "n_messages": len(graph.messages),
        "n_warnings": len(graph.warning_messages()),
        "n_errors": len(graph.error_messages()),
    }

    graph.metadata["node_names"] = [node.name for node in graph.nodes]
    graph.metadata["edge_keys"] = [edge.key() for edge in graph.edges]
