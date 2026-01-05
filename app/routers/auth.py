from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from app.database import get_db_connection
from app.config import settings
import secrets
import logging
import uuid
from datetime import datetime, timedelta

router = APIRouter()
logger = logging.getLogger(__name__)

# Magic link tokens expire after 15 minutes
MAGIC_LINK_EXPIRY_MINUTES = 15


class MagicLinkRequest(BaseModel):
    """Request to send magic link"""
    email: EmailStr


class VerifyCodeRequest(BaseModel):
    """Request to verify code"""
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class VerifyTokenRequest(BaseModel):
    """Request to verify magic link token"""
    token: str


class AuthResponse(BaseModel):
    """Authentication response"""
    success: bool
    message: str
    user_id: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None


@router.post("/sign-in-magic-link", response_model=AuthResponse)
async def send_magic_link(data: MagicLinkRequest):
    """
    Send magic link to user's email.

    Creates or finds user by email and sends a login link.
    """
    async with get_db_connection() as conn:
        # Find or create user
        user = await conn.fetchrow(
            "SELECT id, name, email FROM profile WHERE email = $1",
            data.email.lower()
        )

        if not user:
            # Create new user
            user = await conn.fetchrow("""
                INSERT INTO profile (email, created_at, updated_at)
                VALUES ($1, NOW(), NOW())
                RETURNING id, name, email
            """, data.email.lower())

        # Generate verification code (6 digits)
        code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
        expires_at = datetime.now() + timedelta(minutes=MAGIC_LINK_EXPIRY_MINUTES)

        # Store verification code in magic_tokens
        await conn.execute("""
            INSERT INTO magic_tokens (id, user_id, token, verification_code, expires_at, used, created_at)
            VALUES (gen_random_uuid(), $1, $2::text, $3::varchar, $4, false, NOW())
        """, user['id'], code, code, expires_at)

        # Send email with code
        from app.services.email_service import send_email

        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>Your Access Code</h2>
            <p>Use this code to sign in:</p>
            <div style="background: #f0f0f0; padding: 20px; text-align: center; font-size: 32px; letter-spacing: 8px; font-weight: bold;">
                {code}
            </div>
            <p style="color: #666; margin-top: 20px;">
                This code expires in {MAGIC_LINK_EXPIRY_MINUTES} minutes.
            </p>
        </div>
        """

        await send_email(
            to_email=data.email,
            subject=f"Your Access Code: {code}",
            html_body=html_body
        )

        logger.info(f"Magic link sent to {data.email}")

        return AuthResponse(
            success=True,
            message="Code sent to your email"
        )


@router.post("/verify-code", response_model=AuthResponse)
async def verify_code(data: VerifyCodeRequest, request: Request, response: Response):
    """
    Verify the code sent via email.

    If valid, creates a session and sets the session cookie.
    """
    # Get tenant from request state (set by middleware)
    tenant_context = getattr(request.state, 'tenant_context', None)
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    async with get_db_connection() as conn:
        # Find user
        user = await conn.fetchrow(
            "SELECT id, name, email FROM profile WHERE email = $1",
            data.email.lower()
        )

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Verify code
        token_row = await conn.fetchrow("""
            SELECT * FROM magic_tokens
            WHERE user_id = $1 AND token = $2 AND used = false
              AND expires_at > NOW()
        """, user['id'], data.code)

        if not token_row:
            raise HTTPException(status_code=400, detail="Invalid or expired code")

        # Mark token as used
        await conn.execute(
            "UPDATE magic_tokens SET used = true, used_at = NOW() WHERE id = $1",
            token_row['id']
        )

        # Create session - use UUID as session ID
        session_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(days=30)

        await conn.execute("""
            INSERT INTO sessions (id, user_id, tenant_id, expires_at, created_at, is_active, login_method)
            VALUES ($1, $2, $3, $4, NOW(), true, 'magic_link')
        """, session_id, user['id'], tenant_id, expires_at)

        session_token = session_id

        # Set cookie
        response.set_cookie(
            key="session-token",
            value=session_token,
            httponly=True,
            secure=not settings.is_development,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,  # 30 days
            path="/"
        )

        logger.info(f"User logged in: {user['email']} (tenant: {tenant_id})")

        return AuthResponse(
            success=True,
            message="Session started",
            user_id=str(user['id']),
            email=user['email'],
            name=user['name']
        )


@router.post("/verify", response_model=AuthResponse)
async def verify_magic_link(data: VerifyTokenRequest, request: Request, response: Response):
    """
    Verify magic link token (alternative to code verification).

    Token is a longer secure string sent in the email link.
    """
    # Get tenant from request state (set by middleware)
    tenant_context = getattr(request.state, 'tenant_context', None)
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    async with get_db_connection() as conn:
        # Find token
        token_row = await conn.fetchrow("""
            SELECT mt.*, p.id as user_id, p.name, p.email
            FROM magic_tokens mt
            JOIN profile p ON mt.user_id = p.id
            WHERE mt.token = $1 AND mt.used = false
              AND mt.expires_at > NOW()
        """, data.token)

        if not token_row:
            raise HTTPException(status_code=400, detail="Invalid or expired token")

        # Mark token as used
        await conn.execute(
            "UPDATE magic_tokens SET used = true, used_at = NOW() WHERE id = $1",
            token_row['id']
        )

        # Create session - use UUID as session ID
        session_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(days=30)

        await conn.execute("""
            INSERT INTO sessions (id, user_id, tenant_id, expires_at, created_at, is_active, login_method)
            VALUES ($1, $2, $3, $4, NOW(), true, 'magic_link')
        """, session_id, token_row['user_id'], tenant_id, expires_at)

        session_token = session_id

        # Set cookie
        response.set_cookie(
            key="session-token",
            value=session_token,
            httponly=True,
            secure=not settings.is_development,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,
            path="/"
        )

        logger.info(f"User logged in via token: {token_row['email']} (tenant: {tenant_id})")

        return AuthResponse(
            success=True,
            message="Session started",
            user_id=str(token_row['user_id']),
            email=token_row['email'],
            name=token_row['name']
        )


@router.get("/me", response_model=AuthResponse)
async def get_current_user(request: Request):
    """
    Get current authenticated user info.
    """
    session_token = request.cookies.get("session-token")

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with get_db_connection(use_transaction=False) as conn:
        # Validate session and get user in one query
        result = await conn.fetchrow("""
            SELECT p.id, p.name, p.email, s.expires_at
            FROM sessions s
            JOIN profile p ON s.user_id = p.id
            WHERE s.id = $1 AND s.is_active = true AND s.expires_at > NOW()
        """, session_token)

        if not result:
            raise HTTPException(status_code=401, detail="Invalid or expired session")

        return AuthResponse(
            success=True,
            message="Authenticated",
            user_id=str(result['id']),
            email=result['email'],
            name=result['name']
        )


@router.post("/sign-out")
async def sign_out(request: Request, response: Response):
    """
    Sign out and clear session.
    """
    session_token = request.cookies.get("session-token")

    if session_token:
        async with get_db_connection() as conn:
            await conn.execute(
                "UPDATE sessions SET is_active = false, ended_at = NOW(), end_reason = 'logout' WHERE id = $1",
                session_token
            )

    response.delete_cookie(key="session-token", path="/")

    return {"success": True, "message": "Session closed"}
