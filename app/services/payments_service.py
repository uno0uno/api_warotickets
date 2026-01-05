import logging
import hashlib
import hmac
from typing import Optional
from datetime import datetime
from decimal import Decimal
from app.database import get_db_connection
from app.config import settings
from app.models.payment import (
    Payment, PaymentCreate, PaymentSummary,
    PaymentIntentResponse, PaymentConfirmation,
    WompiWebhookEvent, WompiTransactionStatus
)
from app.services import reservations_service
from app.core.exceptions import PaymentError, ValidationError

logger = logging.getLogger(__name__)


async def create_payment_intent(user_id: str, data: PaymentCreate) -> PaymentIntentResponse:
    """Create a payment intent for a reservation"""
    async with get_db_connection() as conn:
        # Get reservation and verify ownership
        reservation = await conn.fetchrow("""
            SELECT r.id, r.status, r.user_id
            FROM reservations r
            WHERE r.id = $1 AND r.user_id = $2
        """, data.reservation_id, user_id)

        if not reservation:
            raise ValidationError("Reservation not found")

        if reservation['status'] != 'pending':
            raise ValidationError(f"Cannot pay for reservation with status: {reservation['status']}")

        # Calculate total amount
        total = await conn.fetchval("""
            SELECT COALESCE(SUM(a.price), 0)
            FROM reservation_units ru
            JOIN units u ON ru.unit_id = u.id
            JOIN areas a ON u.area_id = a.id
            WHERE ru.reservation_id = $1
        """, data.reservation_id)

        amount = Decimal(str(total))
        amount_in_cents = int(amount * 100)

        # Generate unique reference
        reference = f"WT-{data.reservation_id[:8]}-{int(datetime.now().timestamp())}"

        # Create payment record
        payment_row = await conn.fetchrow("""
            INSERT INTO payments (
                reservation_id, payment_date, amount, currency,
                status, amount_in_cents, payment_method_type,
                customer_email, customer_data, billing_data,
                reference, environment, updated_at
            ) VALUES (
                $1, NOW(), $2, 'COP', 'pending', $3, $4,
                $5, $6, $7, $8, $9, NOW()
            )
            RETURNING *
        """,
            data.reservation_id,
            amount,
            amount_in_cents,
            data.payment_method_type.value,
            data.customer_email,
            data.customer_data or {},
            data.billing_data or {},
            reference,
            settings.wompi_environment
        )

        payment_id = payment_row['id']

        # Build checkout URL (Wompi redirect)
        checkout_url = None
        if settings.wompi_public_key:
            # In production, this would be Wompi's checkout URL
            checkout_url = f"https://checkout.wompi.co/p/?public-key={settings.wompi_public_key}"

        # Calculate expiration (same as reservation timeout)
        expires_at = datetime.now() + reservations_service.timedelta(
            minutes=reservations_service.RESERVATION_TIMEOUT_MINUTES
        )

        logger.info(f"Created payment intent {payment_id} for reservation {data.reservation_id}")

        return PaymentIntentResponse(
            payment_id=payment_id,
            reservation_id=data.reservation_id,
            amount=amount,
            amount_in_cents=amount_in_cents,
            currency="COP",
            reference=reference,
            checkout_url=checkout_url,
            public_key=settings.wompi_public_key,
            expires_at=expires_at
        )


async def get_payment_by_id(payment_id: int, user_id: str) -> Optional[Payment]:
    """Get payment by ID with ownership verification"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT p.* FROM payments p
            JOIN reservations r ON p.reservation_id = r.id
            WHERE p.id = $1 AND r.user_id = $2
        """, payment_id, user_id)

        if not row:
            return None

        return Payment(**dict(row))


