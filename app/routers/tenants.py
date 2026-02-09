from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.database import get_db_connection
from datetime import datetime
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


class Tenant(BaseModel):
    id: str
    name: str
    slug: str


class UserTenantsResponse(BaseModel):
    success: bool = True
    data: List[Tenant]
    message: Optional[str] = None
    timestamp: Optional[str] = None


@router.get("/user-tenants", response_model=UserTenantsResponse)
async def get_user_tenants(request: Request):
    """
    Get tenants associated with the current user
    Requires valid session cookie
    """
    session_token = request.cookies.get("session-token")

    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with get_db_connection() as conn:
        # Validate session and get user_id
        session = await conn.fetchrow("""
            SELECT user_id FROM sessions
            WHERE id = $1 AND is_active = true AND expires_at > NOW()
        """, session_token)

        if not session:
            raise HTTPException(status_code=401, detail="Invalid or expired session")

        user_id = session['user_id']

        # Get tenants for the user
        tenant_rows = await conn.fetch("""
            SELECT DISTINCT
                t.id,
                t.name,
                t.slug
            FROM tenants t
            INNER JOIN tenant_members tm ON t.id = tm.tenant_id
            WHERE tm.user_id = $1
            ORDER BY t.name
        """, user_id)

        tenants = [
            Tenant(
                id=str(row['id']),
                name=row['name'],
                slug=row['slug']
            )
            for row in tenant_rows
        ]

        return UserTenantsResponse(
            success=True,
            data=tenants,
            timestamp=datetime.utcnow().isoformat()
        )


@router.get("/members")
async def get_tenant_members(request: Request):
    """
    Get all members of the current tenant
    Includes user profile information and roles
    """
    # Access contexts set by middlewares
    session_context = getattr(request.state, "session_context", None)
    tenant_context = getattr(request.state, "tenant_context", None)

    # Extract user_id and tenant_id from contexts
    user_id = session_context.user_id if session_context and session_context.is_valid else None
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    async with get_db_connection(use_transaction=False) as conn:
        # Get tenant members with their profile and role information
        # Filter out customers - only return actual team members
        members = await conn.fetch("""
            SELECT
                tm.id,
                tm.user_id,
                COALESCE(tmr.created_at, p.created_at) as created_at,
                p.email,
                COALESCE(NULLIF(p.name, ''), p.user_name, SPLIT_PART(p.email, '@', 1)) as full_name,
                COALESCE(tmr.site_role_name, tm.role) as role,
                COALESCE(tmr.is_active, true) as is_active
            FROM tenant_members tm
            JOIN profile p ON p.id = tm.user_id
            LEFT JOIN tenant_member_roles tmr ON tmr.tenant_member_id = tm.id
                AND tmr.is_active = true
            WHERE tm.tenant_id = $1
                AND COALESCE(tmr.site_role_name, tm.role) != 'customer'
                AND COALESCE(tmr.site_role_name, tm.role) IS NOT NULL
            ORDER BY COALESCE(tmr.created_at, p.created_at) DESC
        """, tenant_id)

        return {
            "members": [dict(row) for row in members]
        }


@router.delete("/members/{member_id}")
async def delete_tenant_member(member_id: str, request: Request):
    """
    Remove a member from the current tenant.
    Only admins/superusers can remove members. Cannot remove yourself.
    """
    session_context = getattr(request.state, "session_context", None)
    tenant_context = getattr(request.state, "tenant_context", None)

    user_id = session_context.user_id if session_context and session_context.is_valid else None
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    async with get_db_connection() as conn:
        # Verify current user is admin/superuser
        current_role = await conn.fetchval("""
            SELECT COALESCE(tmr.site_role_name, tm.role)
            FROM tenant_members tm
            LEFT JOIN tenant_member_roles tmr ON tmr.tenant_member_id = tm.id AND tmr.is_active = true
            WHERE tm.user_id = $1 AND tm.tenant_id = $2
        """, user_id, tenant_id)

        if current_role not in ('admin', 'superuser'):
            raise HTTPException(status_code=403, detail="Solo administradores pueden eliminar miembros")

        # Get the member to delete
        member = await conn.fetchrow("""
            SELECT id, user_id FROM tenant_members
            WHERE id = $1 AND tenant_id = $2
        """, member_id, tenant_id)

        if not member:
            raise HTTPException(status_code=404, detail="Miembro no encontrado")

        # Cannot remove yourself
        if str(member['user_id']) == str(user_id):
            raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo del equipo")

        # Delete tenant_member_roles first (if any)
        await conn.execute("""
            DELETE FROM tenant_member_roles WHERE tenant_member_id = $1
        """, member_id)

        # Delete tenant_member
        await conn.execute("""
            DELETE FROM tenant_members WHERE id = $1 AND tenant_id = $2
        """, member_id, tenant_id)

        logger.info(f"Member {member_id} removed from tenant {tenant_id} by user {user_id}")

        return {
            "success": True,
            "message": "Miembro eliminado del equipo"
        }
