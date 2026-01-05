"""
Mocks para servicios externos y dependencias.
"""
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional, List, Any
from datetime import datetime


class MockDBConnection:
    """Mock de conexión a base de datos asyncpg."""

    def __init__(self):
        self.fetchrow_returns = {}
        self.fetch_returns = {}
        self.execute_returns = {}
        self._call_history = []

    def set_fetchrow_return(self, query_contains: str, value: Any):
        """Configura valor de retorno para fetchrow según query."""
        self.fetchrow_returns[query_contains] = value

    def set_fetch_return(self, query_contains: str, value: List[Any]):
        """Configura valor de retorno para fetch según query."""
        self.fetch_returns[query_contains] = value

    async def fetchrow(self, query: str, *args) -> Optional[dict]:
        """Mock de fetchrow."""
        self._call_history.append(("fetchrow", query, args))

        for key, value in self.fetchrow_returns.items():
            if key in query:
                if callable(value):
                    return value(*args)
                return value
        return None

    async def fetch(self, query: str, *args) -> List[dict]:
        """Mock de fetch."""
        self._call_history.append(("fetch", query, args))

        for key, value in self.fetch_returns.items():
            if key in query:
                if callable(value):
                    return value(*args)
                return value
        return []

    async def execute(self, query: str, *args) -> str:
        """Mock de execute."""
        self._call_history.append(("execute", query, args))

        for key, value in self.execute_returns.items():
            if key in query:
                return value
        return "UPDATE 1"

    async def fetchval(self, query: str, *args) -> Any:
        """Mock de fetchval."""
        self._call_history.append(("fetchval", query, args))
        return None

    def get_call_history(self) -> List[tuple]:
        """Retorna historial de llamadas."""
        return self._call_history

    def was_called_with(self, method: str, query_contains: str) -> bool:
        """Verifica si se llamó un método con cierta query."""
        for call in self._call_history:
            if call[0] == method and query_contains in call[1]:
                return True
        return False


class MockDBContextManager:
    """Context manager mock para get_db_connection."""

    def __init__(self, connection: MockDBConnection = None):
        self.connection = connection or MockDBConnection()

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *args):
        pass


def create_db_mock(connection: MockDBConnection = None):
    """Crea un mock completo de base de datos."""
    conn = connection or MockDBConnection()
    ctx_manager = MockDBContextManager(conn)

    return patch(
        'app.database.get_db_connection',
        return_value=ctx_manager
    ), conn


class MockEmailService:
    """Mock del servicio de email."""

    def __init__(self):
        self.sent_emails = []

    async def send_email(self, to_email: str, subject: str, html_body: str, text_body: str = None):
        """Mock de envío de email."""
        self.sent_emails.append({
            "to": to_email,
            "subject": subject,
            "html_body": html_body,
            "text_body": text_body,
            "sent_at": datetime.now()
        })
        return True

    async def send_transfer_notification(self, recipient_email: str, **kwargs):
        """Mock de notificación de transferencia."""
        self.sent_emails.append({
            "type": "transfer_notification",
            "to": recipient_email,
            **kwargs
        })
        return True

    def get_sent_emails(self) -> List[dict]:
        """Retorna emails enviados."""
        return self.sent_emails

    def was_email_sent_to(self, email: str) -> bool:
        """Verifica si se envió email a dirección."""
        return any(e["to"] == email for e in self.sent_emails)


class MockWompiService:
    """Mock del servicio de Wompi."""

    def __init__(self):
        self.transactions = {}
        self.webhook_calls = []

    def create_transaction(self, reference: str, amount: float) -> dict:
        """Crea transacción mock."""
        tx_id = f"tx_{reference}"
        self.transactions[tx_id] = {
            "id": tx_id,
            "reference": reference,
            "amount": amount,
            "status": "PENDING",
            "created_at": datetime.now()
        }
        return self.transactions[tx_id]

    def approve_transaction(self, tx_id: str):
        """Aprueba transacción."""
        if tx_id in self.transactions:
            self.transactions[tx_id]["status"] = "APPROVED"

    def decline_transaction(self, tx_id: str):
        """Rechaza transacción."""
        if tx_id in self.transactions:
            self.transactions[tx_id]["status"] = "DECLINED"

    def get_webhook_payload(self, tx_id: str) -> dict:
        """Genera payload de webhook."""
        tx = self.transactions.get(tx_id, {})
        return {
            "event": "transaction.updated",
            "data": {
                "transaction": tx
            },
            "signature": {
                "checksum": "mock_checksum"
            }
        }


class MockR2Service:
    """Mock del servicio de Cloudflare R2."""

    def __init__(self):
        self.uploaded_files = {}
        self.deleted_files = []

    async def upload_image(self, file_content: bytes, filename: str, content_type: str, folder: str = "images"):
        """Mock de subida de imagen."""
        key = f"{folder}/{filename}"
        self.uploaded_files[key] = {
            "content": file_content,
            "content_type": content_type,
            "uploaded_at": datetime.now()
        }
        return {
            "image_id": len(self.uploaded_files),
            "url": f"https://r2.example.com/{key}",
            "key": key
        }

    async def delete_image(self, image_id: int) -> bool:
        """Mock de eliminación de imagen."""
        self.deleted_files.append(image_id)
        return True


def mock_authenticated_user(user_id: str = "test-user-123", email: str = "test@test.com"):
    """Crea mock de usuario autenticado."""
    from app.core.dependencies import AuthenticatedUser

    user = AuthenticatedUser(
        user_id=user_id,
        email=email,
        tenant_id=None
    )

    return patch(
        'app.core.dependencies.get_authenticated_user',
        return_value=user
    )


def mock_session_validation():
    """Mock de validación de sesión que siempre pasa."""
    async def mock_middleware(request, call_next):
        response = await call_next(request)
        return response

    return patch(
        'app.core.middleware.session_validation_middleware',
        mock_middleware
    )
