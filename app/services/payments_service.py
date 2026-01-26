"""
Payments Service - Gateway Agnostic Implementation

Supports multiple payment gateways:
- Bold (bold.co)
- Wompi (wompi.co)
- MercadoPago (coming soon)
"""
import json
import logging
from typing import Optional
from datetime import datetime, timedelta
from decimal import Decimal

from app.database import get_db_connection
from app.config import settings
from app.models.payment import (
    Payment, PaymentCreate, PaymentSummary,
    PaymentIntentResponse, PaymentConfirmation
)
from app.services import reservations_service, email_service
from app.services.gateways import get_gateway
from app.services.gateways.base import PaymentData, PaymentStatus
from app.core.exceptions import PaymentError, ValidationError

logger = logging.getLogger(__name__)

# Reservation timeout in minutes
PAYMENT_TIMEOUT_MINUTES = 15


async def create_payment_intent(data: PaymentCreate) -> PaymentIntentResponse:
    """
    Create a payment intent using the specified gateway.

    This is a public endpoint - no authentication required.
    The reservation must exist and be in 'pending' status.
    """
    async with get_db_connection() as conn:
        # Get reservation (no user verification - public endpoint)
        reservation = await conn.fetchrow("""
            SELECT r.id, r.status, r.user_id
            FROM reservations r
            WHERE r.id = $1
        """, data.reservation_id)

        if not reservation:
            raise ValidationError("Reservation not found")

        if reservation['status'] != 'pending':
            raise ValidationError(f"Cannot pay for reservation with status: {reservation['status']}")

        # Check for existing pending payment
        existing_payment = await conn.fetchrow("""
            SELECT id, gateway_name, checkout_url, reference, gateway_order_id
            FROM payments
            WHERE reservation_id = $1 AND status = 'pending'
            ORDER BY payment_date DESC
            LIMIT 1
        """, data.reservation_id)

        # If there's an existing pending payment for same gateway, return it
        if existing_payment and existing_payment['gateway_name'] == data.gateway.value:
            # Get payment details
            payment = await conn.fetchrow("SELECT * FROM payments WHERE id = $1", existing_payment['id'])
            return PaymentIntentResponse(
                payment_id=payment['id'],
                reservation_id=data.reservation_id,
                gateway=payment['gateway_name'],
                amount=payment['amount'],
                amount_in_cents=payment['amount_in_cents'],
                currency=payment['currency'],
                reference=payment['reference'],
                checkout_url=existing_payment['checkout_url'],
                gateway_order_id=existing_payment['gateway_order_id'],
                expires_at=payment['payment_date'] + timedelta(minutes=PAYMENT_TIMEOUT_MINUTES)
            )

        # Use provided amount or calculate from reservation units (base price)
        if data.amount:
            # Amount provided (from cart with discounts)
            amount = data.amount
        else:
            # Calculate from base prices (fallback)
            total = await conn.fetchval("""
                SELECT COALESCE(SUM(a.price), 0)
                FROM reservation_units ru
                JOIN units u ON ru.unit_id = u.id
                JOIN areas a ON u.area_id = a.id
                WHERE ru.reservation_id = $1 AND ru.status = 'reserved'
            """, data.reservation_id)

            if not total or total <= 0:
                raise ValidationError("No valid units in reservation")

            amount = Decimal(str(total))
        amount_in_cents = int(amount * 100)

        # Generate unique reference
        timestamp = int(datetime.now().timestamp())
        reference = f"WT-{data.reservation_id[:8]}-{timestamp}"

        # Get gateway instance
        gateway = get_gateway(data.gateway.value)

        # Build payment data for gateway
        payment_data = PaymentData(
            reference=reference,
            amount=amount,
            currency="COP",
            customer_email=data.customer_email,
            customer_name=data.customer_name,
            customer_phone=data.customer_phone,
            description=f"WaRo Tickets - Reserva {data.reservation_id[:8]}",
            return_url=data.return_url or f"{settings.frontend_url}/checkout/result",
            webhook_url=f"{settings.base_url}/payments/webhooks/{gateway.name}",
        )

        # Create payment intent with gateway
        try:
            intent = await gateway.create_payment_intent(payment_data)
        except Exception as e:
            logger.error(f"Gateway {gateway.name} error: {e}")
            raise PaymentError(f"Failed to create payment: {str(e)}")

        # Store payment record
        payment_row = await conn.fetchrow("""
            INSERT INTO payments (
                reservation_id, payment_date, amount, currency,
                status, amount_in_cents, customer_email,
                reference, environment, gateway_name, gateway_order_id,
                updated_at
            ) VALUES (
                $1, NOW(), $2, 'COP', 'pending', $3, $4,
                $5, $6, $7, $8, NOW()
            )
            RETURNING *
        """,
            data.reservation_id,
            amount,
            amount_in_cents,
            data.customer_email,
            reference,
            settings.wompi_environment,  # Use same env setting
            gateway.name,
            intent.gateway_order_id
        )

        payment_id = payment_row['id']
        logger.info(f"Created payment {payment_id} via {gateway.name} for reservation {data.reservation_id}")

        # Update payment with checkout URL
        await conn.execute("""
            UPDATE payments SET checkout_url = $2 WHERE id = $1
        """, payment_id, intent.checkout_url)

        return PaymentIntentResponse(
            payment_id=payment_id,
            reservation_id=data.reservation_id,
            gateway=gateway.name,
            amount=amount,
            amount_in_cents=amount_in_cents,
            currency="COP",
            reference=reference,
            checkout_url=intent.checkout_url,
            gateway_order_id=intent.gateway_order_id,
            expires_at=intent.expires_at or (datetime.now() + timedelta(minutes=PAYMENT_TIMEOUT_MINUTES))
        )


