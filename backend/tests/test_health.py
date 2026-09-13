"""
Phase 0 scaffolding test: proves pytest + FastAPI's TestClient are wired up
correctly. Not a real feature test -- see tests/ subpackages added in later
phases for the document-parsing, config, and route coverage.
"""


def test_health_check_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
