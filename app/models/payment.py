from pydantic import BaseModel, Field, EmailStr
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


class PaymentGateway(str, Enum):
    """Pasarelas de pago soportadas"""
    BOLD = "bold"
    WOMPI = "wompi"
    MERCADOPAGO = "mercadopago"


class PaymentMethodType(str, Enum):
    """Tipos de metodo de pago"""
    CARD = "CARD"
    CREDIT_CARD = "CREDIT_CARD"
    NEQUI = "NEQUI"
    PSE = "PSE"
    BANCOLOMBIA_TRANSFER = "BANCOLOMBIA_TRANSFER"
    BOTON_BANCOLOMBIA = "BOTON_BANCOLOMBIA"
    CASH = "CASH"


class PaymentBase(BaseModel):
    """Campos base de pago"""
    amount: Decimal = Field(..., gt=0, description="Monto del pago")
    currency: str = Field(default="COP", description="Moneda")
    payment_method: Optional[str] = Field(None, description="Metodo de pago")


class PaymentCreate(BaseModel):
    """Schema para iniciar pago (publico, sin auth)"""
    reservation_id: str = Field(..., description="ID de la reservacion")
    gateway: PaymentGateway = Field(default=PaymentGateway.BOLD, description="Pasarela de pago")
    customer_email: EmailStr = Field(..., description="Email del cliente")
    customer_name: Optional[str] = Field(None, description="Nombre del cliente")
    customer_phone: Optional[str] = Field(None, description="Telefono del cliente")
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
    gateway_name: Optional[str] = None
    gateway_order_id: Optional[str] = None

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
    gateway: str
    amount: Decimal
    amount_in_cents: int
    currency: str
    reference: str
    checkout_url: Optional[str] = None
    gateway_order_id: Optional[str] = None
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
