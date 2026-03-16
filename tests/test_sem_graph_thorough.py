from app.models.sem_graph import SemGraph


def test_graph_initialization():
    g = SemGraph()
    assert g.nodes == []
    assert g.edges == []