async def get_payment_by_id(payment_id: int, user_id: Optional[str] = None) -> Optional[Payment]:
    """Get payment by ID with optional ownership verification"""
    async with get_db_connection(use_transaction=False) as conn:
        if user_id:
            row = await conn.fetchrow("""
                SELECT p.* FROM payments p
                JOIN reservations r ON p.reservation_id = r.id
                WHERE p.id = $1 AND r.user_id = $2
            """, payment_id, user_id)
        else:
            row = await conn.fetchrow(
                "SELECT * FROM payments WHERE id = $1",
                payment_id
            )

        if not row:
            return None

        payment_dict = dict(row)
        # Convert UUID to string
        if payment_dict.get('reservation_id'):
            payment_dict['reservation_id'] = str(payment_dict['reservation_id'])
        # Parse JSON string to dict for payment_method_data
        if payment_dict.get('payment_method_data') and isinstance(payment_dict['payment_method_data'], str):
            payment_dict['payment_method_data'] = json.loads(payment_dict['payment_method_data'])

        return Payment(**payment_dict)


async def get_payment_by_reference(reference: str) -> Optional[Payment]:
    """Get payment by reference (for webhook processing)"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM payments WHERE reference = $1",
            reference
        )

        if not row:
            return None

        payment_dict = dict(row)
        if payment_dict.get('reservation_id'):
            payment_dict['reservation_id'] = str(payment_dict['reservation_id'])
        if payment_dict.get('payment_method_data') and isinstance(payment_dict['payment_method_data'], str):
            payment_dict['payment_method_data'] = json.loads(payment_dict['payment_method_data'])

        return Payment(**payment_dict)


async def get_payment_by_gateway_order(gateway_order_id: str) -> Optional[Payment]:
    """Get payment by gateway order ID"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM payments WHERE gateway_order_id = $1",
            gateway_order_id
        )

        if not row:
            return None

        payment_dict = dict(row)
        if payment_dict.get('reservation_id'):
            payment_dict['reservation_id'] = str(payment_dict['reservation_id'])
        if payment_dict.get('payment_method_data') and isinstance(payment_dict['payment_method_data'], str):
            payment_dict['payment_method_data'] = json.loads(payment_dict['payment_method_data'])

        return Payment(**payment_dict)


