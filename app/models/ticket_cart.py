from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


class CartStatus(str, Enum):
    """Estados del carrito"""
    ACTIVE = "active"           # Carrito activo
    ABANDONED = "abandoned"     # Abandonado (expiro)
    CONVERTED = "converted"     # Convertido a reserva


class TicketCartItemCreate(BaseModel):
    """Schema para agregar item al carrito"""
    area_id: int = Field(..., description="ID del area")
    quantity: int = Field(..., ge=1, le=10, description="Cantidad de bundles/tickets")


class TicketCartCreate(BaseModel):
    """Schema para crear carrito"""
    cluster_id: int = Field(..., description="ID del evento")
    items: Optional[List[TicketCartItemCreate]] = Field(default=None, description="Items iniciales")


class TicketCartItemUpdate(BaseModel):
    """Schema para actualizar cantidad de item"""
    quantity: int = Field(..., ge=1, le=10, description="Nueva cantidad")


class CartCheckout(BaseModel):
    """Schema para checkout del carrito"""
    customer_name: str = Field(..., min_length=2, max_length=100, description="Nombre del cliente")
    customer_email: str = Field(..., description="Email del cliente")
    customer_phone: str = Field(..., min_length=7, max_length=20, description="Telefono del cliente")
    accept_terms: bool = Field(..., description="Acepta terminos y condiciones")
    return_url: Optional[str] = Field(None, description="URL de retorno despues del pago")


# Response Models

class TicketCartItemResponse(BaseModel):
    """Item del carrito en respuesta - Precios calculados en tiempo real"""
    id: str
    area_id: int
    area_name: str
    quantity: int               # Bundles/paquetes seleccionados por el usuario

    # Campos calculados en tiempo real (no almacenados en DB)
    tickets_count: int          # Total boletas (quantity * bundle_size)
    unit_price: Decimal         # Precio por boleta con descuento
    bundle_price: Optional[Decimal]  # Precio del bundle (si aplica)
    original_price: Decimal     # Precio original sin descuento
    subtotal: Decimal           # Total del item
    bundle_size: int            # Tamano del bundle (1, 2, 3...)

    # Stage info (calculado desde estado actual)
    stage_name: Optional[str] = None
    stage_id: Optional[str] = None
    stage_status: str = "none"  # "active" | "none"

    # Promotion info
    promotion_id: Optional[str] = None
    promotion_name: Optional[str] = None
    tickets_per_package: Optional[int] = None  # Boletas de esta area por combo (solo para promos)

    @field_validator('id', 'stage_id', 'promotion_id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class ConvertedPromotion(BaseModel):
    """Info de una promocion que fue convertida a items individuales"""
    promotion_name: str
    reason: str
    items_converted: int


class TicketCartResponse(BaseModel):
    """Respuesta completa del carrito - Precios calculados en tiempo real"""
    id: str
    cluster_id: int
    cluster_name: str
    cluster_slug: str
    status: str
    items: List[TicketCartItemResponse]
    subtotal: Decimal           # Sum of all item subtotals
    discount: Decimal           # Total discount applied
    total: Decimal              # Final total
    tickets_count: int          # Total tickets in cart
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Promociones que fueron convertidas a items individuales
    converted_promotions: List[ConvertedPromotion] = []

    @field_validator('id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class CheckoutResponse(BaseModel):
    """Respuesta del checkout"""
    reservation_id: str
    payment_id: str
    checkout_url: str
    amount: Decimal
    currency: str
    expires_at: datetime

    @field_validator('reservation_id', 'payment_id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v


class CartSummary(BaseModel):
    """Resumen simple del carrito"""
    cart_id: Optional[str] = None
    items_count: int = 0
    tickets_count: int = 0
    total: Decimal = Decimal('0')

    @field_validator('cart_id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v
