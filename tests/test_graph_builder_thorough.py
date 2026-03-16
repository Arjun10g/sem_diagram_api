from app.services.parser import parse_sem_syntax
from app.services.graph_builder import build_sem_graph


def test_nodes_created():
    syntax = "f =~ x1 + x2"
    parsed = parse_sem_syntax(syntax)
    graph = build_sem_graph(parsed)
    names = {n.name for n in graph.nodes}
    assert "f" in names
    assert "x1" in names


def test_edges_created():
    syntax = "y ~ x"
    parsed = parse_sem_syntax(syntax)
    graph = build_sem_graph(parsed)
    assert len(graph.edges) == 1
