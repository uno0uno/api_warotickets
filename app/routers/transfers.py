from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.transfer import (
    Transfer, TransferSummary, TransferLogEntry, PendingTransfer,
    TransferInitiateRequest, TransferAcceptRequest, TransferResult
)
from app.services import transfer_service


class EventTransfer(BaseModel):
    id: int
    transfer_date: Optional[str] = None
    status: str
    from_name: Optional[str] = None
    from_email: Optional[str] = None
    to_name: Optional[str] = None
    to_email: Optional[str] = None
    area_name: Optional[str] = None
    unit_display_name: Optional[str] = None


router = APIRouter()


@router.get("/event/{cluster_id}", response_model=List[EventTransfer])
async def get_event_transfers(
    cluster_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get all transfers for an event (admin view).
    Requires organizer ownership of the event.
    """
    transfers = await transfer_service.get_event_transfers(
        cluster_id, user.user_id, limit=limit, offset=offset
    )
    if transfers is None:
        raise HTTPException(status_code=403, detail="Not authorized for this event")
    return transfers


@router.post("/initiate", response_model=Transfer, status_code=201)
async def initiate_transfer(
    data: TransferInitiateRequest,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Initiate a ticket transfer to another user.

    The recipient will receive an email with a link to accept the transfer.
    The transfer expires after 48 hours.
    """
    transfer = await transfer_service.initiate_transfer(user.user_id, data)
    return transfer


@router.post("/accept", response_model=TransferResult)
async def accept_transfer(
    data: TransferAcceptRequest,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Accept a pending transfer.

    The transfer token is received via email.
    After accepting, a new QR code is generated for the new owner.
    """
    result = await transfer_service.accept_transfer(
        user.user_id,
        user.email,
        data.transfer_token
    )
    return result


@router.post("/accept-public", status_code=200)
async def accept_transfer_public(data: TransferAcceptRequest):
    """
    Accept a transfer using only the token (no authentication required).
    The recipient clicks the email link, this endpoint validates the token,
    accepts the transfer, and returns an access token for auto-login.
    """
    result = await transfer_service.accept_transfer_public(data.transfer_token)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/resend/{reservation_unit_id}", status_code=200)
async def resend_transfer(
    reservation_unit_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Resend the transfer notification email to the recipient.
    Uses the same email and token from the existing pending transfer.
    """
    await transfer_service.resend_transfer(user.user_id, reservation_unit_id)
    return {"message": "Transfer notification resent"}


@router.post("/cancel/{reservation_unit_id}", status_code=204)
async def cancel_transfer(
    reservation_unit_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Cancel a pending transfer.

    Only the sender can cancel a transfer.
    The ticket will be restored to confirmed status.
    """
    cancelled = await transfer_service.cancel_transfer(
        user.user_id, reservation_unit_id
    )
    if not cancelled:
        raise HTTPException(
            status_code=404,
            detail="No pending transfer found for this ticket"
        )


@router.get("/outgoing", response_model=List[TransferSummary])
async def get_outgoing_transfers(
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get all transfers initiated by the current user.
    Includes pending, accepted, cancelled, and expired transfers.
    """
    transfers = await transfer_service.get_outgoing_transfers(user.user_id)
    return transfers


@router.get("/incoming", response_model=List[PendingTransfer])
async def get_incoming_transfers(
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get pending transfers for the current user.
    These are tickets that others want to transfer to you.
    """
    transfers = await transfer_service.get_incoming_transfers(user.email)
    return transfers


@router.get("/history/{reservation_unit_id}", response_model=List[TransferLogEntry])
async def get_transfer_history(
    reservation_unit_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get transfer history for a ticket.
    Shows all completed transfers for this ticket.
    """
    history = await transfer_service.get_transfer_history(reservation_unit_id)
    return history
