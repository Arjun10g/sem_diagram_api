from __future__ import annotations

from typing import Any, Dict, Optional

from app.models.sem_graph import SemGraph
from app.services.dot_renderer import DotRenderOptions, render_sem_graph_to_dot
from app.services.graph_builder import build_sem_graph
from app.services.parser import parse_sem_syntax
from app.services.validator import validate_sem_graph
from app.utils.graphviz_helpers import dot_to_svg


def run_parse_pipeline(syntax: str) -> SemGraph:
    """Parse only."""
    return parse_sem_syntax(syntax)


def run_graph_pipeline(
    syntax: str,
    *,
    strict_validation: bool = True,
) -> SemGraph:
    """Parse → build graph → validate."""
    parsed = parse_sem_syntax(syntax)
    semantic = build_sem_graph(parsed)
    validated = validate_sem_graph(semantic)

    if strict_validation and validated.has_errors():
        msg = "; ".join(m.message for m in validated.error_messages()) \
              or "Graph validation failed."
        raise ValueError(msg)

    return validated


def run_render_pipeline(
    syntax: str,
    render_options: Optional[DotRenderOptions] = None,
    *,
    include_dot: bool = True,
    include_svg: bool = False,
    strict_validation: bool = True,
) -> Dict[str, Any]:
    """
    Full pipeline: parse → build → validate → render.

    Returns dict with keys: graph, dot, svg.
    """
    render_options = render_options or DotRenderOptions()
    graph = run_graph_pipeline(syntax, strict_validation=strict_validation)

    dot: Optional[str] = None
    svg: Optional[str] = None

    if include_dot or include_svg:
        dot = render_sem_graph_to_dot(graph, options=render_options)

    if include_svg and dot is not None:
        svg = dot_to_svg(dot)

    return {"graph": graph, "dot": dot, "svg": svg}
