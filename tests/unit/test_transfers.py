"""
Tests para endpoints de transferencias.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from datetime import datetime, timedelta

from tests.utils.factories import TransferFactory, ReservationUnitFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user


class TestInitiateTransfer:
    """Tests para POST /transfers/initiate"""

    @pytest.mark.asyncio
    async def test_initiate_transfer(self, client: AsyncClient, authenticated_user):
        """Inicia transferencia exitosamente."""
        mock_conn = MockDBConnection()

        ticket = {
            "id": 1,
            "status": "confirmed",
            "user_id": authenticated_user.user_id,
            "cluster_name": "Festival",
            "area_name": "VIP",
            "nomenclature_letter_area": "VIP",
            "nomenclature_number_unit": 1,
            "owner_name": "Test User",
            "owner_email": "test@test.com",
            "start_date": datetime.now() + timedelta(days=30)
        }
        mock_conn.set_fetchrow_return("SELECT ru.id", ticket)
        mock_conn.set_fetchrow_return("SELECT id FROM ticket_transfers", None)
        mock_conn.set_fetchrow_return("SELECT id, name FROM profile", {"id": "recipient-id", "name": "Recipient"})

        transfer = TransferFactory.create()
        mock_conn.set_fetchrow_return("INSERT INTO unit_transfer_log", transfer)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/transfers/initiate",
                    json={
                        "reservation_unit_id": 1,
                        "recipient_email": "friend@test.com",
                        "message": "Te regalo esta entrada"
                    }
                )

        assert response.status_code == 201
        data = response.json()
        assert "transfer_token" in data

    @pytest.mark.asyncio
    async def test_initiate_transfer_not_owner(self, client: AsyncClient, authenticated_user):
        """No es dueño del ticket retorna error."""
        mock_conn = MockDBConnection()
        ticket = {"id": 1, "status": "confirmed", "user_id": "other-user"}
        mock_conn.set_fetchrow_return("SELECT ru.id", ticket)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/transfers/initiate",
                    json={"reservation_unit_id": 1, "recipient_email": "friend@test.com"}
                )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_initiate_transfer_already_pending(self, client: AsyncClient, authenticated_user):
        """Ya tiene transferencia pendiente retorna error."""
        mock_conn = MockDBConnection()
        ticket = {"id": 1, "status": "confirmed", "user_id": authenticated_user.user_id}
        mock_conn.set_fetchrow_return("SELECT ru.id", ticket)
        mock_conn.set_fetchrow_return("SELECT id FROM ticket_transfers", {"id": 1})

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/transfers/initiate",
                    json={"reservation_unit_id": 1, "recipient_email": "friend@test.com"}
                )

        assert response.status_code == 400


class TestAcceptTransfer:
    """Tests para POST /transfers/accept"""

    @pytest.mark.asyncio
    async def test_accept_transfer(self, client: AsyncClient, authenticated_user):
        """Acepta transferencia exitosamente."""
        mock_conn = MockDBConnection()

        expires_at = datetime.now() + timedelta(hours=24)
        transfer = {
            "id": 1,
            "reservation_unit_id": 1,
            "unit_id": 1,
            "current_owner": "original-owner",
            "slug_cluster": "festival",
            "transfer_reason": f"PENDING|token123|{authenticated_user.email}|{expires_at.isoformat()}|"
        }
        mock_conn.set_fetchrow_return("SELECT utl.*", transfer)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id, authenticated_user.email):
                response = await client.post(
                    "/transfers/accept",
                    json={"transfer_token": "token123"}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_accept_transfer_expired(self, client: AsyncClient, authenticated_user):
        """Transferencia expirada retorna error."""
        mock_conn = MockDBConnection()

        expires_at = datetime.now() - timedelta(hours=24)  # Expirado
        transfer = {
            "id": 1,
            "reservation_unit_id": 1,
            "transfer_reason": f"PENDING|token123|{authenticated_user.email}|{expires_at.isoformat()}|"
        }
        mock_conn.set_fetchrow_return("SELECT utl.*", transfer)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id, authenticated_user.email):
                response = await client.post(
                    "/transfers/accept",
                    json={"transfer_token": "token123"}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "expired" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_accept_transfer_wrong_recipient(self, client: AsyncClient, authenticated_user):
        """Email incorrecto retorna error."""
        mock_conn = MockDBConnection()

        expires_at = datetime.now() + timedelta(hours=24)
        transfer = {
            "id": 1,
            "reservation_unit_id": 1,
            "transfer_reason": f"PENDING|token123|other@email.com|{expires_at.isoformat()}|"
        }
        mock_conn.set_fetchrow_return("SELECT utl.*", transfer)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id, authenticated_user.email):
                response = await client.post(
                    "/transfers/accept",
                    json={"transfer_token": "token123"}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False


class TestCancelTransfer:
    """Tests para POST /transfers/cancel/{reservation_unit_id}"""

    @pytest.mark.asyncio
    async def test_cancel_transfer(self, client: AsyncClient, authenticated_user):
        """Cancela transferencia exitosamente."""
        mock_conn = MockDBConnection()

        transfer = {"id": 1, "from_user_id": authenticated_user.user_id}
        mock_conn.set_fetchrow_return("SELECT utl.id", transfer)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post("/transfers/cancel/1")

        assert response.status_code == 204


class TestGetTransfers:
    """Tests para listar transferencias"""

    @pytest.mark.asyncio
    async def test_get_outgoing_transfers(self, client: AsyncClient, authenticated_user):
        """Lista transferencias enviadas."""
        mock_conn = MockDBConnection()

        transfers = [
            {
                "id": 1,
                "reservation_unit_id": 1,
                "initiated_at": datetime.now(),
                "transfer_reason": "PENDING|token|email@test.com|2025-12-31|",
                "event_name": "Festival",
                "nomenclature_letter_area": "VIP",
                "nomenclature_number_unit": 1
            }
        ]
        mock_conn.set_fetch_return("SELECT utl.id", transfers)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/transfers/outgoing")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    @pytest.mark.asyncio
    async def test_get_incoming_transfers(self, client: AsyncClient, authenticated_user):
        """Lista transferencias recibidas."""
        mock_conn = MockDBConnection()

        expires_at = datetime.now() + timedelta(hours=24)
        transfers = [
            {
                "id": 1,
                "reservation_unit_id": 1,
                "from_user_id": "sender-id",
                "initiated_at": datetime.now(),
                "transfer_reason": f"PENDING|token|{authenticated_user.email}|{expires_at.isoformat()}|Hello",
                "event_name": "Festival",
                "event_date": datetime.now() + timedelta(days=30),
                "area_name": "VIP",
                "nomenclature_letter_area": "VIP",
                "nomenclature_number_unit": 1,
                "from_user_name": "Sender",
                "from_user_email": "sender@test.com"
            }
        ]
        mock_conn.set_fetch_return("SELECT utl.id", transfers)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id, authenticated_user.email):
                response = await client.get("/transfers/incoming")

        assert response.status_code == 200
