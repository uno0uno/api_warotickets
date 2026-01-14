"""
Mercado Pago Payment Gateway (mercadopago.com)

Payment gateway supporting multiple countries including Colombia:
- Credit/Debit Cards
- PSE (bank transfer - Colombia)
- Cash payments (Efecty, Baloto)
- Digital wallets

Documentation: https://www.mercadopago.com.co/developers/en/docs/checkout-pro/overview
API Reference: https://www.mercadopago.com.ar/developers/en/reference/preferences/_checkout_preferences/post
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

# Mercado Pago API Configuration
MERCADOPAGO_API_BASE_URL = "https://api.mercadopago.com"


class MercadoPagoGateway(BaseGateway):
    """Mercado Pago payment gateway implementation using Checkout Pro"""

    def __init__(self):
        self.access_token = getattr(settings, 'mercadopago_access_token', None)
        self.public_key = getattr(settings, 'mercadopago_public_key', None)
        self.webhook_secret = getattr(settings, 'mercadopago_webhook_secret', None)
        self.environment = getattr(settings, 'mercadopago_environment', 'sandbox')
        self.base_url = MERCADOPAGO_API_BASE_URL

    @property
    def name(self) -> str:
        return "mercadopago"

    @property
    def display_name(self) -> str:
        return "Mercado Pago"

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Mercado Pago API requests"""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Idempotency-Key": None  # Will be set per request if needed
        }

    async def create_payment_intent(self, data: PaymentData) -> PaymentIntent:
        """
        Create a checkout preference with Mercado Pago.

        Mercado Pago Checkout Pro flow:
        1. Create a preference with product/service info
        2. Get init_point URL for checkout
        3. Client redirects to Mercado Pago checkout
        4. Mercado Pago notifies via webhook when transaction completes

        API Docs: https://www.mercadopago.com.ar/developers/en/reference/preferences/_checkout_preferences/post
        """
        amount_in_cents = int(data.amount * 100)

        # Build payload for Mercado Pago Preferences API
        payload = {
            "items": [
                {
                    "id": data.reference,
                    "title": data.description or f"Pago WaRo Tickets - {data.reference}",
                    "description": data.description or "Compra de tickets",
                    "quantity": 1,
                    "currency_id": data.currency or "COP",
                    "unit_price": float(data.amount)
                }
            ],
            "payer": {
                "email": data.customer_email
            },
            "external_reference": data.reference,
            "notification_url": data.webhook_url,
            "auto_return": "approved",
            "binary_mode": False,  # Allow pending payments
            "statement_descriptor": "WAROTICKETS",
        }

        # Add back URLs if provided
        if data.return_url:
            payload["back_urls"] = {
                "success": data.return_url,
                "failure": data.return_url,
                "pending": data.return_url
            }

        # Add payer details if available
        if data.customer_name:
            name_parts = data.customer_name.split(" ", 1)
            payload["payer"]["name"] = name_parts[0]
            if len(name_parts) > 1:
                payload["payer"]["surname"] = name_parts[1]

        if data.customer_phone:
            payload["payer"]["phone"] = {
                "number": data.customer_phone
            }

        if data.customer_document:
            payload["payer"]["identification"] = {
                "type": "CC",  # Cedula de ciudadania for Colombia
                "number": data.customer_document
            }

        # Set expiration (24 hours from now for Checkout Pro)
        expiration = datetime.utcnow() + timedelta(hours=24)
        payload["expires"] = True
        payload["expiration_date_from"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000-05:00")
        payload["expiration_date_to"] = expiration.strftime("%Y-%m-%dT%H:%M:%S.000-05:00")

        # Add metadata
        if data.metadata:
            payload["metadata"] = data.metadata

        try:
            headers = self._get_headers()
            # Remove None values
            headers = {k: v for k, v in headers.items() if v is not None}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/checkout/preferences",
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )

                response_data = response.json()

                if response.status_code not in (200, 201):
                    error_msg = response_data.get("message", "Unknown error")
                    logger.error(f"Mercado Pago API error: {error_msg} - {response_data}")
                    raise Exception(f"Mercado Pago payment creation failed: {error_msg}")

                # Get checkout URL based on environment
                if self.environment == "production":
                    checkout_url = response_data.get("init_point")
                else:
                    checkout_url = response_data.get("sandbox_init_point") or response_data.get("init_point")

                preference_id = response_data.get("id")

                logger.info(f"Created Mercado Pago preference: {preference_id}")

                return PaymentIntent(
                    gateway_order_id=preference_id,
                    checkout_url=checkout_url,
                    reference=data.reference,
                    amount=data.amount,
                    amount_in_cents=amount_in_cents,
                    currency=data.currency or "COP",
                    expires_at=expiration,
                    public_key=self.public_key,
                    extra_data={
                        "preference_id": preference_id,
                        "init_point": response_data.get("init_point"),
                        "sandbox_init_point": response_data.get("sandbox_init_point"),
                        "environment": self.environment
                    }
                )

        except httpx.RequestError as e:
            logger.error(f"Mercado Pago API request failed: {e}")
            raise Exception(f"Failed to connect to Mercado Pago: {e}")

    async def verify_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Verify Mercado Pago webhook signature.

        Mercado Pago uses x-signature header for webhook verification.
        Docs: https://www.mercadopago.com.ar/developers/en/docs/your-integrations/notifications
        """
        if not self.webhook_secret:
            logger.warning("Mercado Pago webhook secret not configured, skipping verification")
            return True

        # Get signature from headers (case-insensitive)
        signature_header = headers.get("x-signature") or headers.get("X-Signature")
        request_id = headers.get("x-request-id") or headers.get("X-Request-Id")

        if not signature_header:
            logger.warning("No Mercado Pago signature in webhook headers")
            return False

        try:
            # Parse x-signature header (format: "ts=timestamp,v1=signature")
            signature_parts = {}
            for part in signature_header.split(","):
                key, value = part.split("=", 1)
                signature_parts[key.strip()] = value.strip()

            timestamp = signature_parts.get("ts")
            received_signature = signature_parts.get("v1")

            if not timestamp or not received_signature:
                logger.warning("Invalid Mercado Pago signature format")
                return False

            # Build the signed payload
            # Format: id:[data.id];request-id:[x-request-id];ts:[ts];
            import json
            body_data = json.loads(body)
            data_id = body_data.get("data", {}).get("id", "")

            manifest = f"id:{data_id};request-id:{request_id};ts:{timestamp};"

            # Calculate expected signature
            expected_signature = hmac.new(
                self.webhook_secret.encode(),
                manifest.encode(),
                hashlib.sha256
            ).hexdigest()

            return hmac.compare_digest(received_signature, expected_signature)

        except Exception as e:
            logger.error(f"Error verifying Mercado Pago webhook signature: {e}")
            return False

    async def process_webhook(self, event_data: Dict[str, Any]) -> WebhookResult:
        """
        Process Mercado Pago webhook event.

        Mercado Pago sends notifications for payment updates.
        Docs: https://www.mercadopago.com.ar/developers/en/docs/checkout-pro/payment-notifications
        """
        event_type = event_data.get("type") or event_data.get("topic")
        action = event_data.get("action")

        # Handle different notification formats
        if event_type == "payment":
            # IPN format - need to fetch payment details
            payment_id = event_data.get("data", {}).get("id")
            if payment_id:
                return await self.get_payment_status(str(payment_id))

        elif event_type == "merchant_order":
            # Merchant order notification
            order_id = event_data.get("data", {}).get("id")
            logger.info(f"Received merchant_order notification: {order_id}")
            # For merchant orders, we might need to fetch the order details
            return WebhookResult(
                success=True,
                reference=str(order_id) if order_id else "",
                status=PaymentStatus.PENDING,
                status_message="Merchant order notification received"
            )

        # Direct payment data in webhook (less common)
        payment = event_data.get("data", {})
        if not payment:
            payment = event_data

        external_reference = payment.get("external_reference", "")
        status = payment.get("status", "").lower()
        payment_id = payment.get("id")

        if not external_reference and not payment_id:
            logger.warning("Mercado Pago webhook missing reference and payment_id")
            return WebhookResult(
                success=False,
                reference="",
                status=PaymentStatus.ERROR,
                status_message="Missing reference in webhook"
            )

        mapped_status = self._map_mercadopago_status(status)

        return WebhookResult(
            success=True,
            reference=external_reference,
            status=mapped_status,
            gateway_transaction_id=str(payment_id) if payment_id else None,
            status_message=payment.get("status_detail"),
            payment_method_type=payment.get("payment_type_id"),
            payment_method_data={
                "payment_method_id": payment.get("payment_method_id"),
                "issuer_id": payment.get("issuer_id"),
                "installments": payment.get("installments")
            },
            raw_data=event_data
        )

    async def get_payment_status(self, gateway_order_id: str) -> WebhookResult:
        """
        Query payment status from Mercado Pago.

        API Docs: https://www.mercadopago.com.co/developers/en/docs/checkout-api/response-handling/query-results
        """
        try:
            headers = self._get_headers()
            headers = {k: v for k, v in headers.items() if v is not None}

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/v1/payments/{gateway_order_id}",
                    headers=headers,
                    timeout=30.0
                )

                if response.status_code == 404:
                    return WebhookResult(
                        success=False,
                        reference=gateway_order_id,
                        status=PaymentStatus.ERROR,
                        status_message="Payment not found"
                    )

                if response.status_code != 200:
                    return WebhookResult(
                        success=False,
                        reference=gateway_order_id,
                        status=PaymentStatus.ERROR,
                        status_message=f"HTTP {response.status_code}"
                    )

                data = response.json()
                status = data.get("status", "").lower()
                mapped_status = self._map_mercadopago_status(status)

                return WebhookResult(
                    success=True,
                    reference=data.get("external_reference", gateway_order_id),
                    status=mapped_status,
                    gateway_transaction_id=str(data.get("id")),
                    status_message=data.get("status_detail"),
                    payment_method_type=data.get("payment_type_id"),
                    payment_method_data={
                        "payment_method_id": data.get("payment_method_id"),
                        "issuer_id": data.get("issuer_id"),
                        "installments": data.get("installments"),
                        "card_last_four": data.get("card", {}).get("last_four_digits")
                    },
                    raw_data=data
                )

        except httpx.RequestError as e:
            logger.error(f"Failed to query Mercado Pago status: {e}")
            return WebhookResult(
                success=False,
                reference=gateway_order_id,
                status=PaymentStatus.ERROR,
                status_message=str(e)
            )

    def _map_mercadopago_status(self, mp_status: str) -> PaymentStatus:
        """
        Map Mercado Pago status to unified PaymentStatus.

        Mercado Pago statuses:
        - pending: Payment is being processed
        - approved: Payment was approved and credited
        - authorized: Payment was authorized but not captured
        - in_process: Payment is under review
        - in_mediation: Payment in dispute
        - rejected: Payment was rejected
        - cancelled: Payment was cancelled
        - refunded: Payment was refunded
        - charged_back: Chargeback was applied

        Docs: https://www.mercadopago.com.co/developers/en/docs/checkout-api/response-handling/query-results
        """
        status_map = {
            "approved": PaymentStatus.APPROVED,
            "authorized": PaymentStatus.PENDING,  # Needs capture
            "pending": PaymentStatus.PENDING,
            "in_process": PaymentStatus.PENDING,
            "in_mediation": PaymentStatus.PENDING,
            "rejected": PaymentStatus.DECLINED,
            "cancelled": PaymentStatus.VOIDED,
            "refunded": PaymentStatus.REFUNDED,
            "charged_back": PaymentStatus.REFUNDED,
        }
        return status_map.get(mp_status.lower(), PaymentStatus.PENDING)
