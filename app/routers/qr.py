from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from typing import Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.qr import (
    QRCodeResponse, QRValidationRequest, QRValidationResponse, CheckInStats
)
from app.services import qr_service


class ResetTicketResponse(BaseModel):
    """Respuesta al resetear ticket"""
    reservation_unit_id: int
    reservation_id: str
    old_status: str
    new_status: str
    message: str

router = APIRouter()


@router.get("/{reservation_id}/{reservation_unit_id}", response_model=QRCodeResponse)
async def get_ticket_qr(
    reservation_id: str,
    reservation_unit_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get QR code for a ticket.
    Returns base64 encoded PNG image.
    """
    qr = await qr_service.generate_qr_for_ticket(
        reservation_id, reservation_unit_id, user.user_id
    )
    return qr


@router.get("/{reservation_id}/{reservation_unit_id}/image")
async def get_ticket_qr_image(
    reservation_id: str,
    reservation_unit_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get QR code as PNG image directly.
    Useful for downloading or printing.
    """
    from app.utils.qr_generator import generate_ticket_qr
    from app.database import get_db_connection

    async with get_db_connection(use_transaction=False) as conn:
        # Check ownership (original buyer OR transferred recipient)
        ticket = await conn.fetchrow("""
            SELECT ru.id, ru.unit_id, ru.reservation_id, r.user_id,
                   ru.original_user_id, c.slug_cluster
            FROM reservation_units ru
            JOIN reservations r ON ru.reservation_id = r.id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE ru.id = $1 AND ru.reservation_id = $2
              AND (r.user_id = $3 OR ru.original_user_id = $3)
        """, reservation_unit_id, reservation_id, user.user_id)

        if not ticket:
            raise HTTPException(status_code=404, detail="Ticket not found")

    # Generate QR as bytes
    qr_bytes = generate_ticket_qr(
        reservation_unit_id=reservation_unit_id,
        unit_id=ticket['unit_id'],
        user_id=user.user_id,
        event_slug=ticket['slug_cluster'],
        as_base64=False
    )

    return Response(
        content=qr_bytes,
        media_type="image/png",
        headers={
            "Content-Disposition": f"inline; filename=ticket-{reservation_unit_id}.png",
            "X-Reservation-Id": str(ticket['reservation_id']),
            "X-Reservation-Unit-Id": str(reservation_unit_id)
        }
    )


@router.post("/{reservation_id}/validate", response_model=QRValidationResponse)
async def validate_qr(
    reservation_id: str,
    data: QRValidationRequest,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Validate a QR code at event entrance.

    This endpoint is used by event staff with scanning devices.
    If valid, marks the ticket as 'used'.

    Returns validation result with ticket and owner info.
    """
    result = await qr_service.validate_qr(reservation_id, data, user.user_id)
    return result


@router.get("/stats/{cluster_id}", response_model=CheckInStats)
async def get_check_in_stats(
    cluster_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get check-in statistics for an event.
    Shows total tickets, checked in, pending, and percentage.
    """
    stats = await qr_service.get_check_in_stats(cluster_id, user.user_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Event not found")
    return stats


@router.post("/{reservation_id}/reset/{reservation_unit_id}", response_model=ResetTicketResponse)
async def reset_ticket_status(
    reservation_id: str,
    reservation_unit_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Reset a used ticket back to confirmed status.
    Admin function for handling mistakes at entrance.
    """
    result = await qr_service.reset_ticket_status(
        reservation_id, reservation_unit_id, user.user_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="Ticket not found or not used")
    return result
