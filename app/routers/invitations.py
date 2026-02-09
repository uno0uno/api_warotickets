"""
API endpoints for team member invitations
"""
import logging
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from app.models.invitation import InvitationCreate, InvitationResponse
from app.services import invitations_service
from app.database import get_db_connection
from app.config import settings


class AcceptInvitationRequest(BaseModel):
    token: str

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("/send")
async def send_invitation(invitation: InvitationCreate, request: Request):
    """
    Send invitation to join the tenant team

    Requires authentication and tenant context
    """
    # Access contexts set by middlewares
    session_context = getattr(request.state, "session_context", None)
    tenant_context = getattr(request.state, "tenant_context", None)

    # Extract user_id and tenant_id from contexts
    user_id = session_context.user_id if session_context and session_context.is_valid else None
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        result = await invitations_service.send_invitation(
            tenant_id=tenant_id,
            email=invitation.email,
            name=invitation.name,
            role=invitation.role,
            invited_by_user_id=user_id,
            phone=invitation.phone
        )

        return {
            "success": True,
            "message": f"Invitacion enviada a {invitation.email}",
            "invitation": result
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error sending invitation: {e}")
        raise HTTPException(status_code=500, detail="Error al enviar la invitacion")


@router.get("/pending")
async def get_pending_invitations(request: Request):
    """
    Get all pending invitations for the current tenant

    Requires authentication and tenant context
    """
    # Access contexts set by middlewares
    tenant_context = getattr(request.state, "tenant_context", None)
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        invitations = await invitations_service.get_pending_invitations(tenant_id)

        return {
            "success": True,
            "invitations": invitations
        }

    except Exception as e:
        logger.error(f"Error fetching invitations: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener invitaciones")


@router.delete("/{invitation_id}")
async def cancel_invitation(invitation_id: str, request: Request):
    """
    Cancel a pending invitation

    Requires authentication and tenant context
    """
    # Access contexts set by middlewares
    tenant_context = getattr(request.state, "tenant_context", None)
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        cancelled = await invitations_service.cancel_invitation(invitation_id, tenant_id)

        if not cancelled:
            raise HTTPException(status_code=404, detail="Invitacion no encontrada")

        return {
            "success": True,
            "message": "Invitacion cancelada"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling invitation: {e}")
        raise HTTPException(status_code=500, detail="Error al cancelar invitacion")


@router.post("/{invitation_id}/resend")
async def resend_invitation(invitation_id: str, request: Request):
    """
    Resend an invitation email

    Requires authentication and tenant context
    """
    # Access contexts set by middlewares
    tenant_context = getattr(request.state, "tenant_context", None)
    tenant_id = tenant_context.tenant_id if tenant_context and tenant_context.is_valid else None

    if not tenant_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        result = await invitations_service.resend_invitation(invitation_id, tenant_id)

        return {
            "success": True,
            "message": "Invitacion reenviada",
            "invitation": result
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error resending invitation: {e}")
        raise HTTPException(status_code=500, detail="Error al reenviar invitacion")


@router.post("/accept")
async def accept_invitation(data: AcceptInvitationRequest, request: Request, response: Response):
    """
    Accept a team invitation via token.
    This is a PUBLIC endpoint - no auth required (user may not have an account yet).
    Creates a session so the user is automatically logged in after accepting.
    """
    try:
        result = await invitations_service.accept_invitation(token=data.token)

        # Create session for the user (auto-login after accepting invitation)
        user_id = result['user']['id']
        tenant_id = result['tenant']['id']

        session_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(days=30)

        async with get_db_connection() as conn:
            await conn.execute("""
                INSERT INTO sessions (id, user_id, tenant_id, expires_at, created_at, is_active, login_method)
                VALUES ($1, $2, $3, $4, NOW(), true, 'invitation')
            """, session_id, user_id, tenant_id, expires_at)

        # Set session cookie
        response.set_cookie(
            key="session-token",
            value=session_id,
            httponly=True,
            secure=not settings.is_development,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,  # 30 days
            path="/"
        )

        logger.info(f"Session created for invited user: {result['user']['email']} (tenant: {tenant_id})")

        return {
            "success": True,
            "message": "Invitación aceptada exitosamente",
            **result
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error accepting invitation: {e}")
        raise HTTPException(status_code=500, detail="Error al aceptar la invitación")
