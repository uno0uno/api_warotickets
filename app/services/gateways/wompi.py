"""
Wompi Payment Gateway (wompi.co)

Colombian payment gateway supporting:
- Credit/Debit Cards
- PSE (bank transfer)
- Nequi
- Bancolombia Transfer

Documentation: https://docs.wompi.co/docs/colombia/links-de-pago/
"""
import logging
import hashlib
import hmac
import httpx
from typing import Dict, Any
from datetime import datetime, timedelta
from decimal import Decimal

from app.config import settings
from app.services.gateways.base import (
    BaseGateway, PaymentIntent, WebhookResult, PaymentData, PaymentStatus
)

logger = logging.getLogger(__name__)

# Wompi API URLs
WOMPI_SANDBOX_URL = "https://sandbox.wompi.co/v1"
WOMPI_PRODUCTION_URL = "https://production.wompi.co/v1"


class WompiGateway(BaseGateway):
    """Wompi payment gateway implementation using Payment Links API"""

    def __init__(self):
        self.public_key = settings.wompi_public_key
        self.private_key = settings.wompi_private_key
        self.events_secret = settings.wompi_events_secret
        self.integrity_secret = getattr(settings, 'wompi_integrity_secret', None)
        self.environment = settings.wompi_environment

        # Set base URL based on environment
        if self.environment == 'production':
            self.base_url = WOMPI_PRODUCTION_URL
        else:
            self.base_url = WOMPI_SANDBOX_URL

    @property
    def name(self) -> str:
        return "wompi"

    @property
    def display_name(self) -> str:
        return "Wompi"

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Wompi API requests"""
        return {
            "Authorization": f"Bearer {self.private_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    async def create_payment_intent(self, data: PaymentData) -> PaymentIntent:
        """
        Create a payment link using Wompi Payment Links API.

        Wompi Payment Links flow:
        1. Create a payment link via API
        2. Get the link ID and build checkout URL
        3. Client redirects to Wompi checkout
        4. Wompi notifies via webhook when transaction completes

        Docs: https://docs.wompi.co/docs/colombia/links-de-pago/
        """
        amount_in_cents = int(data.amount * 100)
        currency = data.currency or "COP"

        # Calculate expiration (15 minutes from now)
        expiration = datetime.utcnow() + timedelta(minutes=15)
        expiration_iso = expiration.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

        # Build payload for Payment Links API
        payload = {
            "name": data.reference,
            "description": data.description or f"Pago WaRo Tickets - {data.reference}",
            "single_use": True,  # Only one successful payment allowed
            "collect_shipping": False,
            "amount_in_cents": amount_in_cents,
            "currency": currency,
            "expires_at": expiration_iso,
            # Métodos de pago habilitados (excluye SU_PLUS y BANCOLOMBIA_COLLECT
            # porque no envían transaction_id en el redirect)
            "collect_methods": [
                "CARD",
                "NEQUI",
                "PSE",
                "BANCOLOMBIA_TRANSFER",
                "BANCOLOMBIA_QR",
                "DAVIPLATA",
                "BANCOLOMBIA_BNPL",
            ],
        }

        # Add redirect URL if provided
        if data.return_url:
            payload["redirect_url"] = data.return_url

        # Add SKU/reference
        payload["sku"] = data.reference[:36]  # Max 36 chars

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/payment_links",
                    json=payload,
                    headers=self._get_headers(),
                    timeout=30.0
                )

                response_data = response.json()

                if response.status_code not in (200, 201):
                    error_msg = response_data.get("error", {}).get("message", "Unknown error")
                    logger.error(f"Wompi API error: {response.status_code} - {response_data}")
                    raise Exception(f"Wompi payment link creation failed: {error_msg}")

                # Extract link ID from response
                link_data = response_data.get("data", {})
                link_id = link_data.get("id")

                if not link_id:
                    logger.error(f"Wompi response missing link ID: {response_data}")
                    raise Exception("Wompi response missing link ID")

                # Build checkout URL
                checkout_url = f"https://checkout.wompi.co/l/{link_id}"

                logger.info(f"Created Wompi payment link: {link_id} for reference {data.reference}")

                return PaymentIntent(
                    gateway_order_id=link_id,
                    checkout_url=checkout_url,
                    reference=data.reference,
                    amount=data.amount,
                    amount_in_cents=amount_in_cents,
                    currency=currency,
                    expires_at=expiration,
                    public_key=self.public_key,
                    extra_data={
                        "environment": self.environment,
                        "link_id": link_id,
                        "link_data": link_data
                    }
                )

        except httpx.RequestError as e:
            logger.error(f"Wompi API request failed: {e}")
            raise Exception(f"Failed to connect to Wompi: {e}")

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

        # payment_link_id is our gateway_order_id (used to find the payment)
        payment_link_id = transaction.get("payment_link_id", "")
        wompi_reference = transaction.get("reference", "")
        status = transaction.get("status", "").upper()
        transaction_id = transaction.get("id")

        if not payment_link_id:
            logger.warning(f"Wompi webhook missing payment_link_id: {transaction}")
            return WebhookResult(
                success=False,
                reference="",
                status=PaymentStatus.ERROR,
                status_message="Missing payment_link_id in webhook"
            )

        # Map Wompi status to our status
        mapped_status = self._map_wompi_status(status)

        logger.info(f"Wompi webhook: payment_link_id={payment_link_id}, status={status}, tx_id={transaction_id}")

        customer_email, customer_data, billing_data = self._extract_customer_data(transaction)

        return WebhookResult(
            success=True,
            reference=payment_link_id,  # Use payment_link_id as reference (matches our gateway_order_id)
            status=mapped_status,
            gateway_transaction_id=transaction_id,
            status_message=transaction.get("status_message"),
            payment_method_type=transaction.get("payment_method_type"),
            payment_method_data=transaction.get("payment_method"),
            raw_data=event_data,
            customer_email=customer_email,
            customer_data=customer_data,
            billing_data=billing_data,
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
        # Properties come as "transaction.id", "transaction.status", etc.
        transaction = event_data.get("data", {}).get("transaction", {})
        values = []
        for prop in properties:
            # Strip "transaction." prefix to get the actual key
            key = prop.replace("transaction.", "") if prop.startswith("transaction.") else prop
            value = transaction.get(key, "")
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

        For Payment Links, we query transactions by payment_link_id.
        Docs: https://docs.wompi.co/docs/colombia/seguimiento-de-transacciones/
        """
        try:
            async with httpx.AsyncClient() as client:
                # Query transactions by payment_link_id
                response = await client.get(
                    f"{self.base_url}/transactions",
                    params={"payment_link_id": gateway_order_id},
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

                transactions = response.json().get("data", [])

                if not transactions:
                    # No transactions yet for this payment link
                    return WebhookResult(
                        success=True,
                        reference=gateway_order_id,
                        status=PaymentStatus.PENDING,
                        status_message="No transactions found for payment link"
                    )

                # Get the most recent transaction (last in list, or first by date)
                # Wompi returns transactions ordered by created_at ascending
                data = transactions[-1] if transactions else {}
                status = data.get("status", "").upper()
                mapped_status = self._map_wompi_status(status)

                customer_email, customer_data, billing_data = self._extract_customer_data(data)

                return WebhookResult(
                    success=True,
                    reference=data.get("reference", gateway_order_id),
                    status=mapped_status,
                    gateway_transaction_id=data.get("id"),
                    status_message=data.get("status_message"),
                    payment_method_type=data.get("payment_method_type"),
                    payment_method_data=data.get("payment_method"),
                    raw_data=data,
                    customer_email=customer_email,
                    customer_data=customer_data,
                    billing_data=billing_data,
                )

        except httpx.RequestError as e:
            logger.error(f"Failed to query Wompi transaction status: {e}")
            return WebhookResult(
                success=False,
                reference=gateway_order_id,
                status=PaymentStatus.ERROR,
                status_message=str(e)
            )

    def _extract_customer_data(self, transaction: Dict[str, Any]):
        """
        Extract and normalize customer contact data from a Wompi transaction object.

        Returns (customer_email, customer_data, billing_data).

        Fields intentionally excluded from customer_data:
        - device_data_token: large JWT with no business value
        - browser_info: device fingerprint, not contact data
        - device_id: device fingerprint

        PSE enrichment: address, legal_id, legal_id_type, bank_name come from
        payment_method.extra and payment_method root fields.
        NEQUI enrichment: nequi_phone from payment_method.phone_number.
        """
        customer_email = transaction.get("customer_email") or None

        raw_customer = transaction.get("customer_data") or {}
        customer_data: Dict[str, Any] = {}

        if raw_customer.get("full_name"):
            customer_data["full_name"] = raw_customer["full_name"]
        if raw_customer.get("phone_number"):
            customer_data["phone_number"] = raw_customer["phone_number"]

        # Enrich with payment-method-specific contact fields
        payment_method = transaction.get("payment_method") or {}
        pm_type = (transaction.get("payment_method_type") or "").upper()
        pm_extra = payment_method.get("extra") or {}

        if pm_type == "PSE":
            if pm_extra.get("address"):
                customer_data["address"] = pm_extra["address"]
            legal_id = payment_method.get("user_legal_id") or pm_extra.get("identificationNumber")
            legal_id_type = payment_method.get("user_legal_id_type")
            bank_name = pm_extra.get("financial_institution_name")
            if legal_id:
                customer_data["legal_id"] = str(legal_id)
            if legal_id_type:
                customer_data["legal_id_type"] = legal_id_type
            if bank_name:
                customer_data["bank_name"] = bank_name

        elif pm_type == "NEQUI":
            nequi_phone = payment_method.get("phone_number")
            if nequi_phone:
                customer_data["nequi_phone"] = str(nequi_phone)

        elif pm_type == "DAVIPLATA":
            daviplata_phone = payment_method.get("phone_number")
            if daviplata_phone:
                customer_data["daviplata_phone"] = str(daviplata_phone)

        elif pm_type == "BANCOLOMBIA_TRANSFER":
            user_type = payment_method.get("user_type")
            if user_type is not None:
                customer_data["user_type"] = str(user_type)

        elif pm_type == "CARD":
            # billing_data already handled below; card_holder available in payment_method_data
            card_holder = pm_extra.get("card_holder")
            if card_holder:
                customer_data.setdefault("full_name", card_holder)

        billing_data = transaction.get("billing_data") or None

        return (
            customer_email,
            customer_data if customer_data else None,
            billing_data,
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
