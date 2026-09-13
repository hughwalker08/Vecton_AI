from app.core.config import settings


def test_root_reports_the_api_is_running(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": f"{settings.PROJECT_NAME} API is running."}


def test_health_check(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