async def process_gateway_webhook(gateway_name: str, event_data: dict) -> bool:
    """
    Process webhook from any gateway.

    This is the unified webhook handler that routes to the appropriate gateway.
    """
    gateway = get_gateway(gateway_name)

    try:
        result = await gateway.process_webhook(event_data)
    except Exception as e:
        logger.error(f"Webhook processing error for {gateway_name}: {e}")
        raise PaymentError(f"Webhook processing failed: {str(e)}")

    if not result.success:
        logger.warning(f"Webhook processing failed: {result.status_message}")
        return False

    # Find payment by reference or gateway_order_id
    payment = await get_payment_by_reference(result.reference)
    if not payment:
        payment = await get_payment_by_gateway_order(result.reference)

    if not payment:
        logger.warning(f"Payment not found for reference: {result.reference}")
        return False

    # Check if payment was already finalized (avoid duplicate processing)
    was_already_approved = payment.status == 'approved'

    # Update payment status
    new_status = result.status.value
    is_final = new_status in ('approved', 'declined', 'voided', 'error')

    async with get_db_connection() as conn:
        await conn.execute("""
            UPDATE payments
            SET status = $2,
                payment_gateway_transaction_id = $3,
                finalized_at = CASE WHEN $7 THEN NOW() ELSE NULL END,
                status_message = $4,
                payment_method_type = $5,
                payment_method_data = $6,
                updated_at = NOW()
            WHERE id = $1
        """,
            payment.id,
            new_status,
            result.gateway_transaction_id,
            result.status_message,
            result.payment_method_type,
            json.dumps(result.payment_method_data) if result.payment_method_data else None,
            is_final
        )

        logger.info(f"Updated payment {payment.id} status to {result.status.value}")

        # If approved and wasn't already, confirm reservation and send email
        if result.status == PaymentStatus.APPROVED and not was_already_approved:
            await reservations_service.confirm_reservation(payment.reservation_id)
            logger.info(f"Confirmed reservation {payment.reservation_id}")

            # Send purchase confirmation email
            try:
                await send_purchase_confirmation_email(
                    payment.reservation_id,
                    payment.customer_email,
                    payment.amount,
                    payment.reference
                )
            except Exception as e:
                logger.error(f"Failed to send confirmation email via webhook: {e}")

    return True


async def get_payments_by_reservation(reservation_id: str) -> list[PaymentSummary]:
    """Get all payments for a reservation"""
    async with get_db_connection(use_transaction=False) as conn:
        rows = await conn.fetch("""
            SELECT id, reservation_id, amount, currency, status,
                   payment_method, payment_date
            FROM payments
            WHERE reservation_id = $1
            ORDER BY payment_date DESC
        """, reservation_id)

        return [PaymentSummary(**dict(row)) for row in rows]


async def simulate_payment_approval(payment_id: int) -> PaymentConfirmation:
    """Simulate payment approval (for testing in sandbox)"""
    if settings.wompi_environment != 'sandbox':
        raise PaymentError("Simulation only available in sandbox environment")

    async with get_db_connection() as conn:
        payment = await conn.fetchrow(
            "SELECT * FROM payments WHERE id = $1",
            payment_id
        )

        if not payment:
            raise ValidationError("Payment not found")

        if payment['status'] != 'pending':
            raise ValidationError(f"Payment already processed with status: {payment['status']}")

        # Update payment to approved
        sim_transaction_id = f"SIM-{int(datetime.now().timestamp())}"
        await conn.execute("""
            UPDATE payments
            SET status = 'approved',
                payment_gateway_transaction_id = $2,
                finalized_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
        """, payment_id, sim_transaction_id)

        reservation_id = str(payment['reservation_id'])

        # Confirm reservation
        await reservations_service.confirm_reservation(reservation_id)

        # Get user_id from reservation
        user_id = await conn.fetchval(
            "SELECT user_id FROM reservations WHERE id = $1",
            payment['reservation_id']
        )

    # Get tickets (outside transaction)
    tickets = await reservations_service.get_my_tickets(str(user_id))

    logger.info(f"Simulated approval for payment {payment_id}")

    return PaymentConfirmation(
        payment_id=payment_id,
        reservation_id=reservation_id,
        status='approved',
        amount=payment['amount'],
        currency=payment['currency'],
        payment_method=payment['gateway_name'],
        transaction_id=sim_transaction_id,
        tickets=[t.model_dump() for t in tickets]
    )


