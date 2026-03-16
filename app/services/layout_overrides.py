"""
layout_overrides.py
===================
Applies user-supplied position and routing overrides to a SemGraph
before DOT rendering.

This is the bridge between the drag-and-drop UI layer and the Graphviz
DOT renderer.  Overrides are sent in the API request, stamped onto the
graph objects, and then picked up by dot_renderer at render time.

Position overrides
------------------
- Stamp x/y coordinates (in Graphviz point units, 72 DPI) onto Node objects.
- Nodes with positions will have  pos="x,y!"  emitted in DOT.
- Switching from dot→neato is triggered automatically in the renderer when
  any node has a pinned position.

Edge route overrides
--------------------
- Mark specific edges for straight-line rendering.
- Stored in edge.metadata["straight"] = True.
- dot_renderer sets  splines=line  when any edge carries this hint.

R Shiny round-trip
------------------
Client JS extracts node positions from the rendered SVG in Graphviz
point coords, sends them back in the next POST request.  Subsequent
renders use those positions to maintain the user's layout while still
routing edges cleanly with neato.
"""

from __future__ import annotations
import math

from dataclasses import dataclass
from typing import Dict, List, Set

from app.models.sem_graph import Severity, SemGraph


# ============================================================
# Override data structures
# ============================================================

@dataclass
class NodePositionOverride:
    """
    Pin a named node to a fixed position in the Graphviz coordinate space.

    x, y are in Graphviz point units (72 DPI), with origin at bottom-left
    of the diagram.  These values are what the SVG drag JS reports back.

    pinned=True  →  pos="x,y!"  in DOT (position is exact and fixed)
    pinned=False →  pos="x,y"   in DOT (position is a hint, neato may adjust)
    """
    name: str
    x: float
    y: float
    pinned: bool = True


@dataclass
class EdgeRouteOverride:
    """
    Override the routing style for a specific edge.

    straight=True requests a straight-line path instead of the default spline.
    This is stored as metadata on the Edge object; the dot_renderer switches
    to splines=line when any edge carries this hint.
    """
    source: str
    target: str
    straight: bool = False


# ============================================================
# Application functions
# ============================================================

def _coerce_position_override(o) -> NodePositionOverride:
    """Accept either a NodePositionOverride dataclass or a plain dict."""
    if isinstance(o, dict):
        x = float(o["x"])
        y = float(o["y"])
        # Reject non-finite values — these crash json.dumps and produce
        # broken neato layouts.  Treat them as missing (return None sentinel).
        if not (math.isfinite(x) and math.isfinite(y)):
            return None  # caller must filter
        return NodePositionOverride(
            name=o["name"],
            x=x,
            y=y,
            pinned=bool(o.get("pinned", True)),
        )
    if isinstance(o, NodePositionOverride):
        if not (math.isfinite(o.x) and math.isfinite(o.y)):
            return None
    return o


def apply_position_overrides(
    graph: SemGraph,
    overrides: List[NodePositionOverride],
) -> None:
    """
    Stamp override x/y positions onto Node objects in-place.

    Must be called after build_sem_graph and before render_sem_graph_to_dot.

    Accepts either NodePositionOverride dataclass instances or plain dicts
    with keys 'name', 'x', 'y', and optionally 'pinned' (default True).
    This lets callers pass raw dicts from test code or deserialized JSON
    without wrapping them in the dataclass first.
    """
    if not overrides:
        return

    coerced = [c for o in overrides
               if (c := _coerce_position_override(o)) is not None]
    pos_map: Dict[str, NodePositionOverride] = {o.name: o for o in coerced}
    node_names: Set[str] = {node.name for node in graph.nodes}

    for node in graph.nodes:
        override = pos_map.get(node.name)
        if override is None:
            continue
        node.x = override.x
        node.y = override.y
        node.metadata["pinned"] = override.pinned

    unmatched = [o.name for o in coerced if o.name not in node_names]
    if unmatched:
        graph.add_message(
            Severity.WARNING,
            "unmatched_position_overrides",
            f"Position overrides specified for unknown nodes: {', '.join(sorted(unmatched))}",
        )


def apply_edge_route_overrides(
    graph: SemGraph,
    overrides: List[EdgeRouteOverride],
) -> None:
    """
    Mark edges with routing hints in-place.

    straight=True edges store metadata["straight"] = True.
    The dot_renderer checks for this when choosing the global spline mode.
    """
    if not overrides:
        return

    for override in overrides:
        for edge in graph.edges:
            if edge.source == override.source and edge.target == override.target:
                if override.straight:
                    edge.metadata["straight"] = True
                break


# ============================================================
# Query helpers (used by dot_renderer)
# ============================================================

def has_position_overrides(graph: SemGraph) -> bool:
    """Return True if any node has pinned coordinates."""
    return any(
        node.x is not None and node.y is not None
        for node in graph.nodes
    )


def has_straight_edge_overrides(graph: SemGraph) -> bool:
    """Return True if any edge is marked for straight-line routing."""
    return any(e.metadata.get("straight") for e in graph.edges)
