"""
Tests para endpoints de eventos.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from datetime import datetime, timedelta

from tests.utils.factories import EventFactory, UserFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager, mock_authenticated_user


class TestListEvents:
    """Tests para GET /events"""

    @pytest.mark.asyncio
    async def test_list_events(self, client: AsyncClient, authenticated_user):
        """Lista eventos del organizador."""
        mock_conn = MockDBConnection()
        events = [EventFactory.create(id=i) for i in range(1, 4)]
        mock_conn.set_fetch_return("FROM clusters", events)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/events")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    @pytest.mark.asyncio
    async def test_list_events_filter_active(self, client: AsyncClient, authenticated_user):
        """Filtra eventos por is_active."""
        mock_conn = MockDBConnection()
        active_events = [EventFactory.create(is_active=True)]
        mock_conn.set_fetch_return("FROM clusters", active_events)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/events?is_active=true")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_events_empty(self, client: AsyncClient, authenticated_user):
        """Retorna lista vacía si no hay eventos."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetch_return("FROM clusters", [])

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/events")

        assert response.status_code == 200
        assert response.json() == []


class TestGetEvent:
    """Tests para GET /events/{id}"""

    @pytest.mark.asyncio
    async def test_get_event_by_id(self, client: AsyncClient, authenticated_user):
        """Obtiene evento por ID."""
        mock_conn = MockDBConnection()
        event = EventFactory.create(id=1, profile_id=authenticated_user.user_id)
        mock_conn.set_fetchrow_return("WHERE c.id = $1", event)
        mock_conn.set_fetch_return("FROM cluster_images", [])

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/events/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1

    @pytest.mark.asyncio
    async def test_get_event_not_found(self, client: AsyncClient, authenticated_user):
        """Evento no existe retorna 404."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("WHERE c.id = $1", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/events/999")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_event_not_owner(self, client: AsyncClient, authenticated_user):
        """No es dueño del evento retorna 404."""
        mock_conn = MockDBConnection()
        # Evento existe pero con otro profile_id
        mock_conn.set_fetchrow_return("WHERE c.id = $1", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.get("/events/1")

        assert response.status_code == 404


class TestCreateEvent:
    """Tests para POST /events"""

    @pytest.mark.asyncio
    async def test_create_event(self, client: AsyncClient, authenticated_user):
        """Crea evento exitosamente."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT id FROM clusters WHERE slug", None)

        new_event = EventFactory.create(profile_id=authenticated_user.user_id)
        mock_conn.set_fetchrow_return("INSERT INTO clusters", new_event)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/events",
                    json={
                        "cluster_name": "Nuevo Festival",
                        "description": "Un gran festival",
                        "start_date": "2025-06-15T18:00:00",
                        "end_date": "2025-06-15T23:59:00",
                        "cluster_type": "festival"
                    }
                )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_event_generates_slug(self, client: AsyncClient, authenticated_user):
        """Auto-genera slug desde el nombre."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT id FROM clusters WHERE slug", None)

        new_event = EventFactory.create(
            cluster_name="Mi Evento Especial",
            slug_cluster="mi-evento-especial"
        )
        mock_conn.set_fetchrow_return("INSERT INTO clusters", new_event)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.post(
                    "/events",
                    json={
                        "cluster_name": "Mi Evento Especial",
                        "start_date": "2025-06-15T18:00:00"
                    }
                )

        assert response.status_code == 201
        data = response.json()
        assert data["slug_cluster"] == "mi-evento-especial"


class TestUpdateEvent:
    """Tests para PUT /events/{id}"""

    @pytest.mark.asyncio
    async def test_update_event(self, client: AsyncClient, authenticated_user):
        """Actualiza evento exitosamente."""
        mock_conn = MockDBConnection()
        event = EventFactory.create(id=1, profile_id=authenticated_user.user_id)

        mock_conn.set_fetchrow_return("SELECT id FROM clusters WHERE id", {"id": 1})
        mock_conn.set_fetchrow_return("UPDATE clusters", event)
        mock_conn.set_fetchrow_return("WHERE c.id = $1", event)
        mock_conn.set_fetch_return("FROM cluster_images", [])

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.put(
                    "/events/1",
                    json={"description": "Nueva descripción"}
                )

        assert response.status_code == 200


class TestDeleteEvent:
    """Tests para DELETE /events/{id}"""

    @pytest.mark.asyncio
    async def test_delete_event(self, client: AsyncClient, authenticated_user):
        """Soft delete evento exitosamente."""
        mock_conn = MockDBConnection()
        mock_conn.execute_returns["UPDATE clusters"] = "UPDATE 1"

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.delete("/events/1")

        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_event_not_found(self, client: AsyncClient, authenticated_user):
        """Eliminar evento que no existe retorna 404."""
        mock_conn = MockDBConnection()
        mock_conn.execute_returns["UPDATE clusters"] = "UPDATE 0"

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with mock_authenticated_user(authenticated_user.user_id):
                response = await client.delete("/events/999")

        assert response.status_code == 404


class TestPublicEvents:
    """Tests para endpoints públicos de eventos."""

    @pytest.mark.asyncio
    async def test_get_event_by_slug_public(self, client: AsyncClient):
        """Acceso público a evento por slug."""
        mock_conn = MockDBConnection()
        event = EventFactory.create(slug_cluster="festival-test")
        mock_conn.set_fetchrow_return("WHERE c.slug_cluster = $1", event)
        mock_conn.set_fetch_return("FROM cluster_images", [])

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.get("/public/events/festival-test")

        assert response.status_code == 200
        data = response.json()
        assert data["slug_cluster"] == "festival-test"

    @pytest.mark.asyncio
    async def test_list_public_events(self, client: AsyncClient):
        """Lista eventos públicos sin autenticación."""
        mock_conn = MockDBConnection()
        events = [EventFactory.create(is_active=True) for _ in range(3)]
        mock_conn.set_fetch_return("FROM clusters", events)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.get("/public/events")

        assert response.status_code == 200
        assert len(response.json()) == 3
