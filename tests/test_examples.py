from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_list_examples():
    response = client.get("/examples")
    assert response.status_code == 200
    data = response.json()
    assert "examples" in data
    assert "cfa.txt" in data["examples"]


def test_get_example():
    response = client.get("/examples/cfa.txt")
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "cfa.txt"
    assert "visual =~ x1 + x2 + x3" in data["syntax"]