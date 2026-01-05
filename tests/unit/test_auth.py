"""
Tests for authentication endpoints.
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock
from datetime import datetime, timedelta
import uuid

from tests.utils.factories import UserFactory
from tests.utils.mocks import MockDBConnection, MockDBContextManager


class TestSendMagicLink:
    """Tests for POST /auth/sign-in-magic-link"""

    @pytest.mark.asyncio
    async def test_send_magic_link_new_user(self, client: AsyncClient):
        """Creates new user and sends code."""
        mock_conn = MockDBConnection()

        # User does not exist
        mock_conn.set_fetchrow_return("SELECT id, name, email FROM profile", None)

        # Create user returns new user
        new_user = UserFactory.create()
        mock_conn.set_fetchrow_return("INSERT INTO profile", new_user)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with patch('app.services.email_service.send_email', new_callable=AsyncMock) as mock_email:
                mock_email.return_value = True

                response = await client.post(
                    "/auth/sign-in-magic-link",
                    json={"email": "new@test.com"}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "Code sent" in data["message"]

    @pytest.mark.asyncio
    async def test_send_magic_link_existing_user(self, client: AsyncClient):
        """Existing user receives code."""
        mock_conn = MockDBConnection()
        existing_user = UserFactory.create(email="existing@test.com")
        mock_conn.set_fetchrow_return("SELECT id, name, email FROM profile", existing_user)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            with patch('app.services.email_service.send_email', new_callable=AsyncMock) as mock_email:
                mock_email.return_value = True

                response = await client.post(
                    "/auth/sign-in-magic-link",
                    json={"email": "existing@test.com"}
                )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_send_magic_link_invalid_email(self, client: AsyncClient):
        """Invalid email returns error 422."""
        response = await client.post(
            "/auth/sign-in-magic-link",
            json={"email": "not-an-email"}
        )

        assert response.status_code == 422


class TestVerifyCode:
    """Tests for POST /auth/verify-code"""

    @pytest.mark.asyncio
    async def test_verify_code_success(self, client: AsyncClient):
        """Valid code creates session."""
        mock_conn = MockDBConnection()
        user = UserFactory.create()
        token_id = str(uuid.uuid4())

        mock_conn.set_fetchrow_return("SELECT id, name, email FROM profile", user)
        mock_conn.set_fetchrow_return(
            "SELECT * FROM magic_tokens",
            {
                "id": token_id,
                "user_id": user["id"],
                "token": "123456",
                "used": False,
                "expires_at": datetime.now() + timedelta(minutes=10)
            }
        )

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.post(
                "/auth/verify-code",
                json={"email": user["email"], "code": "123456"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["user_id"] == user["id"]
        assert data["email"] == user["email"]

    @pytest.mark.asyncio
    async def test_verify_code_invalid(self, client: AsyncClient):
        """Invalid code returns error 400."""
        mock_conn = MockDBConnection()
        user = UserFactory.create()

        mock_conn.set_fetchrow_return("SELECT id, name, email FROM profile", user)
        mock_conn.set_fetchrow_return("SELECT * FROM magic_tokens", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.post(
                "/auth/verify-code",
                json={"email": user["email"], "code": "999999"}
            )

        assert response.status_code == 400
        assert "Invalid or expired" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_verify_code_user_not_found(self, client: AsyncClient):
        """User not found returns 404."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT id, name, email FROM profile", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.post(
                "/auth/verify-code",
                json={"email": "notexist@test.com", "code": "123456"}
            )

        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]


class TestVerifyToken:
    """Tests for POST /auth/verify"""

    @pytest.mark.asyncio
    async def test_verify_token_success(self, client: AsyncClient):
        """Valid token creates session."""
        mock_conn = MockDBConnection()
        user = UserFactory.create()
        token_id = str(uuid.uuid4())

        mock_conn.set_fetchrow_return(
            "SELECT mt.*, p.id as user_id",
            {
                "id": token_id,
                "user_id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "token": "abc123token",
                "used": False,
                "expires_at": datetime.now() + timedelta(minutes=10)
            }
        )

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.post(
                "/auth/verify",
                json={"token": "abc123token"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Session started"

    @pytest.mark.asyncio
    async def test_verify_token_invalid(self, client: AsyncClient):
        """Invalid token returns error 400."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT mt.*, p.id as user_id", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.post(
                "/auth/verify",
                json={"token": "invalid-token"}
            )

        assert response.status_code == 400
        assert "Invalid or expired" in response.json()["detail"]


class TestGetCurrentUser:
    """Tests for GET /auth/me"""

    @pytest.mark.asyncio
    async def test_get_current_user(self, client: AsyncClient):
        """Authenticated user gets their information."""
        mock_conn = MockDBConnection()
        user = UserFactory.create()
        session_id = str(uuid.uuid4())

        mock_conn.set_fetchrow_return(
            "SELECT p.id, p.name, p.email",
            {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "expires_at": datetime.now() + timedelta(days=30)
            }
        )

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.get(
                "/auth/me",
                cookies={"session-token": session_id}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["user_id"] == user["id"]
        assert data["message"] == "Authenticated"

    @pytest.mark.asyncio
    async def test_get_current_user_unauthorized(self, client: AsyncClient):
        """Without session returns 401."""
        response = await client.get("/auth/me")

        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_current_user_expired_session(self, client: AsyncClient):
        """Expired session returns 401."""
        mock_conn = MockDBConnection()
        mock_conn.set_fetchrow_return("SELECT p.id, p.name, p.email", None)

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.get(
                "/auth/me",
                cookies={"session-token": "expired-session-id"}
            )

        assert response.status_code == 401
        assert "Invalid or expired" in response.json()["detail"]


class TestSignOut:
    """Tests for POST /auth/sign-out"""

    @pytest.mark.asyncio
    async def test_sign_out(self, client: AsyncClient):
        """Successfully closes session."""
        mock_conn = MockDBConnection()

        with patch('app.database.get_db_connection', return_value=MockDBContextManager(mock_conn)):
            response = await client.post(
                "/auth/sign-out",
                cookies={"session-token": "valid-token"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Session closed"

    @pytest.mark.asyncio
    async def test_sign_out_without_session(self, client: AsyncClient):
        """Sign out without session still returns success."""
        response = await client.post("/auth/sign-out")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
