"""
Tests unitarios para commissions_service.record_commission().

Verifica:
- Uso de clusters.commission_percentage como fallback (sin override)
- Uso de promoter_event_configs.commission_percentage como override (con precedencia)
- Idempotencia: segunda llamada retorna registro existente sin duplicar
- Retorno None cuando la reserva no tiene promoter_code_id
"""
import pytest
from decimal import Decimal
from unittest.mock import patch

from tests.utils.factories import OrderCommissionFactory, PromoterCodeFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager


RESERVATION_ID = "res-abc-123"
PAYMENT_ID = 1
PROMOTER_CODE_ID = "promo-code-1"
TENANT_MEMBER_ID = "member-1"
TENANT_ID = "tenant-1"
CLUSTER_ID = 1


def _reservation_data(promoter_code_id=PROMOTER_CODE_ID):
    """Base reservation row returned by the first fetchrow in record_commission."""
    return {
        "id": RESERVATION_ID,
        "promoter_code_id": promoter_code_id,
        "cluster_id": CLUSTER_ID,
        "tenant_member_id": TENANT_MEMBER_ID,
        "tenant_id": TENANT_ID,
        "commission_percentage": 10.0,
    }


def _commission_row(commission_percentage: float, has_override: bool):
    """Row returned by the COALESCE query."""
    return {
        "commission_percentage": commission_percentage,
        "has_override": has_override,
    }


class TestRecordCommission:

    @pytest.mark.asyncio
    async def test_uses_cluster_default_when_no_override(self):
        """Compra en evento con 10% cluster default → commission_amount = base_price × 10%."""
        mock_conn = MockDBConnection()

        mock_conn.set_fetchrow_return("FROM reservations r", _reservation_data())
        mock_conn.set_fetchrow_return("FROM order_commissions WHERE reservation_id", None)
        mock_conn.set_fetch_return(
            "FROM reservation_units ru",
            [{"unit_price_paid": 100000}]
        )
        mock_conn.set_fetchrow_return(
            "SELECT COALESCE",
            _commission_row(commission_percentage=10.0, has_override=False)
        )

        inserted_commission = OrderCommissionFactory.create(
            reservation_id=RESERVATION_ID,
            payment_id=PAYMENT_ID,
            promoter_code_id=PROMOTER_CODE_ID,
            tenant_member_id=TENANT_MEMBER_ID,
            tenant_id=TENANT_ID,
            cluster_id=CLUSTER_ID,
            total_base_price=100000.0,
            tickets_count=1,
            commission_percentage=10.0,
            commission_amount=10000.0,
        )
        mock_conn.set_fetchrow_return("INSERT INTO order_commissions", inserted_commission)

        with patch(
            "app.services.commissions_service.get_db_connection",
            return_value=MockDBContextManager(mock_conn)
        ):
            from app.services import commissions_service
            result = await commissions_service.record_commission(
                payment_id=PAYMENT_ID,
                reservation_id=RESERVATION_ID
            )

        assert result is not None
        assert Decimal(str(result["commission_amount"])) == Decimal("10000.00")
        assert Decimal(str(result["commission_percentage"])) == Decimal("10.0")

    @pytest.mark.asyncio
    async def test_uses_override_when_promoter_event_config_exists(self):
        """Compra con override de 15% en promoter_event_configs → commission_amount = base_price × 15%."""
        mock_conn = MockDBConnection()

        mock_conn.set_fetchrow_return("FROM reservations r", _reservation_data())
        mock_conn.set_fetchrow_return("FROM order_commissions WHERE reservation_id", None)
        mock_conn.set_fetch_return(
            "FROM reservation_units ru",
            [{"unit_price_paid": 100000}]
        )
        mock_conn.set_fetchrow_return(
            "SELECT COALESCE",
            _commission_row(commission_percentage=15.0, has_override=True)
        )

        inserted_commission = OrderCommissionFactory.create(
            reservation_id=RESERVATION_ID,
            payment_id=PAYMENT_ID,
            promoter_code_id=PROMOTER_CODE_ID,
            tenant_member_id=TENANT_MEMBER_ID,
            tenant_id=TENANT_ID,
            cluster_id=CLUSTER_ID,
            total_base_price=100000.0,
            tickets_count=1,
            commission_percentage=15.0,
            commission_amount=15000.0,
        )
        mock_conn.set_fetchrow_return("INSERT INTO order_commissions", inserted_commission)

        with patch(
            "app.services.commissions_service.get_db_connection",
            return_value=MockDBContextManager(mock_conn)
        ):
            from app.services import commissions_service
            result = await commissions_service.record_commission(
                payment_id=PAYMENT_ID,
                reservation_id=RESERVATION_ID
            )

        assert result is not None
        assert Decimal(str(result["commission_amount"])) == Decimal("15000.00")
        assert Decimal(str(result["commission_percentage"])) == Decimal("15.0")

    @pytest.mark.asyncio
    async def test_idempotency_returns_existing_on_second_call(self):
        """Re-envío del webhook con mismo reservation_id retorna registro existente sin duplicar."""
        mock_conn = MockDBConnection()

        existing_commission = OrderCommissionFactory.create(
            reservation_id=RESERVATION_ID,
            payment_id=PAYMENT_ID,
            promoter_code_id=PROMOTER_CODE_ID,
            commission_percentage=10.0,
            commission_amount=10000.0,
        )

        mock_conn.set_fetchrow_return("FROM reservations r", _reservation_data())
        mock_conn.set_fetchrow_return("FROM order_commissions WHERE reservation_id", existing_commission)

        with patch(
            "app.services.commissions_service.get_db_connection",
            return_value=MockDBContextManager(mock_conn)
        ):
            from app.services import commissions_service
            result = await commissions_service.record_commission(
                payment_id=PAYMENT_ID,
                reservation_id=RESERVATION_ID
            )

        assert result is not None
        assert result["id"] == existing_commission["id"]
        assert not mock_conn.was_called_with("fetchrow", "INSERT INTO order_commissions")

    @pytest.mark.asyncio
    async def test_returns_none_when_no_promoter_code(self):
        """Reserva sin promoter_code_id → retorna None (sin comisión)."""
        mock_conn = MockDBConnection()

        mock_conn.set_fetchrow_return("FROM reservations r", _reservation_data(promoter_code_id=None))

        with patch(
            "app.services.commissions_service.get_db_connection",
            return_value=MockDBContextManager(mock_conn)
        ):
            from app.services import commissions_service
            result = await commissions_service.record_commission(
                payment_id=PAYMENT_ID,
                reservation_id=RESERVATION_ID
            )

        assert result is None
