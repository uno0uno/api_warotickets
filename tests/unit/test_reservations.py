"""
Tests para endpoints de reservaciones.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch
from datetime import datetime, timedelta

from tests.utils.factories import ReservationFactory, UnitFactory, AreaFactory, EventFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user


class TestCreateReservation:
    """Tests para POST /reservations"""

    @pytest.mark.asyncio
    async def test_create_reservation(self, client: AsyncClient, authenticated_user):
        """Crea reserva exitosamente."""
        mock_conn = MockDBConnection()
        units = [UnitFactory.create(id=i, status="available") for i in range(1, 4)]
        mock_conn.set_fetch_return("SELECT u.* FROM units", units)

        area = AreaFactory.create(base_price=100000)
        mock_conn.set_fetchrow_return("SELECT a.* FROM areas", area)

        reservation = ReservationFactory.create(id=1, total_price=300000)
        mock_conn.set_fetchrow_return("INSERT INTO reservations", reservation)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/reservations",
                    json={"cluster_id": 1, "unit_ids": [1, 2, 3]}
                )

        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_reservation_unavailable_units(self, client: AsyncClient, authenticated_user):
        """Units no disponibles retorna error."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetch_return("SELECT u.* FROM units", [])

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/reservations",
                    json={"cluster_id": 1, "unit_ids": [1]}
                )

        assert response.status_code == 400


class TestConfirmReservation:
    """Tests para POST /reservations/{id}/confirm"""

    @pytest.mark.asyncio
    async def test_confirm_reservation(self, client: AsyncClient, authenticated_user):
        """Confirma reserva exitosamente."""
        mock_conn = MockDBConnection()
        reservation = ReservationFactory.create(user_id=authenticated_user.user_id, status="pending")
        mock_conn.set_fetchrow_return("SELECT r.* FROM reservations", reservation)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/reservations/1/confirm",
                    json={"payment_reference": "tx_123"}
                )

        assert response.status_code == 200


class TestCancelReservation:
    """Tests para POST /reservations/{id}/cancel"""

    @pytest.mark.asyncio
    async def test_cancel_reservation(self, client: AsyncClient, authenticated_user):
        """Cancela reserva y libera units."""
        mock_conn = MockDBConnection()
        reservation = ReservationFactory.create(user_id=authenticated_user.user_id, status="pending")
        mock_conn.set_fetchrow_return("SELECT r.* FROM reservations", reservation)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post("/reservations/1/cancel")

        assert response.status_code == 200


class TestMyTickets:
    """Tests para GET /reservations/my-tickets"""

    @pytest.mark.asyncio
    async def test_get_my_tickets(self, client: AsyncClient, authenticated_user):
        """Lista tickets del usuario."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetch_return("SELECT", [{"id": 1, "status": "confirmed"}])

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/reservations/my-tickets")

        assert response.status_code == 200
