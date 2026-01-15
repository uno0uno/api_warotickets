"""
Payments Router - Gateway Agnostic

Supports multiple payment gateways:
- Bold (bold.co)
- Wompi (wompi.co)
- MercadoPago (coming soon)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.payment import (
    Payment, PaymentCreate, PaymentSummary,
    PaymentIntentResponse, PaymentConfirmation
)
from app.services import payments_service
from app.config import settings

router = APIRouter()


# ============================================================================
# PUBLIC ENDPOINTS (No authentication required)
# ============================================================================

@router.post("/intent", response_model=PaymentIntentResponse, status_code=201)
async def create_payment_intent(data: PaymentCreate):
    """
    Create a payment intent for a reservation (PUBLIC).

    This endpoint is public - no authentication required.
    The reservation must exist and be in 'pending' status.

    **Supported Gateways:**
    - `bold` - Bold.co (default)
    - `wompi` - Wompi.co

    **Request Body:**
    - `reservation_id`: UUID of the reservation
    - `gateway`: Payment gateway to use (bold, wompi)
    - `customer_email`: Customer email for receipt
    - `customer_name`: Optional customer name
    - `return_url`: URL to redirect after payment

    **Returns:**
    - `payment_id`: Our internal payment ID
    - `gateway`: Gateway used
    - `checkout_url`: Redirect URL for payment
    - `gateway_order_id`: Gateway's order/link ID
    - `expires_at`: Payment expiration time
    """
    intent = await payments_service.create_payment_intent(data)
    return intent


@router.get("/checkout/result")
async def checkout_result(id: str = None, env: str = None):
    """
    Handle Wompi redirect after checkout (PUBLIC).

    Wompi redirects to: `{redirect_url}?id=TRANSACTION_ID&env=test`

    **Query Parameters:**
    - `id`: Transaction ID from Wompi
    - `env`: Environment (test/production)

    **Returns:**
    - Payment object with status
    """
    if not id:
        raise HTTPException(status_code=400, detail="Missing transaction ID")

    payment = await payments_service.verify_transaction(id)
    return payment


@router.get("/verify/{transaction_id}")
async def verify_transaction(transaction_id: str):
    """
    Verify a transaction using the gateway's transaction ID (PUBLIC).

    This endpoint is called after Wompi redirects the user with ?id=TRANSACTION_ID.
    It queries the gateway to get the current status and updates our records.

    **Flow:**
    1. Wompi redirects to: your-site.com/checkout/result?id=TRANSACTION_ID
    2. Frontend calls: GET /payments/verify/{transaction_id}
    3. Backend queries Wompi and updates payment status

    **Returns:**
    - Payment object with updated status
    """
    payment = await payments_service.verify_transaction(transaction_id)
    return payment


@router.get("/{payment_id}/status", response_model=Payment)
async def check_payment_status(payment_id: int):
    """
    Check current payment status (PUBLIC).

    Useful for polling payment status from frontend.
    This also queries the gateway for latest status.
    """
    payment = await payments_service.check_payment_status(payment_id)
    return payment


# ============================================================================
# WEBHOOK ENDPOINTS (No auth - validated by signature)
# ============================================================================

@router.post("/webhooks/wompi")
async def wompi_webhook(request: Request):
    """
    Webhook endpoint for Wompi payment notifications.

    Wompi sends transaction.updated events with signature for verification.
    """
    event_data = await request.json()
    await payments_service.process_gateway_webhook('wompi', event_data)
    return {"status": "received"}


# ============================================================================
# AUTHENTICATED ENDPOINTS
# ============================================================================

@router.get("/{payment_id}", response_model=Payment)
async def get_payment(
    payment_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get payment details by ID (authenticated).

    Only returns payments belonging to the authenticated user.
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
    Get all payments for a reservation (authenticated).
    """
    payments = await payments_service.get_payments_by_reservation(reservation_id)
    return payments


# ============================================================================
# SANDBOX/TESTING ENDPOINTS
# ============================================================================

@router.post("/simulate/{payment_id}", response_model=PaymentConfirmation)
async def simulate_payment(payment_id: int):
    """
    Simulate payment approval (SANDBOX ONLY).

    This endpoint is only available in sandbox environment for testing.
    In production, payments are confirmed via gateway webhooks.

    **Note:** No authentication required for easier testing.
    """
    if settings.wompi_environment != 'sandbox':
        raise HTTPException(
            status_code=403,
            detail="Simulation only available in sandbox"
        )

    confirmation = await payments_service.simulate_payment_approval(payment_id)
    return confirmation
