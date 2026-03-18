"""
Tests para endpoints de áreas.
"""
import pytest
from decimal import Decimal
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock

from tests.utils.factories import AreaFactory, EventFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user
from app.services import areas_service
from app.services.areas_service import calculate_service_fee
from app.models.area import AreaUpdate
from app.core.exceptions import ValidationError


class TestListAreas:
    """Tests para GET /areas/event/{event_id}"""

    @pytest.mark.asyncio
    async def test_list_areas_by_event(self, client: AsyncClient, authenticated_user):
        """Lista áreas de un evento."""
        mock_conn = MockDBConnection()
        areas = [AreaFactory.create(id=i, cluster_id=1) for i in range(1, 4)]
        mock_conn.set_fetch_return("SELECT a.* FROM areas", areas)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/areas/event/1")

        assert response.status_code == 200
        assert len(response.json()) == 3


class TestGetArea:
    """Tests para GET /areas/{id}"""

    @pytest.mark.asyncio
    async def test_get_area_by_id(self, client: AsyncClient, authenticated_user):
        """Obtiene área por ID."""
        mock_conn = MockDBConnection()
        area = AreaFactory.create(id=1)
        mock_conn.set_fetchrow_return("SELECT a.* FROM areas", area)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/areas/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1

    @pytest.mark.asyncio
    async def test_area_not_found(self, client: AsyncClient, authenticated_user):
        """Área no existe retorna 404."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT a.* FROM areas", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/areas/999")

        assert response.status_code == 404


class TestCreateArea:
    """Tests para POST /areas"""

    @pytest.mark.asyncio
    async def test_create_area(self, client: AsyncClient, authenticated_user):
        """Crea área exitosamente."""
        mock_conn = MockDBConnection()

        # Verificar que evento existe y pertenece al usuario
        event = EventFactory.create(profile_id=authenticated_user.user_id)
        mock_conn.set_fetchrow_return("SELECT id FROM clusters", event)

        new_area = AreaFactory.create(id=1)
        mock_conn.set_fetchrow_return("INSERT INTO areas", new_area)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/areas",
                    json={
                        "cluster_id": 1,
                        "area_name": "VIP",
                        "capacity": 100,
                        "base_price": 250000
                    }
                )

        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_area_auto_units(self, client: AsyncClient, authenticated_user):
        """Crea área y genera units automáticamente."""
        mock_conn = MockDBConnection()

        event = EventFactory.create(profile_id=authenticated_user.user_id)
        mock_conn.set_fetchrow_return("SELECT id FROM clusters", event)

        new_area = AreaFactory.create(id=1, capacity=50)
        mock_conn.set_fetchrow_return("INSERT INTO areas", new_area)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/areas",
                    json={
                        "cluster_id": 1,
                        "area_name": "General",
                        "capacity": 50,
                        "base_price": 100000,
                        "auto_generate_units": True,
                        "nomenclature_prefix": "G"
                    }
                )

        assert response.status_code == 201


class TestUpdateArea:
    """Tests para PUT /areas/{id}"""

    @pytest.mark.asyncio
    async def test_update_area(self, client: AsyncClient, authenticated_user):
        """Actualiza área exitosamente."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT a.id FROM areas", {"id": 1})

        area = AreaFactory.create(id=1, base_price=300000)
        mock_conn.set_fetchrow_return("UPDATE areas", area)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.put(
                    "/areas/1",
                    json={"base_price": 300000}
                )

        assert response.status_code == 200


class TestDeleteArea:
    """Tests para DELETE /areas/{id}"""

    @pytest.mark.asyncio
    async def test_delete_area(self, client: AsyncClient, authenticated_user):
        """Elimina área exitosamente."""
        mock_conn = MockDBConnection()
        mock_conn.execute_returns["DELETE FROM areas"] = "DELETE 1"

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.delete("/areas/1")

        assert response.status_code == 204


