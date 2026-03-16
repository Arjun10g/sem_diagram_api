from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================
# Enums
# ============================================================

class NodeType(str, Enum):
    LATENT = "latent"
    OBSERVED = "observed"
    INTERCEPT = "intercept"
    ERROR = "error"
    CONSTANT = "constant"


# Node-type priority: higher index wins when merging conflicting types.
# LATENT > OBSERVED; synthetic types (INTERCEPT, ERROR, CONSTANT) are fixed
# and should never be silently overridden.
_NODE_TYPE_PRIORITY: Dict[str, int] = {
    NodeType.OBSERVED:   0,
    NodeType.LATENT:     1,
    NodeType.INTERCEPT:  2,
    NodeType.ERROR:      2,
    NodeType.CONSTANT:   2,
}


class NodeRole(str, Enum):
    LATENT = "latent"
    INDICATOR = "indicator"
    EXOGENOUS = "exogenous"
    ENDOGENOUS = "endogenous"
    VARIABLE = "variable"
    INTERCEPT = "intercept"
    ERROR = "error"
    CONSTANT = "constant"
    MIXED = "mixed"


class EdgeRelation(str, Enum):
    LOADING = "loading"
    REGRESSION = "regression"
    COVARIANCE = "covariance"
    VARIANCE = "variance"
    RESIDUAL = "residual"
    INTERCEPT = "intercept"
    MEAN = "mean"
    DEFINED = "defined"
    CONSTRAINT = "constraint"


class StatementType(str, Enum):
    LOADING = "loading"
    REGRESSION = "regression"
    COVARIANCE = "covariance"
    VARIANCE = "variance"
    INTERCEPT = "intercept"
    DEFINED = "defined"
    CONSTRAINT = "constraint"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ============================================================
# Core model classes
# ============================================================

@dataclass
class ParseMessage:
    """
    A message generated during parsing, graph building, or validation.
    Useful for API responses and GUI feedback.
    """
    severity: Severity
    code: str
    message: str
    line_no: Optional[int] = None
    context: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "line_no": self.line_no,
            "context": self.context,
        }


@dataclass
class ParameterSpec:
    """
    Information about a parameter attached to a path.

    Examples:
    - free path: label=None, fixed=None
    - labeled path: label='a'
    - fixed path: fixed=1.0
    """
    label: Optional[str] = None
    fixed: Optional[float] = None
    start: Optional[float] = None
    free: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "fixed": self.fixed,
            "start": self.start,
            "free": self.free,
        }


@dataclass
class ParsedStatement:
    """
    Represents one atomic parsed statement.

    Example:
      visual =~ x1 + x2 + x3

    usually becomes 3 ParsedStatement objects:
      visual -> x1
      visual -> x2
      visual -> x3
    """
    stmt_type: StatementType
    lhs: str
    rhs: str
    operator: str
    line_no: int
    raw: str
    parameter: ParameterSpec = field(default_factory=ParameterSpec)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stmt_type": self.stmt_type.value,
            "lhs": self.lhs,
            "rhs": self.rhs,
            "operator": self.operator,
            "line_no": self.line_no,
            "raw": self.raw,
            "parameter": self.parameter.to_dict(),
            "metadata": self.metadata,
        }


@dataclass
class Node:
    """
    A node in the SEM graph.

    Examples:
    - latent factor: visual
    - observed indicator: x1
    - intercept node: INT__x1
    - residual/error node: ERR__x1
    """
    name: str
    node_type: NodeType
    role: NodeRole = NodeRole.VARIABLE
    graph_id: Optional[str] = None
    label: Optional[str] = None

    # layout hints can be used later by renderer/layout modules
    layer: Optional[str] = None
    group: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.label is None:
            self.label = self.name
        if self.graph_id is None:
            self.graph_id = self.make_graph_id(self.name)

    @staticmethod
    def make_graph_id(name: str) -> str:
        """
        Make a Graphviz-safe identifier from an arbitrary node name.
        """
        out: List[str] = []
        for ch in name:
            if ch.isalnum() or ch == "_":
                out.append(ch)
            else:
                out.append("_")

        graph_id = "".join(out).strip("_")

        if not graph_id:
            graph_id = "node"

        if graph_id[0].isdigit():
            graph_id = f"n_{graph_id}"

        return graph_id

    def is_synthetic(self) -> bool:
        return bool(self.metadata.get("synthetic"))

    def to_dict(self) -> Dict[str, Any]:
        import math as _math
        def _safe_float(v):
            if v is None:
                return None
            try:
                f = float(v)
                return f if _math.isfinite(f) else None
            except (TypeError, ValueError):
                return None
        return {
            "name": self.name,
            "node_type": self.node_type.value,
            "role": self.role.value,
            "graph_id": self.graph_id,
            "label": self.label,
            "layer": self.layer,
            "group": self.group,
            "x": _safe_float(self.x),
            "y": _safe_float(self.y),
            "metadata": self.metadata,
        }