async def get_payment_by_reference(reference: str) -> Optional[Payment]:
    """Get payment by reference (for webhook processing)"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM payments WHERE reference = $1",
            reference
        )

        if not row:
            return None

        return Payment(**dict(row))


async def process_wompi_webhook(event: WompiWebhookEvent) -> bool:
    """Process Wompi webhook event"""

    # Verify signature
    if not verify_wompi_signature(event):
        logger.warning("Invalid Wompi webhook signature")
        raise PaymentError("Invalid signature")

    event_type = event.event
    transaction_data = event.data.get('transaction', {})

    if event_type == 'transaction.updated':
        return await handle_transaction_updated(transaction_data)

    logger.info(f"Unhandled Wompi event type: {event_type}")
    return True


def verify_wompi_signature(event: WompiWebhookEvent) -> bool:
    """Verify Wompi webhook signature"""
    if not settings.wompi_events_secret:
        logger.warning("Wompi events secret not configured, skipping signature verification")
        return True

    # Wompi signature verification
    signature_data = event.signature
    properties = signature_data.get('properties', [])
    checksum = signature_data.get('checksum', '')

    # Build string to hash
    transaction = event.data.get('transaction', {})
    values = []
    for prop in properties:
        value = transaction.get(prop, '')
        values.append(str(value))

    values.append(str(event.timestamp))
    values.append(settings.wompi_events_secret)

    concatenated = ''.join(values)
    calculated_checksum = hashlib.sha256(concatenated.encode()).hexdigest()

    return hmac.compare_digest(calculated_checksum, checksum)


async def handle_transaction_updated(transaction: dict) -> bool:
    """Handle transaction.updated event from Wompi"""
    reference = transaction.get('reference')
    status = transaction.get('status')
    transaction_id = transaction.get('id')

    if not reference:
        logger.warning("Transaction update without reference")
        return False

    async with get_db_connection() as conn:
        # Find payment by reference
        payment = await conn.fetchrow(
            "SELECT id, reservation_id, status FROM payments WHERE reference = $1",
            reference
        )

        if not payment:
            logger.warning(f"Payment not found for reference: {reference}")
            return False

        # Map Wompi status to our status
        status_mapping = {
            'APPROVED': 'approved',
            'DECLINED': 'declined',
            'VOIDED': 'voided',
            'ERROR': 'error',
            'PENDING': 'pending'
        }

        new_status = status_mapping.get(status, 'pending')

        # Update payment
        await conn.execute("""
            UPDATE payments
            SET status = $2,
                payment_gateway_transaction_id = $3,
                finalized_at = CASE WHEN $2 IN ('approved', 'declined', 'voided', 'error') THEN NOW() ELSE NULL END,
                status_message = $4,
                payment_method_data = $5,
                updated_at = NOW()
            WHERE id = $1
        """,
            payment['id'],
            new_status,
            transaction_id,
            transaction.get('status_message'),
            transaction.get('payment_method', {})
        )

        logger.info(f"Updated payment {payment['id']} status to {new_status}")

        # If approved, confirm reservation
        if new_status == 'approved':
            await reservations_service.confirm_reservation(str(payment['reservation_id']))
            logger.info(f"Confirmed reservation {payment['reservation_id']}")

        # If declined/error, could release reservation (or let it expire)

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
        await conn.execute("""
            UPDATE payments
            SET status = 'approved',
                payment_gateway_transaction_id = $2,
                finalized_at = NOW(),
                updated_at = NOW()
            WHERE id = $1
        """, payment_id, f"SIM-{int(datetime.now().timestamp())}")

        # Confirm reservation
        await reservations_service.confirm_reservation(str(payment['reservation_id']))

        # Get tickets
        tickets = await reservations_service.get_my_tickets(
            (await conn.fetchval(
                "SELECT user_id FROM reservations WHERE id = $1",
                payment['reservation_id']
            ))
        )

        logger.info(f"Simulated approval for payment {payment_id}")

        return PaymentConfirmation(
            payment_id=payment_id,
            reservation_id=str(payment['reservation_id']),
            status='approved',
            amount=payment['amount'],
            currency=payment['currency'],
            payment_method=payment['payment_method_type'],
            transaction_id=f"SIM-{int(datetime.now().timestamp())}",
            tickets=[t.model_dump() for t in tickets]
        )
