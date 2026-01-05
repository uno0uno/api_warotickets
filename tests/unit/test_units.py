"""
Tests para endpoints de units (boletos).
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch

from tests.utils.factories import UnitFactory, AreaFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user


class TestListUnits:
    """Tests para GET /units/area/{area_id}"""

    @pytest.mark.asyncio
    async def test_list_units_by_area(self, client: AsyncClient, authenticated_user):
        """Lista units de un área."""
        mock_conn = MockDBConnection()
        units = [UnitFactory.create(id=i, area_id=1) for i in range(1, 11)]
        mock_conn.set_fetch_return("SELECT u.* FROM units", units)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/units/area/1")

        assert response.status_code == 200
        assert len(response.json()) == 10

    @pytest.mark.asyncio
    async def test_list_units_filter_status(self, client: AsyncClient, authenticated_user):
        """Filtra units por status."""
        mock_conn = MockDBConnection()
        units = [UnitFactory.create(status="available")]
        mock_conn.set_fetch_return("SELECT u.* FROM units", units)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/units/area/1?status=available")

        assert response.status_code == 200


class TestCreateUnitsBulk:
    """Tests para POST /units/bulk"""

    @pytest.mark.asyncio
    async def test_create_units_bulk(self, client: AsyncClient, authenticated_user):
        """Crea múltiples units."""
        mock_conn = MockDBConnection()

        # Verificar área existe
        area = AreaFactory.create()
        mock_conn.set_fetchrow_return("SELECT a.* FROM areas", area)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/units/bulk",
                    json={
                        "area_id": 1,
                        "quantity": 50,
                        "nomenclature_prefix": "A",
                        "start_number": 1
                    }
                )

        assert response.status_code == 201
        data = response.json()
        assert data["created_count"] == 50

    @pytest.mark.asyncio
    async def test_create_units_nomenclature(self, client: AsyncClient, authenticated_user):
        """Genera nomenclatura correcta."""
        mock_conn = MockDBConnection()

        area = AreaFactory.create()
        mock_conn.set_fetchrow_return("SELECT a.* FROM areas", area)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/units/bulk",
                    json={
                        "area_id": 1,
                        "quantity": 5,
                        "nomenclature_prefix": "VIP",
                        "start_number": 10
                    }
                )

        assert response.status_code == 201


class TestUpdateUnitsBulk:
    """Tests para PUT /units/bulk"""

    @pytest.mark.asyncio
    async def test_update_units_bulk(self, client: AsyncClient, authenticated_user):
        """Actualiza múltiples units."""
        mock_conn = MockDBConnection()
        mock_conn.execute_returns["UPDATE units"] = "UPDATE 3"

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.put(
                    "/units/bulk",
                    json={
                        "unit_ids": [1, 2, 3],
                        "status": "available"
                    }
                )

        assert response.status_code == 200
        data = response.json()
        assert data["updated_count"] == 3


class TestGetUnit:
    """Tests para GET /units/{id}"""

    @pytest.mark.asyncio
    async def test_get_unit_by_id(self, client: AsyncClient, authenticated_user):
        """Obtiene unit por ID."""
        mock_conn = MockDBConnection()
        unit = UnitFactory.create(id=1)
        mock_conn.set_fetchrow_return("SELECT u.* FROM units", unit)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/units/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1


class TestUnitStatusChanges:
    """Tests para cambios de estado de units."""

    @pytest.mark.asyncio
    async def test_reserve_unit(self, client: AsyncClient, authenticated_user):
        """Reservar unit cambia status a reserved."""
        mock_conn = MockDBConnection()

        unit = UnitFactory.create(id=1, status="available")
        mock_conn.set_fetchrow_return("SELECT u.* FROM units", unit)
        mock_conn.execute_returns["UPDATE units"] = "UPDATE 1"

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.put(
                    "/units/bulk",
                    json={"unit_ids": [1], "status": "reserved"}
                )

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_release_unit(self, client: AsyncClient, authenticated_user):
        """Liberar unit reservado vuelve a available."""
        mock_conn = MockDBConnection()

        unit = UnitFactory.create(id=1, status="reserved")
        mock_conn.set_fetchrow_return("SELECT u.* FROM units", unit)
        mock_conn.execute_returns["UPDATE units"] = "UPDATE 1"

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.put(
                    "/units/bulk",
                    json={"unit_ids": [1], "status": "available"}
                )

        assert response.status_code == 200
