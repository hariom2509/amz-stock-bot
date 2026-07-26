"""
Tests for Product API endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture
def auth_headers():
    reg = client.post("/api/v1/auth/register", json={}).json()
    return {"Authorization": f"Bearer {reg['client_token']}"}


def test_add_invalid_url(auth_headers):
    response = client.post("/api/v1/products", json={"url": "https://www.google.com"}, headers=auth_headers)
    assert response.status_code == 400
    assert "Invalid Amazon URL" in response.json()["detail"]


def test_add_valid_product(auth_headers):
    url = "https://www.amazon.in/dp/B0CHX1W1XY"
    response = client.post("/api/v1/products", json={"url": url}, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["asin"] == "B0CHX1W1XY"
    assert data["url"] == "https://www.amazon.in/dp/B0CHX1W1XY"


def test_list_products(auth_headers):
    url1 = "https://www.amazon.in/dp/B0CHX1W1XY"
    url2 = "https://www.amazon.in/dp/B09XS7JWHH"
    client.post("/api/v1/products", json={"url": url1}, headers=auth_headers)
    client.post("/api/v1/products", json={"url": url2}, headers=auth_headers)

    response = client.get("/api/v1/products", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2


def test_turbo_mode(auth_headers):
    url = "https://www.amazon.in/dp/B0CHX1W1XY"
    client.post("/api/v1/products", json={"url": url}, headers=auth_headers)

    response = client.post("/api/v1/products/B0CHX1W1XY/turbo", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["mode"] == "TURBO"

    # Return to normal
    response_norm = client.post("/api/v1/products/B0CHX1W1XY/normal", headers=auth_headers)
    assert response_norm.status_code == 200
    assert response_norm.json()["mode"] == "NORMAL"


def test_remove_product(auth_headers):
    url = "https://www.amazon.in/dp/B0CHX1W1XY"
    client.post("/api/v1/products", json={"url": url}, headers=auth_headers)

    response = client.delete("/api/v1/products/B0CHX1W1XY", headers=auth_headers)
    assert response.status_code == 200

    # List should now be empty
    response_list = client.get("/api/v1/products", headers=auth_headers)
    assert response_list.json()["count"] == 0
