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
async def send_magic_link(data: MagicLinkRequest, request: Request):
    """
    Send magic link to user's email.

    Only sends if user exists and is a tenant member.
    """
    # Get tenant from request state
    tenant_context = getattr(request.state, 'tenant_context', None)
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    async with get_db_connection() as conn:
        # Find user - must already exist
        user = await conn.fetchrow(
            "SELECT id, name, email FROM profile WHERE email = $1",
            data.email.lower()
        )

        if not user:
            # Don't reveal if user exists or not for security
            logger.warning(f"Login attempt for non-existent user: {data.email}")
            raise HTTPException(status_code=400, detail="No se encontro una cuenta con este correo")

        # Check if user is a member of ANY tenant (multi-tenant access)
        is_member = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 FROM tenant_members
                WHERE user_id = $1
            )
        """, user['id'])

        if not is_member:
            # Not a tenant member - check if they have purchased tickets (buyer)
            has_tickets = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM reservations r
                    WHERE r.user_id = $1 AND r.status = 'confirmed'
                )
            """, user['id'])

            if not has_tickets:
                logger.warning(f"User {data.email} has no tenant membership and no tickets")
                raise HTTPException(status_code=400, detail="No se encontro una cuenta con este correo")

            logger.info(f"Buyer login: {data.email} (no tenant, has tickets)")

        # Generate verification code (6 digits) and token
        code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(minutes=MAGIC_LINK_EXPIRY_MINUTES)

        # Store verification code in magic_tokens
        await conn.execute("""
            INSERT INTO magic_tokens (id, user_id, token, verification_code, expires_at, used, created_at)
            VALUES (gen_random_uuid(), $1, $2::text, $3::varchar, $4, false, NOW())
        """, user['id'], token, code, expires_at)

        # Build magic link URL
        magic_link_url = f"{settings.frontend_url}/auth/verify?token={token}"

        # Get tenant branding info
        tenant_info = {
            'brand_name': tenant_context.brand_name if tenant_context else 'WaRo Tickets',
            'tenant_name': tenant_context.tenant_name if tenant_context else 'WaRo Tickets',
            'admin_name': 'Saifer 101 (Anderson Arevalo)',
            'admin_email': 'anderson.arevalo@warotickets.com'
        }

        # Send email with code using template
        from app.services.email_service import send_email
        from app.templates.magic_link_template import get_magic_link_template, get_magic_link_subject

        html_body = get_magic_link_template(magic_link_url, code, tenant_info)
        subject = get_magic_link_subject(tenant_info['brand_name'])

        await send_email(
            to_email=data.email,
            subject=subject,
            html_body=html_body
        )

        logger.info(f"Magic link sent to {data.email}")

        return AuthResponse(
            success=True,
            message="Codigo enviado a tu correo"
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

        # Verify code (stored in verification_code column)
        token_row = await conn.fetchrow("""
            SELECT * FROM magic_tokens
            WHERE user_id = $1 AND verification_code = $2 AND used = false
              AND expires_at > NOW()
        """, user['id'], data.code)

        if not token_row:
            raise HTTPException(status_code=400, detail="Invalid or expired code")

        # Mark token as used
        await conn.execute(
            "UPDATE magic_tokens SET used = true, used_at = NOW() WHERE id = $1",
            token_row['id']
        )

        # Resolve tenant: use context if available, otherwise look up user's membership
        if not tenant_id:
            member = await conn.fetchrow("""
                SELECT tm.tenant_id FROM tenant_members tm
                WHERE tm.user_id = $1 LIMIT 1
            """, user['id'])
            tenant_id = member['tenant_id'] if member else None

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

        # Resolve tenant: use context if available, otherwise look up user's membership
        if not tenant_id:
            member = await conn.fetchrow("""
                SELECT tm.tenant_id FROM tenant_members tm
                WHERE tm.user_id = $1 LIMIT 1
            """, token_row['user_id'])
            tenant_id = member['tenant_id'] if member else None

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


class Tenant(BaseModel):
    """Tenant info"""
    id: str
    name: str
    slug: str


class User(BaseModel):
    """User info"""
    id: str
    email: str
    name: Optional[str] = None
    createdAt: Optional[datetime] = None


class Session(BaseModel):
    """Session info"""
    expiresAt: datetime
    createdAt: datetime
    tenantId: Optional[str] = None


class SessionResponse(BaseModel):
    """Session data response"""
    success: bool = True
    user: User
    session: Session
    currentTenant: Optional[Tenant] = None


@router.get("/session", response_model=SessionResponse)
async def get_session(request: Request, response: Response):
    """
    Get current session data including user and tenant info.
    """
    session_token = request.cookies.get("session-token")

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with get_db_connection() as conn:
        # Get session with user info
        session_result = await conn.fetchrow("""
            SELECT s.*, p.id as user_id, p.email, p.name, p.created_at as user_created_at
            FROM sessions s
            JOIN profile p ON s.user_id = p.id
            WHERE s.id = $1 AND s.expires_at > NOW() AND s.is_active = true
            LIMIT 1
        """, session_token)

        if not session_result:
            logger.warning("Invalid or expired session")
            response.delete_cookie(key="session-token", path="/")
            raise HTTPException(status_code=401, detail="Session expired")

        # Update last activity
        await conn.execute(
            "UPDATE sessions SET last_activity_at = NOW() WHERE id = $1",
            session_token
        )

        # Get tenant info if tenant_id exists
        current_tenant = None
        if session_result['tenant_id']:
            tenant_result = await conn.fetchrow(
                "SELECT id, name, slug FROM tenants WHERE id = $1",
                session_result['tenant_id']
            )
            if tenant_result:
                current_tenant = Tenant(
                    id=str(tenant_result['id']),
                    name=tenant_result['name'],
                    slug=tenant_result['slug']
                )

        # Build response
        user = User(
            id=str(session_result['user_id']),
            email=session_result['email'],
            name=session_result['name'],
            createdAt=session_result['user_created_at']
        )

        session = Session(
            expiresAt=session_result['expires_at'],
            createdAt=session_result['created_at'],
            tenantId=str(session_result['tenant_id']) if session_result['tenant_id'] else None
        )

        return SessionResponse(
            success=True,
            user=user,
            session=session,
            currentTenant=current_tenant
        )


class SwitchTenantRequest(BaseModel):
    """Request to switch tenant"""
    tenantSlug: str


class SwitchTenantResponse(BaseModel):
    """Response after switching tenant"""
    success: bool = True
    tenant: Tenant
    message: Optional[str] = None
    timestamp: Optional[str] = None


@router.post("/switch-tenant", response_model=SwitchTenantResponse)
async def switch_tenant(data: SwitchTenantRequest, request: Request, response: Response):
    """
    Switch to a different tenant for the current user.
    Creates a new session with the new tenant.
    """
    session_token = request.cookies.get("session-token")

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with get_db_connection() as conn:
        # Get current session info
        current_session = await conn.fetchrow("""
            SELECT s.user_id, s.ip_address, s.user_agent, s.login_method, s.tenant_id, t.slug as current_tenant_slug
            FROM sessions s
            LEFT JOIN tenants t ON s.tenant_id = t.id
            WHERE s.id = $1 AND s.expires_at > NOW() AND s.is_active = true
            LIMIT 1
        """, session_token)

        if not current_session:
            raise HTTPException(status_code=401, detail="Invalid session")

        user_id = current_session['user_id']
        current_tenant_slug = current_session['current_tenant_slug']

        # Check if already on the requested tenant
        if current_tenant_slug == data.tenantSlug:
            logger.info(f"Already on tenant {data.tenantSlug}, skipping switch")
            # Get tenant info and return
            tenant_info = await conn.fetchrow(
                "SELECT id, name, slug FROM tenants WHERE slug = $1",
                data.tenantSlug
            )
            if tenant_info:
                return SwitchTenantResponse(
                    success=True,
                    tenant=Tenant(
                        id=str(tenant_info['id']),
                        name=tenant_info['name'],
                        slug=tenant_info['slug']
                    ),
                    timestamp=datetime.utcnow().isoformat()
                )

        # Validate user has access to requested tenant
        tenant_access = await conn.fetchrow("""
            SELECT t.id, t.name, t.slug
            FROM tenants t
            INNER JOIN tenant_members tm ON t.id = tm.tenant_id
            WHERE t.slug = $1 AND tm.user_id = $2
            LIMIT 1
        """, data.tenantSlug, user_id)

        if not tenant_access:
            logger.warning(f"Access denied to tenant {data.tenantSlug} for user {user_id}")
            raise HTTPException(status_code=403, detail="No tienes acceso a este tenant")

        tenant_id = tenant_access['id']
        tenant_name = tenant_access['name']

        # End current session
        await conn.execute(
            "UPDATE sessions SET is_active = false, ended_at = NOW(), end_reason = 'tenant_switch' WHERE id = $1",
            session_token
        )
        logger.info(f"Ended session for tenant switch: {session_token}")

        # Create new session with new tenant
        new_session_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(days=30)

        # Get current client info
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get('user-agent')

        await conn.execute("""
            INSERT INTO sessions (
                id, user_id, tenant_id, expires_at, ip_address,
                user_agent, login_method, is_active, created_at, last_activity_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, true, NOW(), NOW())
        """, new_session_id, user_id, tenant_id, expires_at,
            client_ip or current_session['ip_address'],
            user_agent or current_session['user_agent'],
            current_session['login_method']
        )

        # Set new session cookie
        response.set_cookie(
            key="session-token",
            value=new_session_id,
            httponly=True,
            secure=not settings.is_development,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,
            path="/"
        )

        logger.info(f"Switched to tenant {data.tenantSlug} for user {user_id}")

        return SwitchTenantResponse(
            success=True,
            tenant=Tenant(
                id=str(tenant_id),
                name=tenant_name,
                slug=data.tenantSlug
            ),
            timestamp=datetime.utcnow().isoformat()
        )