async def check_payment_status(payment_id: int) -> Payment:
    """
    Check current payment status with the gateway.

    Useful for polling or verifying status.
    Also updates our records and confirms reservation if approved.
    """
    payment = await get_payment_by_id(payment_id)
    if not payment:
        raise ValidationError("Payment not found")

    # If already finalized, return current status
    if payment.status in ['approved', 'declined', 'voided', 'error']:
        return payment

    # Query gateway for current status
    if payment.gateway_name and payment.gateway_order_id:
        gateway = get_gateway(payment.gateway_name)
        result = await gateway.get_payment_status(payment.gateway_order_id)

        if result.success and result.status != PaymentStatus.PENDING:
            # Update our records with all available data
            async with get_db_connection() as conn:
                await conn.execute("""
                    UPDATE payments
                    SET status = $2,
                        payment_gateway_transaction_id = $3,
                        finalized_at = CASE WHEN $2 IN ('approved', 'declined', 'voided', 'error') THEN NOW() ELSE NULL END,
                        status_message = $4,
                        payment_method_type = $5,
                        payment_method_data = $6,
                        updated_at = NOW()
                    WHERE id = $1
                """,
                    payment_id,
                    result.status.value,
                    result.gateway_transaction_id,
                    result.status_message,
                    result.payment_method_type,
                    json.dumps(result.payment_method_data) if result.payment_method_data else None
                )

                logger.info(f"Updated payment {payment_id} status to {result.status.value} via polling")

                # If approved, confirm reservation
                if result.status == PaymentStatus.APPROVED:
                    await reservations_service.confirm_reservation(payment.reservation_id)
                    logger.info(f"Confirmed reservation {payment.reservation_id} via polling")

            payment = await get_payment_by_id(payment_id)

    return payment


