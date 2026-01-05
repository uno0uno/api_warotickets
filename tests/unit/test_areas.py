"""
Tests para endpoints de áreas.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch

from tests.utils.factories import AreaFactory, EventFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user


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
