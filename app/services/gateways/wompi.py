"""
Wompi Payment Gateway (wompi.co)

Colombian payment gateway supporting:
- Credit/Debit Cards
- PSE (bank transfer)
- Nequi
- Bancolombia Transfer

Documentation: https://docs.wompi.co
"""
import logging
import hashlib
import hmac
from typing import Dict, Any
from datetime import datetime, timedelta
from decimal import Decimal

from app.config import settings
from app.services.gateways.base import (
    BaseGateway, PaymentIntent, WebhookResult, PaymentData, PaymentStatus
)

logger = logging.getLogger(__name__)


class WompiGateway(BaseGateway):
    """Wompi payment gateway implementation"""

    def __init__(self):
        self.public_key = settings.wompi_public_key
        self.private_key = settings.wompi_private_key
        self.events_secret = settings.wompi_events_secret
        self.environment = settings.wompi_environment

    @property
    def name(self) -> str:
        return "wompi"

    @property
    def display_name(self) -> str:
        return "Wompi"

    async def create_payment_intent(self, data: PaymentData) -> PaymentIntent:
        """
        Create a payment intent for Wompi.

        Wompi uses a redirect checkout flow where:
        1. We generate a reference and build the checkout URL
        2. Client redirects to Wompi checkout
        3. Wompi notifies via webhook when transaction completes
        """
        amount_in_cents = int(data.amount * 100)

        # Build Wompi checkout URL
        # In production, you might use Wompi's API to create a transaction first
        checkout_url = None
        if self.public_key:
            checkout_url = f"https://checkout.wompi.co/p/?public-key={self.public_key}"

        # Calculate expiration
        expiration = datetime.now() + timedelta(minutes=15)

        return PaymentIntent(
            gateway_order_id=data.reference,  # Wompi uses our reference
            checkout_url=checkout_url,
            reference=data.reference,
            amount=data.amount,
            amount_in_cents=amount_in_cents,
            currency=data.currency or "COP",
            expires_at=expiration,
            public_key=self.public_key,
            extra_data={
                "environment": self.environment
            }
        )

    async def verify_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Verify Wompi webhook signature.

        Wompi includes signature data in the event payload itself,
        not in headers. This method is for header-based verification.
        """
        # Wompi verification is done in process_webhook using event.signature
        return True

    async def process_webhook(self, event_data: Dict[str, Any]) -> WebhookResult:
        """
        Process Wompi webhook event.

        Wompi sends transaction.updated events with signature for verification.
        """
        event_type = event_data.get("event")
        transaction = event_data.get("data", {}).get("transaction", {})

        # Verify signature
        if not self._verify_event_signature(event_data):
            logger.warning("Invalid Wompi webhook signature")
            return WebhookResult(
                success=False,
                reference="",
                status=PaymentStatus.ERROR,
                status_message="Invalid signature"
            )

        reference = transaction.get("reference", "")
        status = transaction.get("status", "").upper()
        transaction_id = transaction.get("id")

        if not reference:
            logger.warning("Wompi webhook missing reference")
            return WebhookResult(
                success=False,
                reference="",
                status=PaymentStatus.ERROR,
                status_message="Missing reference in webhook"
            )

        # Map Wompi status to our status
        mapped_status = self._map_wompi_status(status)

        return WebhookResult(
            success=True,
            reference=reference,
            status=mapped_status,
            gateway_transaction_id=transaction_id,
            status_message=transaction.get("status_message"),
            payment_method_type=transaction.get("payment_method_type"),
            payment_method_data=transaction.get("payment_method"),
            raw_data=event_data
        )

    def _verify_event_signature(self, event_data: Dict[str, Any]) -> bool:
        """Verify Wompi event signature"""
        if not self.events_secret:
            logger.warning("Wompi events secret not configured, skipping verification")
            return True

        signature_data = event_data.get("signature", {})
        properties = signature_data.get("properties", [])
        checksum = signature_data.get("checksum", "")

        if not checksum:
            return False

        # Build string to hash
        transaction = event_data.get("data", {}).get("transaction", {})
        values = []
        for prop in properties:
            value = transaction.get(prop, "")
            values.append(str(value))

        timestamp = event_data.get("timestamp", "")
        values.append(str(timestamp))
        values.append(self.events_secret)

        concatenated = "".join(values)
        calculated = hashlib.sha256(concatenated.encode()).hexdigest()

        return hmac.compare_digest(calculated, checksum)

    async def get_payment_status(self, gateway_order_id: str) -> WebhookResult:
        """
        Query transaction status from Wompi.

        Note: gateway_order_id for Wompi is either our reference
        or the Wompi transaction ID.
        """
        # Wompi requires transaction ID for status queries
        # If we have reference, we need to lookup the transaction first
        # For now, return pending status
        return WebhookResult(
            success=True,
            reference=gateway_order_id,
            status=PaymentStatus.PENDING,
            status_message="Use webhook for status updates"
        )

    def _map_wompi_status(self, wompi_status: str) -> PaymentStatus:
        """Map Wompi status to unified PaymentStatus"""
        status_map = {
            "APPROVED": PaymentStatus.APPROVED,
            "PENDING": PaymentStatus.PENDING,
            "DECLINED": PaymentStatus.DECLINED,
            "VOIDED": PaymentStatus.VOIDED,
            "ERROR": PaymentStatus.ERROR,
        }
        return status_map.get(wompi_status.upper(), PaymentStatus.PENDING)
