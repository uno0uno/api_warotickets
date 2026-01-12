"""
Bold Payment Gateway (bold.co)

Colombian payment gateway supporting:
- Credit/Debit Cards
- PSE (bank transfer)
- Nequi
- Bancolombia Transfer

Documentation: https://developers.bold.co/pagos-en-linea/api-integration
"""
import logging
import hashlib
import hmac
import httpx
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from app.config import settings
from app.services.gateways.base import (
    BaseGateway, PaymentIntent, WebhookResult, PaymentData, PaymentStatus
)

logger = logging.getLogger(__name__)

# Bold API Configuration
BOLD_API_BASE_URL = "https://integrations.api.bold.co"
BOLD_SANDBOX_URL = "https://sandbox.api.bold.co"  # If different for sandbox


class BoldGateway(BaseGateway):
    """Bold.co payment gateway implementation"""

    def __init__(self):
        self.api_key = getattr(settings, 'bold_api_key', None)
        self.secret_key = getattr(settings, 'bold_secret_key', None)
        self.environment = getattr(settings, 'bold_environment', 'sandbox')
        self.base_url = BOLD_API_BASE_URL

    @property
    def name(self) -> str:
        return "bold"

    @property
    def display_name(self) -> str:
        return "Bold"

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Bold API requests"""
        return {
            "Authorization": f"x-api-key {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def create_payment_intent(self, data: PaymentData) -> PaymentIntent:
        """
        Create a payment link with Bold.

        Bold uses payment links that redirect to their checkout page.
        """
        amount_in_cents = int(data.amount * 100)

        # Build payload for Bold API
        payload = {
            "amount_type": "CLOSE",  # Fixed amount
            "amount": {
                "currency": data.currency or "COP",
                "total_amount": float(data.amount),  # Bold uses float, not cents
            },
            "description": data.description or f"Pago WaRo Tickets - {data.reference}",
        }

        # Add callback URL if provided
        if data.return_url:
            payload["callback_url"] = data.return_url

        # Add customer email if provided
        if data.customer_email:
            payload["payer_email"] = data.customer_email

        # Set expiration (15 minutes from now in nanoseconds)
        expiration = datetime.now() + timedelta(minutes=15)
        payload["expiration_date"] = int(expiration.timestamp() * 1_000_000_000)

        # Optionally restrict payment methods
        # payload["payment_methods"] = ["CREDIT_CARD", "PSE", "NEQUI", "BOTON_BANCOLOMBIA"]

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/online/link/v1",
                    json=payload,
                    headers=self._get_headers(),
                    timeout=30.0
                )

                response_data = response.json()

                if response.status_code != 200 or response_data.get("errors"):
                    errors = response_data.get("errors", [])
                    error_msg = errors[0] if errors else "Unknown error"
                    logger.error(f"Bold API error: {error_msg}")
                    raise Exception(f"Bold payment creation failed: {error_msg}")

                payment_link = response_data["payload"]["payment_link"]
                checkout_url = response_data["payload"]["url"]

                logger.info(f"Created Bold payment link: {payment_link}")

                return PaymentIntent(
                    gateway_order_id=payment_link,
                    checkout_url=checkout_url,
                    reference=data.reference,
                    amount=data.amount,
                    amount_in_cents=amount_in_cents,
                    currency=data.currency or "COP",
                    expires_at=expiration,
                    extra_data={
                        "payment_link": payment_link,
                        "environment": self.environment
                    }
                )

        except httpx.RequestError as e:
            logger.error(f"Bold API request failed: {e}")
            raise Exception(f"Failed to connect to Bold: {e}")

    async def verify_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Verify Bold webhook signature.

        Bold uses HMAC-SHA256 for webhook verification.
        """
        if not self.secret_key:
            logger.warning("Bold secret key not configured, skipping verification")
            return True

        signature = headers.get("x-bold-signature") or headers.get("X-Bold-Signature")
        if not signature:
            logger.warning("No Bold signature in webhook headers")
            return False

        # Calculate expected signature
        expected = hmac.new(
            self.secret_key.encode(),
            body,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature, expected)

    async def process_webhook(self, event_data: Dict[str, Any]) -> WebhookResult:
        """
        Process Bold webhook event.

        Bold sends transaction updates via webhook configured in merchant panel.
        """
        # Extract transaction data
        transaction = event_data.get("transaction", event_data)

        payment_link = transaction.get("payment_link") or transaction.get("id")
        status = transaction.get("status", "").upper()
        transaction_id = transaction.get("transaction_id")

        if not payment_link:
            logger.warning("Bold webhook missing payment_link")
            return WebhookResult(
                success=False,
                reference="",
                status=PaymentStatus.ERROR,
                status_message="Missing payment_link in webhook"
            )

        # Map Bold status to our status
        mapped_status = self._map_bold_status(status)

        return WebhookResult(
            success=True,
            reference=payment_link,  # We use payment_link as reference
            status=mapped_status,
            gateway_transaction_id=transaction_id,
            status_message=transaction.get("status_message"),
            payment_method_type=transaction.get("payment_method"),
            payment_method_data=transaction.get("payment_method_data"),
            raw_data=event_data
        )

    async def get_payment_status(self, gateway_order_id: str) -> WebhookResult:
        """
        Query payment link status from Bold.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/online/link/v1/{gateway_order_id}",
                    headers=self._get_headers(),
                    timeout=30.0
                )

                if response.status_code != 200:
                    return WebhookResult(
                        success=False,
                        reference=gateway_order_id,
                        status=PaymentStatus.ERROR,
                        status_message=f"HTTP {response.status_code}"
                    )

                data = response.json()
                payload = data.get("payload", {})

                status = payload.get("status", "").upper()
                mapped_status = self._map_bold_status(status)

                return WebhookResult(
                    success=True,
                    reference=gateway_order_id,
                    status=mapped_status,
                    gateway_transaction_id=payload.get("transaction_id"),
                    payment_method_type=payload.get("payment_method"),
                    raw_data=payload
                )

        except httpx.RequestError as e:
            logger.error(f"Failed to query Bold status: {e}")
            return WebhookResult(
                success=False,
                reference=gateway_order_id,
                status=PaymentStatus.ERROR,
                status_message=str(e)
            )

    def _map_bold_status(self, bold_status: str) -> PaymentStatus:
        """Map Bold status to unified PaymentStatus"""
        status_map = {
            "PAID": PaymentStatus.APPROVED,
            "APPROVED": PaymentStatus.APPROVED,
            "ACTIVE": PaymentStatus.PENDING,
            "PROCESSING": PaymentStatus.PENDING,
            "PENDING": PaymentStatus.PENDING,
            "EXPIRED": PaymentStatus.DECLINED,
            "DECLINED": PaymentStatus.DECLINED,
            "REJECTED": PaymentStatus.DECLINED,
            "VOIDED": PaymentStatus.VOIDED,
            "CANCELLED": PaymentStatus.VOIDED,
            "ERROR": PaymentStatus.ERROR,
            "FAILED": PaymentStatus.ERROR,
        }
        return status_map.get(bold_status.upper(), PaymentStatus.PENDING)
