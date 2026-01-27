from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser, get_authenticated_buyer, AuthenticatedBuyer
from app.models.reservation import (
    Reservation, ReservationCreate, ReservationSummary,
    CreateReservationResponse, ReservationTimeout, MyTicket
)
from app.services import reservations_service

router = APIRouter()


@router.get("", response_model=List[ReservationSummary])
async def list_reservations(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List all reservations for the current user.
    """
    reservations = await reservations_service.get_reservations(
        user.user_id,
        status=status,
        limit=limit,
        offset=offset
    )
    return reservations


@router.get("/my-tickets", response_model=List[MyTicket])
async def get_my_tickets(
    buyer: AuthenticatedBuyer = Depends(get_authenticated_buyer)
):
    """
    Get all confirmed tickets for the current user (buyer or organizer).
    Does NOT require tenant - any authenticated user can see their tickets.
    """
    tickets = await reservations_service.get_my_tickets(buyer.user_id)
    return tickets


@router.get("/{reservation_id}", response_model=Reservation)
async def get_reservation(
    reservation_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get reservation details by ID.
    """
    reservation = await reservations_service.get_reservation_by_id(
        reservation_id, user.user_id
    )
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return reservation


@router.get("/{reservation_id}/timeout", response_model=ReservationTimeout)
async def get_reservation_timeout(
    reservation_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get timeout info for a pending reservation.
    """
    timeout = await reservations_service.get_reservation_timeout(
        reservation_id, user.user_id
    )
    if not timeout:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found or not pending"
        )
    return timeout


@router.post("", response_model=CreateReservationResponse, status_code=201)
async def create_reservation(data: ReservationCreate):
    """
    Create a new reservation (public endpoint).

    Requires customer email - will create profile if doesn't exist.

    This will:
    1. Get or create user profile from email
    2. Verify units are available
    3. Reserve the units (block them)
    4. Calculate pricing with any applicable discounts
    5. Return reservation with payment deadline

    The reservation will expire if not paid within 15 minutes.
    """
    response = await reservations_service.create_reservation(None, data)
    return response


@router.post("/{reservation_id}/cancel", status_code=204)
async def cancel_reservation(
    reservation_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Cancel a reservation and release the units.
    """
    cancelled = await reservations_service.cancel_reservation(
        reservation_id, user.user_id
    )
    if not cancelled:
        raise HTTPException(status_code=404, detail="Reservation not found")
