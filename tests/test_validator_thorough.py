from app.services.parser import parse_sem_syntax
from app.services.graph_builder import build_sem_graph
from app.services.validator import validate_sem_graph


def test_latent_indicator_warning():
    syntax = "f =~ x1"
    g = validate_sem_graph(build_sem_graph(parse_sem_syntax(syntax)))
    assert any("one_indicator" in str(m.code) for m in g.messages)


def test_duplicate_variance_warning():
    syntax = "x ~~ x\nx ~~ x"
    g = validate_sem_graph(build_sem_graph(parse_sem_syntax(syntax)))
    assert len(g.messages) > 0

def test_latent_without_explicit_variance_message():
    syntax = "f =~ x1 + x2 + x3"
    g = validate_sem_graph(build_sem_graph(parse_sem_syntax(syntax)))

    assert any(
        m.code == "latent_without_explicit_variance"
        for m in g.messages
    )