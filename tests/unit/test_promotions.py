"""
Tests para endpoints de promociones.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch
from datetime import datetime, timedelta

from tests.utils.factories import PromotionFactory, EventFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user


class TestListPromotions:
    """Tests para GET /promotions/event/{event_id}"""

    @pytest.mark.asyncio
    async def test_list_promotions(self, client: AsyncClient, authenticated_user):
        """Lista promociones de un evento."""
        mock_conn = MockDBConnection()
        promotions = [PromotionFactory.create(id=i) for i in range(1, 4)]
        mock_conn.set_fetch_return("SELECT p.* FROM promotions", promotions)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/promotions/event/1")

        assert response.status_code == 200
        assert len(response.json()) == 3


class TestCreatePromotion:
    """Tests para POST /promotions"""

    @pytest.mark.asyncio
    async def test_create_promotion_percentage(self, client: AsyncClient, authenticated_user):
        """Crea promoción con descuento porcentual."""
        mock_conn = MockDBConnection()

        event = EventFactory.create(profile_id=authenticated_user.user_id)
        mock_conn.set_fetchrow_return("SELECT id FROM clusters", event)

        promotion = PromotionFactory.create(discount_type="percentage", discount_value=20)
        mock_conn.set_fetchrow_return("INSERT INTO promotions", promotion)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/promotions",
                    json={
                        "cluster_id": 1,
                        "code": "DESC20",
                        "discount_type": "percentage",
                        "discount_value": 20,
                        "max_uses": 100,
                        "valid_from": datetime.now().isoformat(),
                        "valid_until": (datetime.now() + timedelta(days=30)).isoformat()
                    }
                )

        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_promotion_fixed(self, client: AsyncClient, authenticated_user):
        """Crea promoción con descuento fijo."""
        mock_conn = MockDBConnection()

        event = EventFactory.create(profile_id=authenticated_user.user_id)
        mock_conn.set_fetchrow_return("SELECT id FROM clusters", event)

        promotion = PromotionFactory.create(discount_type="fixed", discount_value=50000)
        mock_conn.set_fetchrow_return("INSERT INTO promotions", promotion)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/promotions",
                    json={
                        "cluster_id": 1,
                        "code": "50MIL",
                        "discount_type": "fixed",
                        "discount_value": 50000,
                        "max_uses": 50
                    }
                )

        assert response.status_code == 201


class TestValidatePromotion:
    """Tests para POST /promotions/validate"""

    @pytest.mark.asyncio
    async def test_validate_promotion_valid(self, client: AsyncClient, authenticated_user):
        """Código válido retorna descuento."""
        mock_conn = MockDBConnection()

        promotion = PromotionFactory.create(
            code="VALIDO20",
            discount_type="percentage",
            discount_value=20,
            is_active=True,
            current_uses=5,
            max_uses=100
        )
        mock_conn.set_fetchrow_return("SELECT * FROM promotions", promotion)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/promotions/validate",
                    json={
                        "code": "VALIDO20",
                        "cluster_id": 1,
                        "unit_ids": [1, 2]
                    }
                )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True
        assert data["discount_percentage"] == 20

    @pytest.mark.asyncio
    async def test_validate_promotion_expired(self, client: AsyncClient, authenticated_user):
        """Código expirado retorna error."""
        mock_conn = MockDBConnection()

        promotion = PromotionFactory.create(
            code="EXPIRADO",
            valid_until=datetime.now() - timedelta(days=1)  # Ya expiró
        )
        mock_conn.set_fetchrow_return("SELECT * FROM promotions", promotion)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/promotions/validate",
                    json={"code": "EXPIRADO", "cluster_id": 1}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False

    @pytest.mark.asyncio
    async def test_validate_promotion_max_uses(self, client: AsyncClient, authenticated_user):
        """Límite de usos alcanzado retorna error."""
        mock_conn = MockDBConnection()

        promotion = PromotionFactory.create(
            code="AGOTADO",
            current_uses=100,
            max_uses=100  # Ya alcanzó el límite
        )
        mock_conn.set_fetchrow_return("SELECT * FROM promotions", promotion)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/promotions/validate",
                    json={"code": "AGOTADO", "cluster_id": 1}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False


class TestUpdatePromotion:
    """Tests para PUT /promotions/{id}"""

    @pytest.mark.asyncio
    async def test_update_promotion(self, client: AsyncClient, authenticated_user):
        """Actualiza promoción exitosamente."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT p.id FROM promotions", {"id": 1})

        promotion = PromotionFactory.create(max_uses=200)
        mock_conn.set_fetchrow_return("UPDATE promotions", promotion)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.put(
                    "/promotions/1",
                    json={"max_uses": 200}
                )

        assert response.status_code == 200


class TestDeletePromotion:
    """Tests para DELETE /promotions/{id}"""

    @pytest.mark.asyncio
    async def test_delete_promotion(self, client: AsyncClient, authenticated_user):
        """Elimina promoción exitosamente."""
        mock_conn = MockDBConnection()
        mock_conn.execute_returns["DELETE FROM promotions"] = "DELETE 1"

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.delete("/promotions/1")

        assert response.status_code == 204
