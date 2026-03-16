from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_examples_endpoint():
    response = client.get("/examples")
    assert response.status_code == 200
