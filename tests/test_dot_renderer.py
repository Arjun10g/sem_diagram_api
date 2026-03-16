from app.services.parser import parse_sem_syntax
from app.services.graph_builder import build_sem_graph
from app.services.validator import validate_sem_graph
from app.services.dot_renderer import render_sem_graph_to_dot, DotRenderOptions


def test_render_basic_graph():
    text = "visual =~ x1 + x2 + x3"
    graph = validate_sem_graph(build_sem_graph(parse_sem_syntax(text)))
    dot = render_sem_graph_to_dot(graph)

    assert "digraph SEM" in dot
    assert "visual" in dot
    assert "x1" in dot
    assert "->" in dot



def test_render_intercepts_toggle():
    text = "x1 ~ 1"
    graph = validate_sem_graph(build_sem_graph(parse_sem_syntax(text)))

    dot1 = render_sem_graph_to_dot(graph, DotRenderOptions(show_intercepts=True))
    dot2 = render_sem_graph_to_dot(graph, DotRenderOptions(show_intercepts=False))

    assert "INT__x1" in dot1
    assert "INT__x1" not in dot2


def test_render_variances_toggle():
    text = "x1 ~~ x1"
    graph = validate_sem_graph(build_sem_graph(parse_sem_syntax(text)))

    dot1 = render_sem_graph_to_dot(graph, DotRenderOptions(show_variances=True))
    dot2 = render_sem_graph_to_dot(graph, DotRenderOptions(show_variances=False))

    # With textbook residual rendering, variance visibility controls self-loop variances,
    # not residual/error edges.
    assert "ERR__x1 -> x1" in dot1
    assert "ERR__x1 -> x1" in dot2

    # And there should be no literal self-loop in either version for observed x1.
    assert "\\n  x1 -> x1 [" not in dot1
    assert "\\n  x1 -> x1 [" not in dot2


def test_render_parameter_labels():
    text = "y ~ a*x1 + 1*x2"
    graph = validate_sem_graph(build_sem_graph(parse_sem_syntax(text)))
    dot = render_sem_graph_to_dot(graph, DotRenderOptions(show_edge_labels=True))

    assert "a" in dot
    assert "1" in dot