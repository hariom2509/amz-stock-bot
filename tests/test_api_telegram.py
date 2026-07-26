"""
Tests for Telegram linking API endpoints and deep links.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture
def auth_headers():
    reg = client.post("/api/v1/auth/register", json={}).json()
    return {"Authorization": f"Bearer {reg['client_token']}"}


def test_telegram_link_generation(auth_headers):
    response = client.post("/api/v1/telegram/link", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "deep_link_url" in data
    assert "t.me" in data["deep_link_url"]


def test_telegram_status_unlinked(auth_headers):
    response = client.get("/api/v1/telegram/status", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["linked"] is False


def test_telegram_disconnect(auth_headers):
    response = client.delete("/api/v1/telegram/link", headers=auth_headers)
    assert response.status_code == 200
    assert "disconnected" in response.json()["message"].lower()
