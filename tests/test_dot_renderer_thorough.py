from app.services.parser import parse_sem_syntax
from app.services.graph_builder import build_sem_graph
from app.services.dot_renderer import render_sem_graph_to_dot


def test_dot_contains_digraph():
    syntax = "f =~ x1 + x2"
    g = build_sem_graph(parse_sem_syntax(syntax))
    dot = render_sem_graph_to_dot(g)
    assert "digraph" in dot

from app.services.dot_renderer import DotRenderOptions
from app.services.validator import validate_sem_graph

def test_render_residuals_toggle():
    syntax = "x1 ~~ x1"
    graph = validate_sem_graph(build_sem_graph(parse_sem_syntax(syntax)))

    dot_show = render_sem_graph_to_dot(graph, DotRenderOptions(show_residuals=True))
    dot_hide = render_sem_graph_to_dot(graph, DotRenderOptions(show_residuals=False))

    assert "ERR__x1 -> x1" in dot_show
    assert "ERR__x1 -> x1" not in dot_hide