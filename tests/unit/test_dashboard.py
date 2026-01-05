"""
Tests para endpoints de dashboard.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch
from datetime import datetime

from tests.utils.factories import EventFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user


class TestDashboardOverview:
    """Tests para GET /dashboard/overview"""

    @pytest.mark.asyncio
    async def test_get_overview(self, client: AsyncClient, authenticated_user):
        """Obtiene resumen general del dashboard."""
        mock_conn = MockDBConnection()

        mock_conn.set_fetchrow_return("SELECT", {
            "total": 5,
            "active": 3,
            "upcoming": 2,
            "past": 2
        })
        mock_conn.set_fetchrow_return("SELECT COUNT", {"total_sold": 500, "total_revenue": 50000000})
        mock_conn.set_fetch_return("SELECT c.id", [EventFactory.create()])
        mock_conn.set_fetchrow_return("COUNT", {"sales_count": 10, "revenue": 1000000})

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/dashboard/overview")

        assert response.status_code == 200
        data = response.json()
        assert "total_events" in data
        assert "total_revenue" in data


class TestEventSummary:
    """Tests para GET /dashboard/events/{id}/summary"""

    @pytest.mark.asyncio
    async def test_get_event_summary(self, client: AsyncClient, authenticated_user):
        """Obtiene resumen de ventas de evento."""
        mock_conn = MockDBConnection()

        summary = {
            "event_id": 1,
            "event_name": "Festival Test",
            "event_date": datetime.now(),
            "event_status": "active",
            "created_at": datetime.now(),
            "total_capacity": 1000,
            "available_units": 700,
            "sold_units": 250,
            "reserved_units": 50,
            "total_revenue": 25000000,
            "pending_revenue": 5000000
        }
        mock_conn.set_fetchrow_return("SELECT", summary)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/dashboard/events/1/summary")

        assert response.status_code == 200
        data = response.json()
        assert data["total_capacity"] == 1000
        assert data["sold_units"] == 250

    @pytest.mark.asyncio
    async def test_get_event_summary_not_found(self, client: AsyncClient, authenticated_user):
        """Evento no encontrado retorna 404."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/dashboard/events/999/summary")

        assert response.status_code == 404


class TestAreaBreakdown:
    """Tests para GET /dashboard/events/{id}/areas"""

    @pytest.mark.asyncio
    async def test_get_area_breakdown(self, client: AsyncClient, authenticated_user):
        """Obtiene desglose por área."""
        mock_conn = MockDBConnection()

        mock_conn.set_fetchrow_return("SELECT id FROM clusters", {"id": 1})
        areas = [
            {
                "area_id": 1,
                "area_name": "VIP",
                "base_price": 250000,
                "total_units": 100,
                "sold_units": 80,
                "available_units": 15,
                "reserved_units": 5,
                "revenue": 20000000
            },
            {
                "area_id": 2,
                "area_name": "General",
                "base_price": 100000,
                "total_units": 500,
                "sold_units": 200,
                "available_units": 290,
                "reserved_units": 10,
                "revenue": 20000000
            }
        ]
        mock_conn.set_fetch_return("SELECT a.id", areas)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/dashboard/events/1/areas")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


class TestRevenueReport:
    """Tests para GET /dashboard/events/{id}/revenue"""

    @pytest.mark.asyncio
    async def test_get_revenue_report(self, client: AsyncClient, authenticated_user):
        """Obtiene reporte de ingresos."""
        mock_conn = MockDBConnection()

        mock_conn.set_fetchrow_return("SELECT id, cluster_name", {"id": 1, "cluster_name": "Festival"})
        mock_conn.set_fetchrow_return("SELECT", {
            "gross_revenue": 50000000,
            "refunds": 1000000,
            "transaction_count": 450,
            "tickets_sold": 500
        })
        mock_conn.set_fetch_return("SELECT COALESCE", [])

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/dashboard/events/1/revenue")

        assert response.status_code == 200
        data = response.json()
        assert "gross_revenue" in data
        assert "net_revenue" in data


class TestCheckInAnalytics:
    """Tests para GET /dashboard/events/{id}/checkins"""

    @pytest.mark.asyncio
    async def test_get_checkin_analytics(self, client: AsyncClient, authenticated_user):
        """Obtiene analíticas de check-in."""
        mock_conn = MockDBConnection()

        mock_conn.set_fetchrow_return("SELECT id, cluster_name", {
            "id": 1,
            "cluster_name": "Festival",
            "start_date": datetime.now()
        })
        mock_conn.set_fetchrow_return("SELECT COUNT", {
            "total_tickets": 500,
            "checked_in": 200,
            "pending": 280,
            "transferred": 15,
            "cancelled": 5,
            "first_check_in": datetime.now(),
            "last_check_in": datetime.now()
        })
        mock_conn.set_fetch_return("SELECT a.area_name", [])

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/dashboard/events/1/checkins")

        assert response.status_code == 200
        data = response.json()
        assert data["total_tickets"] == 500
        assert data["checked_in"] == 200


class TestAttendeesList:
    """Tests para GET /dashboard/events/{id}/attendees"""

    @pytest.mark.asyncio
    async def test_get_attendees_list(self, client: AsyncClient, authenticated_user):
        """Obtiene lista de asistentes."""
        mock_conn = MockDBConnection()

        mock_conn.set_fetchrow_return("SELECT id FROM clusters", {"id": 1})
        attendees = [
            {
                "ticket_id": 1,
                "status": "confirmed",
                "area_name": "VIP",
                "nomenclature_letter_area": "VIP",
                "nomenclature_number_unit": 1,
                "owner_name": "Juan Pérez",
                "owner_email": "juan@test.com",
                "purchase_date": datetime.now(),
                "last_update": datetime.now()
            }
        ]
        mock_conn.set_fetch_return("SELECT ru.id", attendees)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/dashboard/events/1/attendees")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    @pytest.mark.asyncio
    async def test_get_attendees_with_filter(self, client: AsyncClient, authenticated_user):
        """Filtra asistentes por status."""
        mock_conn = MockDBConnection()

        mock_conn.set_fetchrow_return("SELECT id FROM clusters", {"id": 1})
        mock_conn.set_fetch_return("SELECT ru.id", [])

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/dashboard/events/1/attendees?status=used")

        assert response.status_code == 200
