import logging
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from app.database import get_db_connection
from app.config import settings

logger = logging.getLogger(__name__)

class SessionContext:
    """Session context object"""
    def __init__(self, session_data: Optional[Dict[str, Any]] = None):
        if session_data:
            self.user_id = session_data['user_id']
            self.tenant_id = session_data['tenant_id']
            self.email = session_data['email']
            self.name = session_data['name']
            self.expires_at = session_data['expires_at']
            self.is_active = session_data['is_active']
            self.is_valid = True
        else:
            self.user_id = None
            self.tenant_id = None
            self.email = None
            self.name = None
            self.expires_at = None
            self.is_active = False
            self.is_valid = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'user_id': self.user_id,
            'tenant_id': self.tenant_id,
            'email': self.email,
            'name': self.name,
            'expires_at': self.expires_at,
            'is_active': self.is_active,
            'is_valid': self.is_valid
        }

class TenantContext:
    """Tenant context object"""
    def __init__(self, tenant_data: Optional[Dict[str, Any]] = None):
        if tenant_data:
            self.tenant_id = tenant_data['tenant_id']
            self.tenant_name = tenant_data['tenant_name']
            self.tenant_slug = tenant_data['tenant_slug']
            self.tenant_email = tenant_data['tenant_email']
            self.site = tenant_data['site']
            self.brand_name = tenant_data['brand_name']
            self.is_active = tenant_data['is_active']
            self.is_valid = True
        else:
            self.tenant_id = None
            self.tenant_name = None
            self.tenant_slug = None
            self.tenant_email = None
            self.site = None
            self.brand_name = None
            self.is_active = False
            self.is_valid = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'tenant_id': self.tenant_id,
            'tenant_name': self.tenant_name,
            'tenant_slug': self.tenant_slug,
            'tenant_email': self.tenant_email,
            'site': self.site,
            'brand_name': self.brand_name,
            'is_active': self.is_active,
            'is_valid': self.is_valid
        }

async def tenant_detection_middleware(request: Request, call_next):
    """
    Middleware to detect tenant from user session.
    Validates that user is a tenant_member (not based on tenant_sites).
    Sets request.state.tenant_context for use in endpoints.
    """
    try:
        # Skip tenant detection for health checks, docs, webhooks, public endpoints and root endpoint
        skip_paths = ['/health', '/docs', '/redoc', '/openapi.json', '/']
        skip_prefixes = ['/payments/webhooks', '/public', '/cart']

        if request.url.path in skip_paths or any(request.url.path.startswith(p) for p in skip_prefixes):
            request.state.tenant_context = TenantContext()
            return await call_next(request)

        # Get tenant from user session - validate by tenant_member, not tenant_sites
        session_token = request.cookies.get("session-token")
        logger.info(f"tenant_detection_middleware: path={request.url.path}, session_token={session_token[:20] if session_token else 'None'}...")
        if session_token:
            try:
                async with get_db_connection(use_transaction=False) as conn:
                    # Get session with tenant and validate membership
                    query = """
                        SELECT s.tenant_id, s.user_id,
                               t.name as tenant_name, t.slug as tenant_slug, t.email as tenant_email
                        FROM sessions s
                        JOIN tenants t ON s.tenant_id = t.id
                        JOIN tenant_members tm ON tm.tenant_id = t.id AND tm.user_id = s.user_id
                        WHERE s.id = $1 AND s.expires_at > NOW() AND s.is_active = true
                        LIMIT 1
                    """
                    result = await conn.fetchrow(query, session_token)
                    if result:
                        logger.info(f"tenant_detection_middleware: found session for tenant_id={result['tenant_id']}, tenant_name={result['tenant_name']}")
                        # Try to get brand_name from tenant_sites if it exists
                        site_result = await conn.fetchrow(
                            "SELECT site, brand_name FROM tenant_sites WHERE tenant_id = $1 AND is_active = true LIMIT 1",
                            result['tenant_id']
                        )

                        tenant_context = TenantContext({
                            'tenant_id': result['tenant_id'],
                            'tenant_name': result['tenant_name'],
                            'tenant_slug': result['tenant_slug'],
                            'tenant_email': result['tenant_email'],
                            'site': site_result['site'] if site_result else None,
                            'brand_name': site_result['brand_name'] if site_result else result['tenant_name'],
                            'is_active': True
                        })
                        request.state.tenant_context = tenant_context
                        return await call_next(request)
            except Exception as e:
                logger.warning(f"Failed to get tenant from session: {e}")

        # No valid session - let the endpoint handle authentication
        # (session_validation_middleware will handle auth errors)
        request.state.tenant_context = TenantContext()
        return await call_next(request)

    except Exception as e:
        logger.error(f"Tenant detection middleware error: {e}", exc_info=True)
        request.state.tenant_context = TenantContext()
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error during tenant detection"}
        )

def get_tenant_context(request: Request) -> TenantContext:
    """Helper function to get tenant context from request"""
    return getattr(request.state, 'tenant_context', TenantContext())

def require_valid_tenant(request: Request) -> TenantContext:
    """Helper function that raises error if no valid tenant context"""
    tenant_context = get_tenant_context(request)
    if not tenant_context.is_valid:
        from app.core.exceptions import ValidationError
        raise ValidationError("Valid tenant context required")
    return tenant_context

async def session_validation_middleware(request: Request, call_next):
    """
    Middleware to validate session for protected endpoints
    Sets request.state.session_context for use in endpoints
    """
    try:
        path = request.url.path
        public_endpoints = [
            '/docs', '/openapi.json', '/health',
            '/auth/sign-in-magic-link', '/auth/verify-code', '/auth/verify',
            '/transfers/accept-public'
        ]

        public_prefixes = ['/public', '/webhooks']

        if path == '/' or any(path.startswith(endpoint) for endpoint in public_endpoints) or any(path.startswith(prefix) for prefix in public_prefixes):
            request.state.session_context = SessionContext()
            return await call_next(request)

        from app.core.security import get_session_from_request
        try:
            session_data = await get_session_from_request(request)
            if session_data:
                request.state.session_context = SessionContext(session_data)
            else:
                request.state.session_context = SessionContext()
        except Exception as e:
            logger.warning(f"Session validation error for path {path}: {e}")
            request.state.session_context = SessionContext()

        return await call_next(request)

    except Exception as e:
        logger.error(f"Session validation error: {e}")
        request.state.session_context = SessionContext()
        return await call_next(request)

def get_session_context(request: Request) -> SessionContext:
    """Helper function to get session context from request"""
    return getattr(request.state, 'session_context', SessionContext())

def require_valid_session(request: Request) -> SessionContext:
    """Helper function that raises error if no valid session context"""
    session_context = get_session_context(request)
    if not session_context.is_valid:
        from app.core.exceptions import AuthenticationError
        raise AuthenticationError("Valid session required")
    return session_context

async def request_logging_middleware(request: Request, call_next):
    """Simple request logging middleware"""
    start_time = time.time()

    method = request.method
    path = request.url.path

    tenant_name = getattr(getattr(request.state, 'tenant_context', None), 'tenant_name', 'unknown')
    session_context = getattr(request.state, 'session_context', None)
    user_id = getattr(session_context, 'user_id', 'anonymous') if session_context else 'anonymous'

    response = await call_next(request)

    duration = round((time.time() - start_time) * 1000, 2)

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"{timestamp} | {method} {path} | {duration}ms")

    return response
