"""
Integration tests for FastAPI application endpoints.
"""
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.services.sales_service import data_store


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_endpoints(client):
    """Verify health endpoints."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["app"] == "Sales Dashboard"


def test_landing_page(client):
    """Verify main landing page renders HTML."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Sales Dashboard" in resp.text
    assert "VD_Sales_Dashboard" in resp.text


def test_sales_alias_page(client):
    """Verify /sales renders same landing page."""
    resp = client.get("/sales")
    assert resp.status_code == 200
    assert "Sales Dashboard" in resp.text


def test_dataset_status_endpoint(client):
    """Verify dataset endpoint."""
    resp = client.get("/api/sales/dataset")
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "status" in data
