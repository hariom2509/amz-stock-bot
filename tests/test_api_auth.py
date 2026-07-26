"""
Tests for API authentication and device registration.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import repository as repo

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["database"] == "ok"


def test_device_register():
    response = client.post("/api/v1/auth/register", json={})
    assert response.status_code == 200
    data = response.json()
    assert "public_id" in data
    assert "client_token" in data
    assert data["public_id"].startswith("usr_")


def test_me_unauthorized():
    response = client.get("/api/v1/me")
    assert response.status_code == 401


def test_me_authorized():
    reg = client.post("/api/v1/auth/register", json={}).json()
    token = reg["client_token"]

    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["public_id"] == reg["public_id"]
    assert data["telegram_linked"] is False
    assert data["watch_count"] == 0
