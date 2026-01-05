"""
Tests para endpoints de salud.
"""
import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """Tests para endpoints de health check."""

    @pytest.mark.asyncio
    async def test_root_endpoint(self, client: AsyncClient):
        """GET / retorna información del servicio."""
        response = await client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "WaRo Tickets API"
        assert data["version"] == "1.0.0"
        assert "database" in data
        assert "environment" in data

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient):
        """GET /health retorna status healthy."""
        response = await client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "database" in data
        assert "host" in data