class TestUpdateAreaServiceFees:
    """Tests para la recalculación de service fees al editar capacity o price."""

    def _area_row(self, **kwargs) -> dict:
        """Crea un dict compatible con el modelo Area."""
        defaults = {
            "id": 1, "cluster_id": 1, "area_name": "VIP",
            "description": None, "capacity": 100, "price": 100000,
            "currency": "COP", "status": "available",
            "nomenclature_letter": "V", "unit_capacity": None,
            "service": 3681.0, "extra_attributes": {},
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        }
        defaults.update(kwargs)
        return defaults

    def _make_conn(self, existing_capacity: int = 100, fetchval_side_effect=None):
        """Construye un MockDBConnection pre-configurado para update_area."""
        mock_conn = MockDBConnection()
        # Ownership check returns area with current capacity
        mock_conn.set_fetchrow_return(
            "SELECT a.id, a.capacity FROM areas",
            {"id": 1, "capacity": existing_capacity}
        )
        # UPDATE areas RETURNING * — used by update_area() dynamic query
        mock_conn.set_fetchrow_return("UPDATE areas", self._area_row(capacity=existing_capacity))
        # get_area_by_id final fetch (JOIN clusters query)
        mock_conn.set_fetchrow_return("JOIN clusters", self._area_row())

        # executemany needed by _generate_units_for_area
        mock_conn.executemany = AsyncMock(return_value=None)

        if fetchval_side_effect:
            mock_conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
        else:
            mock_conn.fetchval = AsyncMock(return_value=0)

        return mock_conn

    @pytest.mark.asyncio
    async def test_update_price_triggers_recalculation(self):
        """Al cambiar price, _recalculate_cluster_service_fees debe ejecutarse."""
        mock_conn = self._make_conn(fetchval_side_effect=[500])  # total_capacity = 500

        # Patch at the service module level (areas_service already imported get_db_connection)
        with patch('app.services.areas_service.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            data = AreaUpdate(price=Decimal('250000'))
            await areas_service.update_area(1, 1, "profile-1", "tenant-1", data)

        assert mock_conn.was_called_with("execute", "SET service = CASE")

    @pytest.mark.asyncio
    async def test_update_capacity_syncs_cluster_total_capacity(self):
        """Al cambiar capacity, clusters.total_capacity se actualiza."""
        mock_conn = self._make_conn(
            existing_capacity=100,
            fetchval_side_effect=[0, 350, None]  # active_units check, new_total_capacity, nomenclature
        )

        with patch('app.services.areas_service.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            data = AreaUpdate(capacity=150)
            await areas_service.update_area(1, 1, "profile-1", "tenant-1", data)

        assert mock_conn.was_called_with("execute", "UPDATE clusters SET total_capacity")

    @pytest.mark.asyncio
    async def test_update_capacity_triggers_recalculation_of_all_areas(self):
        """Al cambiar capacity, _recalculate_cluster_service_fees se ejecuta para el cluster."""
        mock_conn = self._make_conn(
            existing_capacity=200,
            fetchval_side_effect=[0, 600, None]  # active_units=0, new_total=600, nomenclature=None
        )

        with patch('app.services.areas_service.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            data = AreaUpdate(capacity=400)  # 200 → 400, cluster total 400 → 600
            await areas_service.update_area(1, 1, "profile-1", "tenant-1", data)

        assert mock_conn.was_called_with("execute", "SET service = CASE")
        assert mock_conn.was_called_with("execute", "UPDATE clusters SET total_capacity")

    @pytest.mark.asyncio
    async def test_update_capacity_reduction_blocked_when_active_units_exceed_new_cap(self):
        """No permite reducir capacity si hay más unidades activas que la nueva capacidad."""
        mock_conn = self._make_conn(
            existing_capacity=200,
            fetchval_side_effect=[150]  # 150 active (sold/reserved) units
        )

        with patch('app.services.areas_service.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            data = AreaUpdate(capacity=100)  # Trying to reduce to 100 but 150 are active
            with pytest.raises(ValidationError) as exc_info:
                await areas_service.update_area(1, 1, "profile-1", "tenant-1", data)

        assert "150" in str(exc_info.value)
        assert "100" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_update_non_price_capacity_fields_skip_recalculation(self):
        """Cambiar area_name o description NO llama a _recalculate_cluster_service_fees."""
        mock_conn = self._make_conn()

        with patch('app.services.areas_service.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            data = AreaUpdate(area_name="Nuevo Nombre", description="Nueva descripción")
            await areas_service.update_area(1, 1, "profile-1", "tenant-1", data)

        mock_conn.fetchval.assert_not_called()
        assert not mock_conn.was_called_with("execute", "UPDATE clusters SET total_capacity")


class TestCalculateServiceFee:
    """Tests unitarios para calculate_service_fee() — fórmula plana price * 3.26% + $1,894."""

    def test_fee_boleta_economica(self):
        """$30,000 → fee = ROUND(30000*0.0326 + 1894) = $2,872"""
        fee = calculate_service_fee(Decimal('30000'))
        assert fee == Decimal('2872')

    def test_fee_boleta_media(self):
        """$100,000 → fee = ROUND(100000*0.0326 + 1894) = $5,154"""
        fee = calculate_service_fee(Decimal('100000'))
        assert fee == Decimal('5154')

    def test_fee_boleta_premium(self):
        """$300,000 → fee = ROUND(300000*0.0326 + 1894) = $11,674"""
        fee = calculate_service_fee(Decimal('300000'))
        assert fee == Decimal('11674')

    def test_fee_gratuita(self):
        """Precio $0 → fee = $0"""
        fee = calculate_service_fee(Decimal('0'))
        assert fee == Decimal('0')

    def test_fee_precio_negativo(self):
        """Precio negativo → fee = $0 (guard)"""
        fee = calculate_service_fee(Decimal('-1000'))
        assert fee == Decimal('0')
