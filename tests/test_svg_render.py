from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_svg_render():
    response = client.post(
        "/render",
        json={
            "syntax": "visual =~ x1 + x2 + x3",
            "include_dot": True,
            "include_svg": True
        }
    )

    assert response.status_code == 200

    data = response.json()

    assert "svg" in data
    assert data["svg"] is not None
    assert "<svg" in data["svg"]
    assert "</svg>" in data["svg"]