@dataclass
class Edge:
    """
    A directed or bidirectional relation between two nodes.

    Examples:
    - loading: visual -> x1
    - regression: visual -> speed
    - covariance: visual <-> textual
    - variance: visual -> visual
    - residual: ERR__x1 -> x1
    - intercept: INT__x1 -> x1
    """
    source: str
    target: str
    relation: EdgeRelation
    parameter: ParameterSpec = field(default_factory=ParameterSpec)

    directed: bool = True
    bidirectional: bool = False

    label: Optional[str] = None
    graph_attrs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        """
        Stable edge key used for duplicate detection.

        Covariances are symmetric, so normalize source/target order.
        """
        if self.relation == EdgeRelation.COVARIANCE:
            a, b = sorted([self.source, self.target])
            return f"{self.relation.value}|{a}|{b}"
        return f"{self.relation.value}|{self.source}|{self.target}"

    def is_synthetic(self) -> bool:
        return bool(self.metadata.get("synthetic_source"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation.value,
            "parameter": self.parameter.to_dict(),
            "directed": self.directed,
            "bidirectional": self.bidirectional,
            "label": self.label,
            "graph_attrs": self.graph_attrs,
            "metadata": self.metadata,
        }


@dataclass
class DefinedParameter:
    """
    Represents a lavaan-style defined parameter, e.g.

      indirect := a*b
    """
    name: str
    expression: str
    line_no: int
    raw: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "expression": self.expression,
            "line_no": self.line_no,
            "raw": self.raw,
        }


@dataclass
class ConstraintSpec:
    """
    Placeholder for future support of algebraic constraints, e.g.
      a == b
      a > 0
    """
    expression: str
    line_no: int
    raw: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expression": self.expression,
            "line_no": self.line_no,
            "raw": self.raw,
        }


# ============================================================
# Main graph container
# ============================================================

