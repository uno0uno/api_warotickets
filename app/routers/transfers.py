from fastapi import APIRouter, Depends, HTTPException
from typing import List
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.transfer import (
    Transfer, TransferSummary, TransferLogEntry, PendingTransfer,
    TransferInitiateRequest, TransferAcceptRequest, TransferResult
)
from app.services import transfer_service

router = APIRouter()


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
