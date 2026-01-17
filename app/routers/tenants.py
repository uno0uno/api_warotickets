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