@dataclass
class SemGraph:
    """
    Main internal representation of the SEM.

    This is the central object the rest of the backend should use.
    """
    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    statements: List[ParsedStatement] = field(default_factory=list)
    defined_parameters: List[DefinedParameter] = field(default_factory=list)
    constraints: List[ConstraintSpec] = field(default_factory=list)
    messages: List[ParseMessage] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)

    # --------------------------------------------------------
    # Node helpers
    # --------------------------------------------------------

    def add_node(self, node: Node) -> None:
        if self.get_node(node.name) is None:
            self.nodes.append(node)

    def get_node(self, name: str) -> Optional[Node]:
        for node in self.nodes:
            if node.name == name:
                return node
        return None

    def ensure_node(
        self,
        name: str,
        node_type: NodeType,
        role: NodeRole = NodeRole.VARIABLE,
        **kwargs: Any,
    ) -> Node:
        existing = self.get_node(name)

        if existing is not None:
            self._merge_node(existing, node_type=node_type, role=role, **kwargs)
            return existing

        node = Node(name=name, node_type=node_type, role=role, **kwargs)
        self.nodes.append(node)
        return node

    def _merge_node(
        self,
        existing: Node,
        *,
        node_type: NodeType,
        role: NodeRole,
        **kwargs: Any,
    ) -> None:
        """
        Merge newly inferred node information into an existing node.

        Node-type priority rules (applied silently unless truly ambiguous):
          - LATENT always takes priority over OBSERVED, in either direction.
            This is correct: latent factors regularly appear in regression and
            covariance statements, which default to OBSERVED; the merge should
            preserve their LATENT type without emitting spurious warnings.
          - Synthetic types (INTERCEPT, ERROR, CONSTANT) are never overridden.
          - Any other type conflict is genuinely unexpected → WARNING.
        """
        if existing.node_type != node_type:
            existing_priority = _NODE_TYPE_PRIORITY.get(existing.node_type, -1)
            new_priority = _NODE_TYPE_PRIORITY.get(node_type, -1)

            if new_priority > existing_priority:
                # Promote the node (e.g., OBSERVED → LATENT).
                existing.node_type = node_type
            elif new_priority < existing_priority:
                # Keep the higher-priority type silently.
                # Common case: latent factor referenced in a regression/covariance
                # statement whose default inference is OBSERVED.  No action needed.
                pass
            else:
                # Same priority level but different types — genuinely unexpected.
                self.add_message(
                    Severity.WARNING,
                    "node_type_conflict",
                    f"Node '{existing.name}' appeared with conflicting types "
                    f"of equal priority: {existing.node_type.value} and "
                    f"{node_type.value}.",
                )

        # Role: only update if current role is the default placeholder.
        if existing.role != role and existing.role != NodeRole.MIXED:
            if existing.role == NodeRole.VARIABLE:
                existing.role = role
            elif role not in {NodeRole.VARIABLE, existing.role}:
                existing.role = NodeRole.MIXED

        # Label: only update if still equal to the auto-set name.
        if existing.label == existing.name and kwargs.get("label") is not None:
            existing.label = kwargs["label"]

        # Layer / group: take first non-None value.
        if kwargs.get("layer") is not None and existing.layer is None:
            existing.layer = kwargs["layer"]

        if kwargs.get("group") is not None and existing.group is None:
            existing.group = kwargs["group"]

        # Metadata: merge shallowly.
        new_metadata = kwargs.get("metadata")
        if new_metadata:
            existing.metadata.update(new_metadata)

    def synthetic_nodes(self) -> List[Node]:
        return [n for n in self.nodes if n.is_synthetic()]

    # --------------------------------------------------------
    # Edge helpers
    # --------------------------------------------------------

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def edge_keys(self) -> List[str]:
        return [edge.key() for edge in self.edges]

    def edges_by_relation(self, relation: EdgeRelation) -> List[Edge]:
        return [e for e in self.edges if e.relation == relation]

    def residual_edges(self) -> List[Edge]:
        return [e for e in self.edges if e.relation == EdgeRelation.RESIDUAL]

    # --------------------------------------------------------
    # Statement helpers
    # --------------------------------------------------------

    def add_statement(self, statement: ParsedStatement) -> None:
        self.statements.append(statement)

    def add_defined_parameter(self, defined_parameter: DefinedParameter) -> None:
        self.defined_parameters.append(defined_parameter)

    def add_constraint(self, constraint: ConstraintSpec) -> None:
        self.constraints.append(constraint)

    # --------------------------------------------------------
    # Message helpers
    # --------------------------------------------------------

    def add_message(
        self,
        severity: Severity,
        code: str,
        message: str,
        line_no: Optional[int] = None,
        context: Optional[str] = None,
    ) -> None:
        self.messages.append(
            ParseMessage(
                severity=severity,
                code=code,
                message=message,
                line_no=line_no,
                context=context,
            )
        )

    def info_messages(self) -> List[ParseMessage]:
        return [m for m in self.messages if m.severity == Severity.INFO]

    def warning_messages(self) -> List[ParseMessage]:
        return [m for m in self.messages if m.severity == Severity.WARNING]

    def error_messages(self) -> List[ParseMessage]:
        return [m for m in self.messages if m.severity == Severity.ERROR]

    # --------------------------------------------------------
    # Summaries
    # --------------------------------------------------------

    def node_names(self) -> List[str]:
        return [node.name for node in self.nodes]

    def latent_nodes(self) -> List[Node]:
        return [n for n in self.nodes if n.node_type == NodeType.LATENT]

    def observed_nodes(self) -> List[Node]:
        return [n for n in self.nodes if n.node_type == NodeType.OBSERVED]

    def intercept_nodes(self) -> List[Node]:
        return [n for n in self.nodes if n.node_type == NodeType.INTERCEPT]

    def error_nodes(self) -> List[Node]:
        return [n for n in self.nodes if n.node_type == NodeType.ERROR]

    def constant_nodes(self) -> List[Node]:
        return [n for n in self.nodes if n.node_type == NodeType.CONSTANT]

    def has_errors(self) -> bool:
        return any(m.severity == Severity.ERROR for m in self.messages)

    # --------------------------------------------------------
    # Serialization
    # --------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "statements": [stmt.to_dict() for stmt in self.statements],
            "defined_parameters": [dp.to_dict() for dp in self.defined_parameters],
            "constraints": [c.to_dict() for c in self.constraints],
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
        }
