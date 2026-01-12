"""
Base Payment Gateway Interface

All payment gateways must implement this interface to ensure
consistent behavior across different providers.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
from enum import Enum


class PaymentStatus(str, Enum):
    """Unified payment status across all gateways"""
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    VOIDED = "voided"
    ERROR = "error"
    REFUNDED = "refunded"


@dataclass
class PaymentIntent:
    """Result of creating a payment intent"""
    gateway_order_id: str
    checkout_url: str
    reference: str
    amount: Decimal
    amount_in_cents: int
    currency: str
    expires_at: Optional[datetime] = None
    public_key: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


@dataclass
class WebhookResult:
    """Result of processing a webhook"""
    success: bool
    reference: str
    status: PaymentStatus
    gateway_transaction_id: Optional[str] = None
    status_message: Optional[str] = None
    payment_method_type: Optional[str] = None
    payment_method_data: Optional[Dict[str, Any]] = None
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class PaymentData:
    """Data needed to create a payment"""
    reference: str
    amount: Decimal
    currency: str
    customer_email: str
    description: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_document: Optional[str] = None
    return_url: Optional[str] = None
    webhook_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class BaseGateway(ABC):
    """
    Abstract base class for payment gateways.

    All payment gateways must implement these methods to ensure
    consistent behavior across different providers.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Gateway identifier (e.g., 'bold', 'wompi', 'mercadopago')"""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable gateway name"""
        pass

    @abstractmethod
    async def create_payment_intent(self, data: PaymentData) -> PaymentIntent:
        """
        Create a payment intent/order with the gateway.

        Args:
            data: Payment data including amount, customer info, etc.

        Returns:
            PaymentIntent with checkout URL and order details
        """
        pass

    @abstractmethod
    async def verify_webhook(self, headers: Dict[str, str], body: bytes) -> bool:
        """
        Verify webhook signature from the gateway.

        Args:
            headers: Request headers
            body: Raw request body

        Returns:
            True if signature is valid
        """
        pass

    @abstractmethod
    async def process_webhook(self, event_data: Dict[str, Any]) -> WebhookResult:
        """
        Process webhook event from the gateway.

        Args:
            event_data: Parsed webhook payload

        Returns:
            WebhookResult with payment status and details
        """
        pass

    @abstractmethod
    async def get_payment_status(self, gateway_order_id: str) -> WebhookResult:
        """
        Query payment status from the gateway.

        Args:
            gateway_order_id: The order/transaction ID from the gateway

        Returns:
            WebhookResult with current payment status
        """
        pass

    def map_status(self, gateway_status: str) -> PaymentStatus:
        """
        Map gateway-specific status to unified PaymentStatus.
        Override in subclasses for gateway-specific mappings.
        """
        status_map = {
            'approved': PaymentStatus.APPROVED,
            'pending': PaymentStatus.PENDING,
            'declined': PaymentStatus.DECLINED,
            'voided': PaymentStatus.VOIDED,
            'error': PaymentStatus.ERROR,
            'refunded': PaymentStatus.REFUNDED,
        }
        return status_map.get(gateway_status.lower(), PaymentStatus.PENDING)
