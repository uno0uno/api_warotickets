from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import List
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.payment import (
    Payment, PaymentCreate, PaymentSummary,
    PaymentIntentResponse, PaymentConfirmation,
    WompiWebhookEvent
)
from app.services import payments_service
from app.config import settings

router = APIRouter()


@router.post("/intent", response_model=PaymentIntentResponse, status_code=201)
async def create_payment_intent(
    data: PaymentCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a payment intent for a reservation.

    Returns:
    - Payment ID and reference
    - Checkout URL for Wompi redirect
    - Expiration time

    The client should redirect to checkout_url to complete payment.
    """
    intent = await payments_service.create_payment_intent(user.user_id, data)
    return intent


@router.get("/{payment_id}", response_model=Payment)
async def get_payment(
    payment_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get payment details by ID.
    """
    payment = await payments_service.get_payment_by_id(payment_id, user.user_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.get("/reservation/{reservation_id}", response_model=List[PaymentSummary])
async def get_payments_by_reservation(
    reservation_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get all payments for a reservation.
    """
    payments = await payments_service.get_payments_by_reservation(reservation_id)
    return payments


@router.post("/simulate/{payment_id}", response_model=PaymentConfirmation)
async def simulate_payment(
    payment_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Simulate payment approval (sandbox only).

    This endpoint is only available in sandbox environment for testing.
    In production, payments are confirmed via Wompi webhooks.
    """
    if settings.wompi_environment != 'sandbox':
        raise HTTPException(
            status_code=403,
            detail="Simulation only available in sandbox"
        )

    confirmation = await payments_service.simulate_payment_approval(payment_id)
    return confirmation


# Webhook endpoints (no auth required - validated by signature)

@router.post("/webhooks/wompi")
async def wompi_webhook(event: WompiWebhookEvent):
    """
    Webhook endpoint for Wompi payment notifications.

    Wompi sends events when:
    - Transaction is approved
    - Transaction is declined
    - Transaction is voided
    - etc.

    This endpoint verifies the signature and processes the event.
    """
    await payments_service.process_wompi_webhook(event)
    return {"status": "received"}
