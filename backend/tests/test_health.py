from fastapi.testclient import TestClient


def test_health_no_database():
    """Root health probe should not hit DB."""
    from ai_interview_analysis.api.app import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"
