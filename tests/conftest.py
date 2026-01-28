"""
Configuración global de pytest y fixtures compartidos.
"""
import pytest
import asyncio
from typing import AsyncGenerator, Generator
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.config import settings


# ============================================================================
# Configuración de Event Loop
# ============================================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Crea un event loop para toda la sesión de tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Cliente HTTP Async
# ============================================================================

@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP async para hacer requests al API."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ============================================================================
# Mock de Base de Datos
# ============================================================================

@pytest.fixture
def mock_db_connection():
    """Mock de conexión a base de datos."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.execute = AsyncMock(return_value="UPDATE 1")
    mock_conn.fetchval = AsyncMock(return_value=None)

    return mock_conn


@pytest.fixture(autouse=True)
def mock_db(mock_db_connection):
    """Context manager mock para get_db_connection."""
    class MockContextManager:
        async def __aenter__(self):
            return mock_db_connection

        async def __aexit__(self, *args):
            pass

    # Patch both the original module and where it's imported in middleware
    with patch('app.database.get_db_connection', return_value=MockContextManager()):
        with patch('app.core.middleware.get_db_connection', return_value=MockContextManager()):
            yield mock_db_connection


# ============================================================================
# Datos de Prueba - Usuario
# ============================================================================

@pytest.fixture
def test_user_data():
    """Datos de usuario de prueba."""
    return {
        "id": "test-user-123",
        "email": "test@warotickets.com",
        "name": "Test User"
    }


@pytest.fixture
def test_user_db_row(test_user_data):
    """Row de base de datos para usuario."""
    return {
        "id": test_user_data["id"],
        "email": test_user_data["email"],
        "name": test_user_data["name"],
        "created_at": "2025-01-01T00:00:00"
    }


# ============================================================================
# Datos de Prueba - Evento
# ============================================================================

@pytest.fixture
def test_event_data():
    """Datos de evento de prueba."""
    return {
        "id": 1,
        "cluster_name": "Festival Test 2025",
        "slug_cluster": "festival-test-2025",
        "description": "Un festival de prueba",
        "start_date": "2025-06-15T18:00:00",
        "end_date": "2025-06-15T23:59:00",
        "cluster_type": "festival",
        "is_active": True,
        "shadowban": False,
        "profile_id": "test-user-123"
    }


@pytest.fixture
def test_event_db_row(test_event_data):
    """Row de base de datos para evento."""
    return {
        **test_event_data,
        "total_capacity": 1000,
        "tickets_sold": 150,
        "tickets_available": 850,
        "created_at": "2025-01-01T00:00:00",
        "updated_at": "2025-01-01T00:00:00"
    }


# ============================================================================
# Datos de Prueba - Área
# ============================================================================

@pytest.fixture
def test_area_data():
    """Datos de área de prueba."""
    return {
        "id": 1,
        "cluster_id": 1,
        "area_name": "VIP",
        "description": "Zona VIP",
        "capacity": 100,
        "base_price": 250000.0,
        "is_active": True
    }


# ============================================================================
# Datos de Prueba - Unit
# ============================================================================

@pytest.fixture
def test_unit_data():
    """Datos de unit de prueba."""
    return {
        "id": 1,
        "area_id": 1,
        "nomenclature_letter_area": "VIP",
        "nomenclature_number_unit": 1,
        "status": "available",
        "price": 250000.0
    }


# ============================================================================
# Datos de Prueba - Reservación
# ============================================================================

@pytest.fixture
def test_reservation_data():
    """Datos de reservación de prueba."""
    return {
        "id": 1,
        "user_id": "test-user-123",
        "cluster_id": 1,
        "status": "pending",
        "total_price": 500000.0,
        "promotion_code": None
    }


# ============================================================================
# Mock de Autenticación
# ============================================================================

@pytest.fixture
def authenticated_user(test_user_data):
    """Mock de usuario autenticado."""
    mock_user = MagicMock()
    mock_user.user_id = test_user_data["id"]
    mock_user.email = test_user_data["email"]
    mock_user.name = test_user_data["name"]
    mock_user.tenant_id = "test-tenant-123"
    return mock_user


@pytest.fixture
def auth_headers():
    """Headers con cookie de sesión."""
    return {"Cookie": "session-token=test-session-token-123"}


@pytest.fixture
def mock_auth(authenticated_user):
    """Mock del dependency de autenticación."""
    with patch(
        'app.core.dependencies.get_authenticated_user',
        return_value=authenticated_user
    ):
        yield authenticated_user


# ============================================================================
# Mock de Servicios Externos
# ============================================================================

@pytest.fixture
def mock_email_service():
    """Mock del servicio de email."""
    with patch('app.services.email_service.send_email', new_callable=AsyncMock) as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def mock_upload_service():
    """Mock del servicio de upload."""
    with patch('app.services.upload_service.upload_image', new_callable=AsyncMock) as mock:
        mock.return_value = {
            "image_id": 1,
            "url": "https://r2.example.com/test.jpg",
            "key": "images/test.jpg"
        }
        yield mock


# ============================================================================
# Utilidades
# ============================================================================

@pytest.fixture
def make_db_row():
    """Factory para crear rows de base de datos."""
    def _make_row(data: dict):
        """Crea un objeto que actúa como asyncpg Record."""
        class MockRecord(dict):
            def __getitem__(self, key):
                return self.get(key)

        return MockRecord(data)

    return _make_row
