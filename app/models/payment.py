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
    WOMPI = "wompi"


class PaymentMethodType(str, Enum):
    """
    Tipos de método de pago soportados por Wompi.
    Docs: https://docs.wompi.co/en/docs/colombia/metodos-de-pago/
    """
    # Tarjetas
    CARD = "CARD"

    # Billeteras digitales
    NEQUI = "NEQUI"
    DAVIPLATA = "DAVIPLATA"

    # Transferencias bancarias
    PSE = "PSE"
    BANCOLOMBIA_TRANSFER = "BANCOLOMBIA_TRANSFER"

    # QR y botones
    BANCOLOMBIA_QR = "BANCOLOMBIA_QR"

    # Efectivo
    BANCOLOMBIA_COLLECT = "BANCOLOMBIA_COLLECT"

    # Puntos y cuotas
    PCOL = "PCOL"  # Puntos Colombia
    BNPL = "BNPL"  # Buy Now Pay Later (legacy)
    BANCOLOMBIA_BNPL = "BANCOLOMBIA_BNPL"  # Cuotas sin interés Bancolombia
    SU_PLUS = "SU_PLUS"  # SU+ Pay (pago a cuotas $35k-$5M COP)

    # Otros (legacy/compatibilidad)
    CREDIT_CARD = "CREDIT_CARD"
    BOTON_BANCOLOMBIA = "BOTON_BANCOLOMBIA"
    CASH = "CASH"


# Mapeo de nombres amigables para mostrar al usuario
PAYMENT_METHOD_DISPLAY_NAMES = {
    "CARD": "Tarjeta de crédito/débito",
    "CREDIT_CARD": "Tarjeta de crédito",
    "NEQUI": "Nequi",
    "DAVIPLATA": "Daviplata",
    "PSE": "PSE - Débito bancario",
    "BANCOLOMBIA_TRANSFER": "Transferencia Bancolombia",
    "BANCOLOMBIA_QR": "QR Bancolombia",
    "BANCOLOMBIA_COLLECT": "Pago en efectivo (Corresponsal)",
    "PCOL": "Puntos Colombia",
    "BNPL": "Cuotas sin interés",
    "BANCOLOMBIA_BNPL": "Cuotas sin interés Bancolombia",
    "SU_PLUS": "SU+ Pay (cuotas)",
    "BOTON_BANCOLOMBIA": "Botón Bancolombia",
    "CASH": "Efectivo",
}


def get_payment_method_display_name(method_type: str | None) -> str:
    """
    Obtiene el nombre amigable del método de pago para mostrar al usuario.

    Args:
        method_type: Tipo de método de pago (CARD, NEQUI, PSE, etc.)

    Returns:
        Nombre amigable del método de pago
    """
    if not method_type:
        return "Pago en línea"
    return PAYMENT_METHOD_DISPLAY_NAMES.get(method_type.upper(), method_type)


def get_payment_method_details(method_type: str | None, method_data: dict | None) -> dict:
    """
    Extrae información relevante del método de pago para mostrar al usuario.

    Args:
        method_type: Tipo de método (CARD, NEQUI, PSE, etc.)
        method_data: Datos del método de pago de Wompi

    Returns:
        Dict con información formateada del método de pago
    """
    if not method_type:
        return {"display_name": "Pago en línea", "details": None}

    display_name = get_payment_method_display_name(method_type)
    details = None

    if not method_data:
        return {"display_name": display_name, "details": None}

    method_type_upper = method_type.upper()

    if method_type_upper == "CARD":
        # Extraer info de tarjeta
        extra = method_data.get("extra", {})
        brand = extra.get("brand", "")
        last_four = extra.get("last_four", "")
        if brand and last_four:
            details = f"{brand} ****{last_four}"
        elif last_four:
            details = f"****{last_four}"

    elif method_type_upper == "NEQUI":
        # Extraer teléfono de Nequi
        phone = method_data.get("phone_number", "")
        if phone:
            # Ocultar parte del número por privacidad
            details = f"***{phone[-4:]}" if len(phone) >= 4 else phone

    elif method_type_upper == "DAVIPLATA":
        # Similar a Nequi
        phone = method_data.get("phone_number", "")
        if phone:
            details = f"***{phone[-4:]}" if len(phone) >= 4 else phone

    elif method_type_upper == "PSE":
        # Info de PSE (banco)
        institution = method_data.get("financial_institution_code", "")
        if institution:
            details = f"Código banco: {institution}"

    elif method_type_upper == "BANCOLOMBIA_TRANSFER":
        # Transferencia Bancolombia
        user_type = method_data.get("user_type")
        if user_type is not None:
            details = "Persona natural" if user_type == 0 else "Persona jurídica"

    elif method_type_upper == "PCOL":
        # Puntos Colombia
        points_used = method_data.get("points_used", 0)
        if points_used:
            details = f"{points_used:,} puntos"

    elif method_type_upper == "SU_PLUS":
        # SU+ Pay - pago a cuotas
        installments = method_data.get("installments") or method_data.get("extra", {}).get("installments")
        if installments:
            details = f"{installments} cuotas"

    return {
        "display_name": display_name,
        "details": details,
        "full_description": f"{display_name} ({details})" if details else display_name
    }


class PaymentBase(BaseModel):
    """Campos base de pago"""
    amount: Decimal = Field(..., gt=0, description="Monto del pago")
    currency: str = Field(default="COP", description="Moneda")
    payment_method: Optional[str] = Field(None, description="Metodo de pago")


class PaymentCreate(BaseModel):
    """Schema para iniciar pago (publico, sin auth)"""
    reservation_id: str = Field(..., description="ID de la reservacion")
    gateway: PaymentGateway = Field(default=PaymentGateway.WOMPI, description="Pasarela de pago")
    customer_email: EmailStr = Field(..., description="Email del cliente")
    customer_name: Optional[str] = Field(None, description="Nombre del cliente")
    customer_phone: Optional[str] = Field(None, description="Telefono del cliente")
    return_url: Optional[str] = Field(None, description="URL de retorno post-pago")
    amount: Optional[Decimal] = Field(None, gt=0, description="Monto a cobrar (si no se proporciona, se calcula del precio base)")


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