async def verify_transaction(transaction_id: str) -> Payment:
    """
    Verify a transaction using the gateway's transaction ID.

    This is called after the user is redirected from the payment gateway.
    Wompi redirects with ?id=TRANSACTION_ID, and we use that to verify.

    Flow:
    1. Query gateway for transaction details using transaction_id
    2. Extract payment_link_id from response
    3. Find our payment record by gateway_order_id
    4. Update payment status and confirm reservation if approved
    """
    import httpx

    # For now, we support Wompi. Can be extended for other gateways.
    # Query Wompi for transaction details
    try:
        async with httpx.AsyncClient() as client:
            # Determine environment
            if settings.wompi_environment == 'production':
                base_url = "https://production.wompi.co/v1"
            else:
                base_url = "https://sandbox.wompi.co/v1"

            response = await client.get(
                f"{base_url}/transactions/{transaction_id}",
                headers={
                    "Authorization": f"Bearer {settings.wompi_private_key}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )

            if response.status_code == 404:
                raise ValidationError(f"Transaction {transaction_id} not found in gateway")

            if response.status_code != 200:
                raise PaymentError(f"Gateway error: HTTP {response.status_code}")

            tx_data = response.json().get("data", {})

    except httpx.RequestError as e:
        logger.error(f"Failed to query gateway for transaction {transaction_id}: {e}")
        raise PaymentError(f"Failed to connect to payment gateway: {e}")

    # Extract payment_link_id to find our payment record
    payment_link_id = tx_data.get("payment_link_id")
    if not payment_link_id:
        raise ValidationError("Transaction is not associated with a payment link")

    # Find our payment by gateway_order_id (which is the payment_link_id)
    payment = await get_payment_by_gateway_order(payment_link_id)
    if not payment:
        raise ValidationError(f"Payment not found for payment link: {payment_link_id}")

    # If already finalized, ensure reservation is confirmed and return
    if payment.status in ['approved', 'declined', 'voided', 'error']:
        # Even if payment was already finalized, ensure reservation is confirmed
        # (handles cases where reservation expired during payment)
        if payment.status == 'approved':
            await reservations_service.confirm_reservation(payment.reservation_id)
        return payment

    # Map Wompi status to our status
    wompi_status = tx_data.get("status", "").upper()
    status_map = {
        "APPROVED": "approved",
        "PENDING": "pending",
        "DECLINED": "declined",
        "VOIDED": "voided",
        "ERROR": "error",
    }
    new_status = status_map.get(wompi_status, "pending")

    # Update our payment record
    async with get_db_connection() as conn:
        payment_method_data = json.dumps(tx_data.get("payment_method")) if tx_data.get("payment_method") else None
        is_final = new_status in ['approved', 'declined', 'voided', 'error']

        await conn.execute("""
            UPDATE payments
            SET status = $2,
                payment_gateway_transaction_id = $3,
                finalized_at = CASE WHEN $7 THEN NOW() ELSE NULL END,
                status_message = $4,
                payment_method_type = $5,
                payment_method_data = $6,
                updated_at = NOW()
            WHERE id = $1
        """,
            payment.id,
            new_status,
            tx_data.get("id"),
            tx_data.get("status_message"),
            tx_data.get("payment_method_type"),
            payment_method_data,
            is_final
        )

        logger.info(f"Updated payment {payment.id} to status {new_status} via verify_transaction")

        # If approved, confirm reservation and send email
        if new_status == "approved":
            await reservations_service.confirm_reservation(payment.reservation_id)
            logger.info(f"Confirmed reservation {payment.reservation_id} via verify_transaction")

            # Send purchase confirmation email
            try:
                await send_purchase_confirmation_email(
                    payment.reservation_id,
                    payment.customer_email,
                    payment.amount,
                    payment.reference
                )
            except Exception as e:
                logger.error(f"Failed to send confirmation email: {e}")

    # Return updated payment
    return await get_payment_by_id(payment.id)


async def send_purchase_confirmation_email(
    reservation_id: str,
    customer_email: str,
    amount: Decimal,
    reference: str
) -> bool:
    """
    Gather purchase details and send confirmation email.
    """
    async with get_db_connection() as conn:
        # Get event info from reservation
        event_info = await conn.fetchrow("""
            SELECT DISTINCT
                c.cluster_name,
                c.start_date,
                c.extra_attributes->>'location' as event_location
            FROM reservations r
            JOIN reservation_units ru ON ru.reservation_id = r.id
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE r.id = $1
            LIMIT 1
        """, reservation_id)

        if not event_info:
            logger.warning(f"Could not find event info for reservation {reservation_id}")
            return False

        # Get tickets summary grouped by area
        tickets_data = await conn.fetch("""
            SELECT
                a.area_name,
                COUNT(ru.id) as quantity,
                a.price as unit_price,
                COALESCE(a.service, 0) as service_fee_per_ticket
            FROM reservation_units ru
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            WHERE ru.reservation_id = $1
            GROUP BY a.area_name, a.price, a.service
            ORDER BY a.area_name
        """, reservation_id)

        # Build tickets list
        tickets = []
        subtotal = Decimal('0')
        total_service_fee = Decimal('0')

        for row in tickets_data:
            qty = row['quantity']
            price = Decimal(str(row['unit_price']))
            fee = Decimal(str(row['service_fee_per_ticket'] or 0))
            ticket_subtotal = price * qty
            ticket_fee = fee * qty

            tickets.append({
                'area_name': row['area_name'],
                'quantity': qty,
                'unit_price': float(price),
                'subtotal': float(ticket_subtotal)
            })

            subtotal += ticket_subtotal
            total_service_fee += ticket_fee

        # Send email
        success = await email_service.send_simple_purchase_confirmation(
            to_email=customer_email,
            event_name=event_info['cluster_name'],
            event_date=event_info['start_date'],
            event_location=event_info['event_location'],
            tickets=tickets,
            subtotal=subtotal,
            service_fee=total_service_fee,
            total=amount,
            reference=reference,
            payment_method="Tarjeta de credito/debito"
        )

        if success:
            logger.info(f"Purchase confirmation email sent to {customer_email}")
        else:
            logger.warning(f"Failed to send purchase confirmation to {customer_email}")

        return success
