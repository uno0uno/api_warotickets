"""
Promoter Dependencies
Provides RBAC (Role-Based Access Control) for the promoter commission system.
"""

from fastapi import HTTPException, Request
from app.database import get_db_connection
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Roles permitidos para acceder a módulo de promotores
ALLOWED_PROMOTER_ROLES = ['superuser', 'admin', 'promotor']


async def require_promoter_access(request: Request) -> dict:
    """
    Verifica que el usuario tenga permiso para acceder al módulo de promotores.
    Roles permitidos: superuser, admin, promotor

    Returns:
        dict: {
            'tenant_member_id': str,
            'tenant_id': str,
            'user_id': str,
            'role': str
        }

    Raises:
        HTTPException: 401 if not authenticated, 403 if no valid role
    """
    # Access contexts set by middlewares
    session_context = getattr(request.state, "session_context", None)
    tenant_context = getattr(request.state, "tenant_context", None)

    # Extract user_id and tenant_id from contexts
    user_id = session_context.user_id if session_context and session_context.is_valid else None
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    async with get_db_connection(use_transaction=False) as conn:
        # Buscar tenant_member
        member = await conn.fetchrow("""
            SELECT id, role FROM tenant_members
            WHERE user_id = $1 AND tenant_id = $2
        """, user_id, tenant_id)

        if not member:
            raise HTTPException(
                status_code=403,
                detail="Not a member of this tenant"
            )

        # Intentar obtener rol de tenant_member_roles (nuevo sistema)
        member_role = await conn.fetchrow("""
            SELECT * FROM tenant_member_roles
            WHERE tenant_member_id = $1
              AND is_active = true
              AND site_role_name = ANY($2::text[])
        """, member['id'], ALLOWED_PROMOTER_ROLES)

        # Si no existe en tenant_member_roles, usar tenant_members.role (legacy)
        if member_role:
            role = member_role['site_role_name']
            logger.info(
                f"Promoter access granted for user {user_id} "
                f"(role from tenant_member_roles: {role})"
            )
        elif member['role'] and member['role'] in ALLOWED_PROMOTER_ROLES:
            role = member['role']
            logger.info(
                f"Promoter access granted for user {user_id} "
                f"(role from tenant_members.role: {role})"
            )
        else:
            logger.warning(
                f"Access denied for user {user_id} to promoter module. "
                f"Required roles: {ALLOWED_PROMOTER_ROLES}"
            )
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required roles: {', '.join(ALLOWED_PROMOTER_ROLES)}"
            )

        return {
            'tenant_member_id': member['id'],
            'tenant_id': tenant_id,
            'user_id': user_id,
            'role': role
        }


async def get_promoter_access_optional(request: Request) -> Optional[dict]:
    """
    Versión opcional que retorna None si no tiene acceso (no lanza error).
    Útil para endpoints que modifican comportamiento según rol.

    Returns:
        dict | None: Same structure as require_promoter_access, or None if no access
    """
    try:
        return await require_promoter_access(request)
    except HTTPException:
        return None


async def require_admin_role(request: Request) -> dict:
    """
    Verifica que el usuario tenga rol de admin o superuser.
    Usado para endpoints de administración (asignar roles, aprobar comisiones, etc.)

    Returns:
        dict: Same structure as require_promoter_access

    Raises:
        HTTPException: 403 if not admin/superuser
    """
    access = await require_promoter_access(request)

    if access['role'] not in ['admin', 'superuser']:
        logger.warning(
            f"Admin access denied for user {access['user_id']} "
            f"(current role: {access['role']})"
        )
        raise HTTPException(
            status_code=403,
            detail="Admin or superuser role required"
        )

    return access
