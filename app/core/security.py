import jwt
import logging
from datetime import datetime
from fastapi import Request, HTTPException, Response
from app.config import settings
from typing import Optional

logger = logging.getLogger(__name__)

async def get_session_token(request: Request) -> str:
    """Extract valid session-token from cookies"""
    from app.database import get_db_connection

    cookie_header = request.headers.get("cookie", "")
    session_tokens = []

    if cookie_header:
        for cookie_pair in cookie_header.split(";"):
            cookie_pair = cookie_pair.strip()
            if cookie_pair.startswith("session-token="):
                token = cookie_pair.split("=", 1)[1]
                session_tokens.append(token)

    if not session_tokens:
        session_token = request.cookies.get("session-token")
        if not session_token:
            raise HTTPException(status_code=401, detail="No session found")
        return session_token

    valid_token = None
    invalid_tokens = []

    async with get_db_connection() as conn:
        for token in session_tokens:
            try:
                session_query = """
                    SELECT id FROM sessions
                    WHERE id = $1 AND expires_at > NOW() AND is_active = true
                    LIMIT 1
                """
                session_result = await conn.fetchrow(session_query, token)

                if session_result:
                    valid_token = token
                    break
                else:
                    invalid_tokens.append(token)
            except Exception:
                invalid_tokens.append(token)

        if invalid_tokens:
            for invalid_token in invalid_tokens:
                try:
                    await conn.execute(
                        "UPDATE sessions SET is_active = false WHERE id = $1",
                        invalid_token
                    )
                except Exception:
                    pass

    if not valid_token:
        raise HTTPException(status_code=401, detail="No valid session found")

    return valid_token

async def set_session_cookie(response: Response, session_token: str, tenant_site: str = None):
    """Set session cookie with correct domain for the tenant"""
    cookie_domain = None
    if not settings.is_development:
        if tenant_site:
            cookie_domain = f".{tenant_site}"
        else:
            try:
                from app.database import get_db_connection
                async with get_db_connection(use_transaction=False) as conn:
                    site_query = """
                        SELECT ts.site
                        FROM sessions s
                        JOIN tenant_sites ts ON s.tenant_id = ts.tenant_id
                        WHERE s.id = $1 AND s.is_active = true AND ts.is_active = true
                        LIMIT 1
                    """
                    site_result = await conn.fetchrow(site_query, session_token)

                    if site_result and site_result['site']:
                        cookie_domain = f".{site_result['site']}"
            except Exception as e:
                logger.warning(f"Error getting site from DB: {e}")

    response.delete_cookie("session-token", domain=cookie_domain)
    if cookie_domain:
        response.delete_cookie("session-token")

    response.set_cookie(
        key="session-token",
        value=session_token,
        httponly=True,
        secure=not settings.is_development,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,  # 7 days
        domain=cookie_domain,
        path="/"
    )

async def clear_session_cookie(response: Response, session_token: str = None):
    """Clear session cookie with dynamic domain from database"""
    cookie_domain = None

    if session_token and not settings.is_development:
        try:
            from app.database import get_db_connection
            async with get_db_connection(use_transaction=False) as conn:
                site_query = """
                    SELECT ts.site
                    FROM sessions s
                    JOIN tenant_sites ts ON s.tenant_id = ts.tenant_id
                    WHERE s.id = $1 AND s.is_active = true AND ts.is_active = true
                    LIMIT 1
                """
                site_result = await conn.fetchrow(site_query, session_token)

                if site_result and site_result['site']:
                    cookie_domain = f".{site_result['site']}"
        except Exception:
            pass

    response.delete_cookie("session-token", domain=cookie_domain, path="/")
    if cookie_domain:
        response.delete_cookie("session-token", path="/")

def create_session_token(user_id: str, email: str) -> str:
    """Create a JWT session token"""
    from datetime import timedelta
    payload = {
        "user_id": user_id,
        "email": email,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_session_token(token: str) -> Optional[dict]:
    """Verify a JWT session token and return payload"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return {
            "user_id": payload.get("user_id"),
            "email": payload.get("email")
        }
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def validate_jwt_token(token: str) -> dict:
    """Validate JWT token"""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_client_ip(request: Request) -> Optional[str]:
    """Get client IP address from request headers"""
    forwarded_for = request.headers.get('x-forwarded-for')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.client.host if request.client else None

def detect_tenant_from_headers(request: Request) -> dict:
    """Extract tenant detection headers"""
    return {
        'host': request.headers.get('host', ''),
        'origin': request.headers.get('origin', ''),
        'referer': request.headers.get('referer', ''),
        'forwarded_host': request.headers.get('x-forwarded-host', ''),
        'original_host': request.headers.get('x-original-host', ''),
    }

async def get_session_from_request(request: Request) -> Optional[dict]:
    """
    Get session data from request using session token.
    Returns session data with user_id, tenant_id, etc.
    """
    from app.database import get_db_connection

    try:
        try:
            session_token = await get_session_token(request)
        except HTTPException:
            return None

        if not session_token:
            return None

        async with get_db_connection() as conn:
            session_check = await conn.fetchrow("""
                SELECT id, expires_at, is_active, ended_at
                FROM sessions
                WHERE id = $1
            """, session_token)

            if session_check:
                is_expired = session_check['expires_at'] < datetime.now(session_check['expires_at'].tzinfo)
                is_inactive = not session_check['is_active']

                if is_expired or is_inactive:
                    if session_check['ended_at'] is None:
                        end_reason = 'expired' if is_expired else 'invalidated'
                        await conn.execute("""
                            UPDATE sessions
                            SET is_active = false,
                                ended_at = NOW(),
                                end_reason = $2
                            WHERE id = $1 AND ended_at IS NULL
                        """, session_token, end_reason)
                    return None

            session_query = """
                SELECT s.user_id, s.tenant_id, s.expires_at, s.is_active,
                       p.email, p.name
                FROM sessions s
                JOIN profile p ON s.user_id = p.id
                WHERE s.id = $1
                  AND s.expires_at > NOW()
                  AND s.is_active = true
                LIMIT 1
            """
            session_result = await conn.fetchrow(session_query, session_token)

            if not session_result:
                return None

            await conn.execute("""
                UPDATE sessions
                SET last_activity_at = NOW()
                WHERE id = $1
            """, session_token)

            return {
                'user_id': session_result['user_id'],
                'tenant_id': session_result['tenant_id'],
                'email': session_result['email'],
                'name': session_result['name'],
                'expires_at': session_result['expires_at'],
                'is_active': session_result['is_active']
            }

    except Exception as e:
        logger.error(f"Error in get_session_from_request: {e}", exc_info=True)
        return None

async def get_current_user_id(request: Request) -> Optional[str]:
    """Get current user ID from session"""
    session = await get_session_from_request(request)
    return session.get('user_id') if session else None
