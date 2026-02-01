from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser, get_authenticated_buyer, AuthenticatedBuyer
from app.models.reservation import (
    Reservation, ReservationCreate, ReservationSummary,
    CreateReservationResponse, ReservationTimeout, MyTicket
)
from app.services import reservations_service


class InvoiceTicketDetail(BaseModel):
    area_name: str
    unit_price: float
    base_price: float = 0
    service_fee: float
    quantity: int
    subtotal: float
    service_total: float
    pricing_label: str = ""
    has_discount: bool = False
    discount_type: Optional[str] = None
    discount_name: Optional[str] = None
    discount_detail: Optional[str] = None

class MyInvoice(BaseModel):
    payment_id: int
    reference: str
    amount: float
    currency: str
    payment_status: str
    payment_method_type: Optional[str] = None
    payment_date: Optional[str] = None
    finalized_at: Optional[str] = None
    gateway_name: Optional[str] = None
    event_name: str
    event_slug: str
    event_date: Optional[str] = None
    reservation_id: str
    ticket_count: int
    tickets: List[InvoiceTicketDetail]


class InvoiceUnitDetail(BaseModel):
    reservation_unit_id: int
    area_name: str
    display_name: str
    status: str
    qr_code: Optional[str] = None
    unit_price: float = 0
    base_price: float = 0
    service_fee: float = 0
    pricing_label: str = ""
    has_discount: bool = False
    discount_type: Optional[str] = None
    discount_name: Optional[str] = None


class MyInvoiceDetail(MyInvoice):
    customer_email: Optional[str] = None
    status_message: Optional[str] = None
    transaction_id: Optional[str] = None
    card_brand: Optional[str] = None
    card_last_four: Optional[str] = None
    card_name: Optional[str] = None
    installments: Optional[int] = None
    reservation_date: Optional[str] = None
    units: List[InvoiceUnitDetail] = []

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

    Environment filtering is automatic: production shows only prod events,
    development shows all events.
    """
    tickets = await reservations_service.get_my_tickets(buyer.user_id)
    return tickets


@router.get("/my-invoices", response_model=List[MyInvoice])
async def get_my_invoices(
    buyer: AuthenticatedBuyer = Depends(get_authenticated_buyer)
):
    """
    Get all payment invoices for the current user.
    Does NOT require tenant - any authenticated user can see their invoices.

    Environment filtering is automatic: production shows only prod events,
    development shows all events.
    """
    invoices = await reservations_service.get_my_invoices(buyer.user_id)
    return invoices


@router.get("/my-invoices/{payment_id}", response_model=MyInvoiceDetail)
async def get_my_invoice_detail(
    payment_id: int,
    buyer: AuthenticatedBuyer = Depends(get_authenticated_buyer)
):
    """
    Get full detail of a single payment invoice.
    Does NOT require tenant - any authenticated user can see their invoices.
    """
    invoice = await reservations_service.get_my_invoice_detail(buyer.user_id, payment_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


class EventReservation(BaseModel):
    id: str
    status: str
    reservation_date: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    total_units: int = 0
    total_paid: float = 0
    areas: List[str] = []


@router.get("/event/{cluster_id}", response_model=List[EventReservation])
async def get_event_reservations(
    cluster_id: int,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get all reservations for an event (admin view).
    Requires tenant membership for the event.
    """
    reservations = await reservations_service.get_event_reservations(
        cluster_id, user.tenant_id, status=status, limit=limit, offset=offset
    )
    if reservations is None:
        raise HTTPException(status_code=403, detail="Not authorized for this event")
    return reservations


@router.get("/event/{cluster_id}/{reservation_id}")
async def get_event_reservation_detail(
    cluster_id: int,
    reservation_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get full detail of a reservation for admin view.
    Includes customer info, payment, ticket breakdown, and individual units.
    """
    detail = await reservations_service.get_event_reservation_detail(
        cluster_id, reservation_id, user.tenant_id
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return detail


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
