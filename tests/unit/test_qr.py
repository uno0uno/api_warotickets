"""
Tests para endpoints de QR codes.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch

from tests.utils.factories import ReservationUnitFactory, EventFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user


class TestGenerateQR:
    """Tests para GET /qr/{reservation_unit_id}"""

    @pytest.mark.asyncio
    async def test_generate_qr_code(self, client: AsyncClient, authenticated_user):
        """Genera QR para ticket."""
        mock_conn = MockDBConnection()
        ticket = {
            "id": 1,
            "unit_id": 1,
            "status": "confirmed",
            "user_id": authenticated_user.user_id,
            "slug_cluster": "festival-test"
        }
        mock_conn.set_fetchrow_return("SELECT ru.id", ticket)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/qr/1")

        assert response.status_code == 200
        data = response.json()
        assert "qr_code_base64" in data
        assert "qr_code_data_url" in data

    @pytest.mark.asyncio
    async def test_generate_qr_not_owner(self, client: AsyncClient, authenticated_user):
        """No es dueño del ticket retorna error."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT ru.id", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/qr/999")

        assert response.status_code == 400


class TestValidateQR:
    """Tests para POST /qr/validate"""

    @pytest.mark.asyncio
    async def test_validate_qr_valid(self, client: AsyncClient, authenticated_user):
        """QR válido permite entrada."""
        mock_conn = MockDBConnection()
        ticket = {
            "id": 1,
            "unit_id": 1,
            "status": "confirmed",
            "slug_cluster": "festival-test",
            "cluster_name": "Festival Test",
            "owner_name": "Test User",
            "owner_email": "test@test.com",
            "area_name": "VIP",
            "nomenclature_letter_area": "VIP",
            "nomenclature_number_unit": 1,
            "event_start": None
        }
        mock_conn.set_fetchrow_return("SELECT ru.id", ticket)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with patch('app.utils.qr_generator.verify_qr_signature') as mock_verify:
                mock_verify.return_value = {
                    "reservation_unit_id": 1,
                    "unit_id": 1,
                    "user_id": "user-1",
                    "event_slug": "festival-test"
                }
                with mock_authenticated_user(authenticated_user.user_id):
                    response = await client.post(
                        "/qr/validate",
                        json={
                            "qr_data": "WT:1|1|user-1|festival-test|123456|abc123",
                            "event_slug": "festival-test"
                        }
                    )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True

    @pytest.mark.asyncio
    async def test_validate_qr_invalid_signature(self, client: AsyncClient, authenticated_user):
        """Firma alterada rechaza QR."""
        with patch('app.utils.qr_generator.verify_qr_signature') as mock_verify:
            mock_verify.return_value = None
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/qr/validate",
                    json={
                        "qr_data": "WT:invalid|data",
                        "event_slug": "festival-test"
                    }
                )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["result"] == "invalid_signature"

    @pytest.mark.asyncio
    async def test_validate_qr_already_used(self, client: AsyncClient, authenticated_user):
        """Ticket ya usado rechaza QR."""
        mock_conn = MockDBConnection()
        ticket = {"id": 1, "status": "used", "slug_cluster": "festival-test"}
        mock_conn.set_fetchrow_return("SELECT ru.id", ticket)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with patch('app.utils.qr_generator.verify_qr_signature') as mock_verify:
                mock_verify.return_value = {"reservation_unit_id": 1}
                with mock_authenticated_user(authenticated_user.user_id):
                    response = await client.post(
                        "/qr/validate",
                        json={"qr_data": "WT:data", "event_slug": "festival-test"}
                    )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert data["result"] == "already_used"


class TestCheckInStats:
    """Tests para GET /qr/stats/{cluster_id}"""

    @pytest.mark.asyncio
    async def test_get_check_in_stats(self, client: AsyncClient, authenticated_user):
        """Obtiene estadísticas de check-in."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT id, cluster_name", {"id": 1, "cluster_name": "Test"})
        mock_conn.set_fetchrow_return("SELECT", {
            "total_tickets": 100,
            "checked_in": 45,
            "pending": 55,
            "last_check_in": None
        })

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/qr/stats/1")

        assert response.status_code == 200
        data = response.json()
        assert data["total_tickets"] == 100
        assert data["checked_in"] == 45


class TestResetTicket:
    """Tests para POST /qr/reset/{reservation_unit_id}"""

    @pytest.mark.asyncio
    async def test_reset_ticket_status(self, client: AsyncClient, authenticated_user):
        """Reset de ticket usado a confirmado."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT ru.id", {"id": 1})
        mock_conn.execute_returns["UPDATE reservation_units"] = "UPDATE 1"

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post("/qr/reset/1")

        assert response.status_code == 204
