from fastapi import Depends, Request, HTTPException
from app.core.middleware import SessionContext, TenantContext, get_session_context, get_tenant_context
from app.core.exceptions import AuthenticationError, AuthorizationError
from typing import Optional
import logging
import os

logger = logging.getLogger(__name__)


def get_current_session(request: Request) -> SessionContext:
    """
    Dependency to get current session context.
    Returns SessionContext (may be invalid if not authenticated).
    """
    return get_session_context(request)


def require_authenticated_session(request: Request) -> SessionContext:
    """
    Dependency that requires a valid authenticated session.
    Raises AuthenticationError if not authenticated.
    """
    session = get_session_context(request)
    if not session.is_valid:
        raise AuthenticationError("Authentication required")
    return session


def get_current_tenant(request: Request) -> TenantContext:
    """
    Dependency to get current tenant context.
    Returns TenantContext (may be invalid if not detected).
    """
    return get_tenant_context(request)


def require_valid_tenant(request: Request) -> TenantContext:
    """
    Dependency that requires a valid tenant context.
    Raises error if tenant not detected.
    """
    tenant = get_tenant_context(request)
    if not tenant.is_valid:
        raise HTTPException(status_code=400, detail="Valid tenant required")
    return tenant


async def get_current_user_id(request: Request) -> Optional[str]:
    """
    Dependency to get current user ID from session.
    Returns None if not authenticated.
    """
    session = get_session_context(request)
    return str(session.user_id) if session.is_valid else None


async def require_user_id(request: Request) -> str:
    """
    Dependency that requires an authenticated user.
    Raises AuthenticationError if not authenticated.
    """
    session = get_session_context(request)
    if not session.is_valid or not session.user_id:
        raise AuthenticationError("Authentication required")
    return str(session.user_id)


async def get_tenant_id(request: Request) -> Optional[str]:
    """
    Dependency to get current tenant ID.
    Returns None if tenant not detected.
    """
    tenant = get_tenant_context(request)
    return str(tenant.tenant_id) if tenant.is_valid else None


async def require_tenant_id(request: Request) -> str:
    """
    Dependency that requires a valid tenant.
    Raises error if tenant not detected.
    """
    tenant = get_tenant_context(request)
    if not tenant.is_valid or not tenant.tenant_id:
        raise HTTPException(status_code=400, detail="Valid tenant required")
    return str(tenant.tenant_id)


class AuthenticatedUser:
    """
    Dependency class that provides both user and tenant context.
    Use this for endpoints that require authentication.
    """
    def __init__(self, request: Request):
        self.session = get_session_context(request)
        self.tenant = get_tenant_context(request)

        if not self.session.is_valid:
            raise AuthenticationError("Authentication required")

        if not self.tenant.is_valid:
            raise HTTPException(status_code=400, detail="Valid tenant required")

    @property
    def user_id(self) -> str:
        return str(self.session.user_id)

    @property
    def tenant_id(self) -> str:
        return str(self.session.tenant_id)

    @property
    def email(self) -> str:
        return self.session.email

    @property
    def name(self) -> str:
        return self.session.name


def get_authenticated_user(request: Request) -> AuthenticatedUser:
    """Dependency to get authenticated user with tenant context"""
    return AuthenticatedUser(request)


class AuthenticatedBuyer:
    """
    Dependency class that provides user context WITHOUT requiring tenant.
    Use this for buyer endpoints (e.g. my-tickets) where tenant is not needed.
    """
    def __init__(self, request: Request):
        self.session = get_session_context(request)

        if not self.session.is_valid:
            raise AuthenticationError("Authentication required")

    @property
    def user_id(self) -> str:
        return str(self.session.user_id)

    @property
    def email(self) -> str:
        return self.session.email

    @property
    def name(self) -> str:
        return self.session.name


def get_authenticated_buyer(request: Request) -> AuthenticatedBuyer:
    """Dependency to get authenticated user WITHOUT tenant context (for buyers)"""
    return AuthenticatedBuyer(request)


def get_environment() -> str:
    """
    Dependency to get current environment (dev/prod).
    Reads from settings.app_env (loaded from .env file).
    Returns 'prod' by default if not set.
    """
    from app.config import settings
    env = settings.app_env
    logger.info(f"get_environment() called - APP_ENV from settings: '{env}'")
    # Normalize to only allow 'dev' or 'prod'
    return "dev" if env == "dev" else "prod"
