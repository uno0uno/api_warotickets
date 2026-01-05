from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum


class PaymentStatus(str, Enum):
    """Estados de pago"""
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    VOIDED = "voided"
    ERROR = "error"
    REFUNDED = "refunded"


class PaymentMethodType(str, Enum):
    """Tipos de metodo de pago"""
    CARD = "CARD"
    NEQUI = "NEQUI"
    PSE = "PSE"
    BANCOLOMBIA_TRANSFER = "BANCOLOMBIA_TRANSFER"
    CASH = "CASH"


class PaymentBase(BaseModel):
    """Campos base de pago"""
    amount: Decimal = Field(..., gt=0, description="Monto del pago")
    currency: str = Field(default="COP", description="Moneda")
    payment_method: Optional[str] = Field(None, description="Metodo de pago")


class PaymentCreate(BaseModel):
    """Schema para iniciar pago"""
    reservation_id: str = Field(..., description="ID de la reservacion")
    payment_method_type: PaymentMethodType = Field(..., description="Tipo de metodo de pago")
    customer_email: str = Field(..., description="Email del cliente")
    customer_data: Optional[dict] = Field(None, description="Datos adicionales del cliente")
    billing_data: Optional[dict] = Field(None, description="Datos de facturacion")
    return_url: Optional[str] = Field(None, description="URL de retorno post-pago")


class Payment(PaymentBase):
    """Schema completo de pago"""
    id: int
    reservation_id: str
    payment_date: datetime
    status: str = "pending"
    payment_gateway_transaction_id: Optional[str] = None
    amount_in_cents: Optional[int] = None
    payment_method_type: Optional[str] = None
    payment_method_data: Optional[dict] = None
    customer_email: Optional[str] = None
    customer_data: Optional[dict] = None
    billing_data: Optional[dict] = None
    finalized_at: Optional[datetime] = None
    status_message: Optional[str] = None
    reference: Optional[str] = None
    environment: Optional[str] = None
    updated_at: datetime
    order_id: Optional[str] = None

    class Config:
        from_attributes = True


class PaymentSummary(BaseModel):
    """Schema resumido de pago"""
    id: int
    reservation_id: str
    amount: Decimal
    currency: str
    status: str
    payment_method: Optional[str] = None
    payment_date: datetime

    class Config:
        from_attributes = True


class WompiTransactionCreate(BaseModel):
    """Datos para crear transaccion en Wompi"""
    amount_in_cents: int
    currency: str = "COP"
    customer_email: str
    reference: str
    payment_method_type: str
    redirect_url: Optional[str] = None
    customer_data: Optional[dict] = None


class WompiWebhookEvent(BaseModel):
    """Evento webhook de Wompi"""
    event: str
    data: dict
    sent_at: str
    timestamp: int
    signature: dict
    environment: str


class WompiTransactionStatus(BaseModel):
    """Estado de transaccion Wompi"""
    id: str
    status: str
    status_message: Optional[str] = None
    reference: str
    amount_in_cents: int
    currency: str
    payment_method_type: str
    payment_method: Optional[dict] = None
    finalized_at: Optional[str] = None


class PaymentIntentResponse(BaseModel):
    """Respuesta al crear intencion de pago"""
    payment_id: int
    reservation_id: str
    amount: Decimal
    amount_in_cents: int
    currency: str
    reference: str
    checkout_url: Optional[str] = None
    public_key: Optional[str] = None
    expires_at: datetime


class PaymentConfirmation(BaseModel):
    """Confirmacion de pago exitoso"""
    payment_id: int
    reservation_id: str
    status: str
    amount: Decimal
    currency: str
    payment_method: Optional[str] = None
    transaction_id: Optional[str] = None
    tickets: List[Any] = []  # List[MyTicket]
