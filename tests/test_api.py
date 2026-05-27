import pytest
from fastapi.testclient import TestClient
from main import app


client = TestClient(app)


def test_health_check():
    """Test health check endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


def test_cache_status():
    """Test cache status endpoint."""
    response = client.get("/api/cache/status")
    assert response.status_code == 200
    assert "status" in response.json()
