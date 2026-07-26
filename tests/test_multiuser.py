"""
Tests for multi-user isolation and shared ASIN monitoring logic.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_multiuser_isolation():
    user1_reg = client.post("/api/v1/auth/register", json={}).json()
    user2_reg = client.post("/api/v1/auth/register", json={}).json()

    h1 = {"Authorization": f"Bearer {user1_reg['client_token']}"}
    h2 = {"Authorization": f"Bearer {user2_reg['client_token']}"}

    # User 1 watches Product A
    client.post("/api/v1/products", json={"url": "https://www.amazon.in/dp/B0USER1111"}, headers=h1)

    # User 2 watches Product B
    client.post("/api/v1/products", json={"url": "https://www.amazon.in/dp/B0USER2222"}, headers=h2)

    # User 1 should only see Product A
    list1 = client.get("/api/v1/products", headers=h1).json()
    assert list1["count"] == 1
    assert list1["products"][0]["asin"] == "B0USER1111"

    # User 2 should only see Product B
    list2 = client.get("/api/v1/products", headers=h2).json()
    assert list2["count"] == 1
    assert list2["products"][0]["asin"] == "B0USER2222"


def test_shared_asin_deduplication():
    user1_reg = client.post("/api/v1/auth/register", json={}).json()
    user2_reg = client.post("/api/v1/auth/register", json={}).json()

    h1 = {"Authorization": f"Bearer {user1_reg['client_token']}"}
    h2 = {"Authorization": f"Bearer {user2_reg['client_token']}"}

    shared_url = "https://www.amazon.in/dp/B0SHARED99"

    # Both users watch SAME ASIN
    p1 = client.post("/api/v1/products", json={"url": shared_url}, headers=h1).json()
    p2 = client.post("/api/v1/products", json={"url": shared_url}, headers=h2).json()

    assert p1["asin"] == "B0SHARED99"
    assert p2["asin"] == "B0SHARED99"

    # Deleting User 1's watch should not delete User 2's watch
    client.delete("/api/v1/products/B0SHARED99", headers=h1)

    list2 = client.get("/api/v1/products", headers=h2).json()
    assert list2["count"] == 1
    assert list2["products"][0]["asin"] == "B0SHARED99"
