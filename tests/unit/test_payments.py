"""
Tests para endpoints de pagos.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch

from tests.utils.factories import ReservationFactory, PaymentFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user


class TestPaymentIntent:
    """Tests para POST /payments/intent"""

    @pytest.mark.asyncio
    async def test_create_payment_intent(self, client: AsyncClient, authenticated_user):
        """Crea intención de pago exitosamente."""
        mock_conn = MockDBConnection()

        reservation = ReservationFactory.create(
            user_id=authenticated_user.user_id,
            status="pending",
            total_price=250000
        )
        mock_conn.set_fetchrow_return("SELECT r.* FROM reservations", reservation)

        payment = PaymentFactory.create(reservation_id=1)
        mock_conn.set_fetchrow_return("INSERT INTO payments", payment)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/payments/intent",
                    json={
                        "reservation_id": 1,
                        "payment_method": "card"
                    }
                )

        assert response.status_code == 200
        data = response.json()
        assert "payment_id" in data

    @pytest.mark.asyncio
    async def test_payment_intent_invalid_reservation(self, client: AsyncClient, authenticated_user):
        """Reserva inválida retorna error."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT r.* FROM reservations", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/payments/intent",
                    json={"reservation_id": 999, "payment_method": "card"}
                )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_payment_already_paid(self, client: AsyncClient, authenticated_user):
        """Reserva ya pagada retorna error."""
        mock_conn = MockDBConnection()

        reservation = ReservationFactory.create(
            user_id=authenticated_user.user_id,
            status="confirmed"  # Ya confirmada/pagada
        )
        mock_conn.set_fetchrow_return("SELECT r.* FROM reservations", reservation)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/payments/intent",
                    json={"reservation_id": 1, "payment_method": "card"}
                )

        assert response.status_code == 400


class TestGetPayment:
    """Tests para GET /payments/{id}"""

    @pytest.mark.asyncio
    async def test_get_payment_status(self, client: AsyncClient, authenticated_user):
        """Obtiene estado del pago."""
        mock_conn = MockDBConnection()

        payment = PaymentFactory.create(status="approved")
        mock_conn.set_fetchrow_return("SELECT p.* FROM payments", payment)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/payments/1")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"


class TestWompiWebhook:
    """Tests para POST /payments/webhook/wompi"""

    @pytest.mark.asyncio
    async def test_wompi_webhook_approved(self, client: AsyncClient):
        """Webhook de pago aprobado confirma reserva."""
        mock_conn = MockDBConnection()

        reservation = ReservationFactory.create(status="pending")
        mock_conn.set_fetchrow_return("SELECT r.* FROM reservations", reservation)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with patch('app.services.payments_service.verify_wompi_signature') as mock_verify:
                mock_verify.return_value = True

                response = await client.post(
                    "/payments/webhook/wompi",
                    json={
                        "event": "transaction.updated",
                        "data": {
                            "transaction": {
                                "id": "tx_123",
                                "status": "APPROVED",
                                "reference": "1"
                            }
                        },
                        "signature": {"checksum": "valid_checksum"}
                    },
                    headers={"X-Event-Checksum": "valid_checksum"}
                )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_wompi_webhook_declined(self, client: AsyncClient):
        """Webhook de pago rechazado cancela reserva."""
        mock_conn = MockDBConnection()

        reservation = ReservationFactory.create(status="pending")
        mock_conn.set_fetchrow_return("SELECT r.* FROM reservations", reservation)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with patch('app.services.payments_service.verify_wompi_signature') as mock_verify:
                mock_verify.return_value = True

                response = await client.post(
                    "/payments/webhook/wompi",
                    json={
                        "event": "transaction.updated",
                        "data": {
                            "transaction": {
                                "id": "tx_123",
                                "status": "DECLINED",
                                "reference": "1"
                            }
                        },
                        "signature": {"checksum": "valid_checksum"}
                    },
                    headers={"X-Event-Checksum": "valid_checksum"}
                )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_wompi_webhook_invalid_signature(self, client: AsyncClient):
        """Firma inválida rechaza webhook."""
        with patch('app.services.payments_service.verify_wompi_signature') as mock_verify:
            mock_verify.return_value = False

            response = await client.post(
                "/payments/webhook/wompi",
                json={
                    "event": "transaction.updated",
                    "data": {"transaction": {"id": "tx_123"}},
                    "signature": {"checksum": "invalid"}
                },
                headers={"X-Event-Checksum": "invalid"}
            )

        assert response.status_code == 400
