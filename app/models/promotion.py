from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class PricingType(str, Enum):
    """Tipo de precio/descuento para la promocion"""
    PERCENTAGE = "percentage"        # Porcentaje de descuento sobre precio normal
    FIXED_DISCOUNT = "fixed_discount"  # Monto fijo de descuento
    FIXED_PRICE = "fixed_price"      # Precio fijo por el combo/paquete completo


class PromotionItem(BaseModel):
    """Item de una promocion: area + cantidad de boletas"""
    area_id: int = Field(..., description="ID del area")
    quantity: int = Field(..., ge=1, description="Cantidad de boletas de esta area")


class PromotionItemResponse(PromotionItem):
    """Item de promocion con info del area"""
    area_name: Optional[str] = None
    area_price: Optional[Decimal] = None  # Precio base del area


class PromotionBase(BaseModel):
    """Campos base de promocion (nivel evento/cluster) - Sistema de combos/paquetes"""
    promotion_name: str = Field(..., min_length=1, max_length=100, description="Nombre de la promocion")
    promotion_code: str = Field(..., min_length=1, max_length=50, description="Codigo promocional OBLIGATORIO (ej: 2X1VIP, PACKFAMILIA)")
    description: Optional[str] = Field(None, description="Descripcion de la promocion")
    pricing_type: PricingType = Field(..., description="Tipo: percentage, fixed_discount o fixed_price")
    pricing_value: Decimal = Field(..., gt=0, description="Valor: porcentaje, monto descuento o precio fijo del paquete")
    max_discount_amount: Optional[Decimal] = Field(None, description="Descuento maximo (solo para percentage)")
    quantity_available: Optional[int] = Field(None, ge=0, description="Cantidad de usos disponibles (None = ilimitado)")
    start_time: datetime = Field(..., description="Inicio de vigencia")
    end_time: Optional[datetime] = Field(None, description="Fin de vigencia (None = sin fin)")
    priority_order: int = Field(default=0, description="Orden de prioridad (menor = mayor prioridad)")


class PromotionCreate(PromotionBase):
    """Schema para crear promocion con items (areas + cantidades)"""
    items: List[PromotionItem] = Field(..., min_length=1, description="Items del combo: areas con sus cantidades")


class PromotionUpdate(BaseModel):
    """Schema para actualizar promocion"""
    promotion_name: Optional[str] = None
    promotion_code: Optional[str] = None
    description: Optional[str] = None
    pricing_type: Optional[PricingType] = None
    pricing_value: Optional[Decimal] = None
    max_discount_amount: Optional[Decimal] = None
    quantity_available: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_active: Optional[bool] = None
    priority_order: Optional[int] = None
    items: Optional[List[PromotionItem]] = Field(None, description="Actualizar items del combo (reemplaza los existentes)")


class Promotion(PromotionBase):
    """Schema completo de promocion"""
    id: str  # UUID
    cluster_id: int
    uses_count: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    # Campos calculados
    is_currently_valid: Optional[bool] = None
    uses_remaining: Optional[int] = None
    total_tickets: Optional[int] = None  # Total de boletas en el combo
    original_price: Optional[Decimal] = None  # Precio original sin descuento

    # Items del combo
    items: List[PromotionItemResponse] = []

    class Config:
        from_attributes = True


class PromotionSummary(BaseModel):
    """Schema resumido de promocion para listados"""
    id: str
    cluster_id: int
    promotion_name: str
    promotion_code: str
    pricing_type: str
    pricing_value: Decimal
    quantity_available: Optional[int] = None
    uses_count: int
    start_time: datetime
    end_time: Optional[datetime] = None
    is_active: bool
    is_currently_valid: bool
    priority_order: int
    total_tickets: int = 0  # Total de boletas en el combo
    items_count: int = 0  # Cantidad de areas diferentes
    items: List[PromotionItemResponse] = []

    class Config:
        from_attributes = True


class PromotionValidation(BaseModel):
    """Resultado de validacion de codigo promocional"""
    is_valid: bool
    promotion_id: Optional[str] = None
    promotion_name: Optional[str] = None
    pricing_type: Optional[str] = None
    pricing_value: Optional[Decimal] = None
    max_discount_amount: Optional[Decimal] = None
    error_message: Optional[str] = None
    items: List[PromotionItemResponse] = []  # Areas y cantidades del combo


class ValidatePromotionRequest(BaseModel):
    """Request para validar codigo promocional"""
    promotion_code: str = Field(..., min_length=1, max_length=50)


class CalculatePriceRequest(BaseModel):
    """Request para calcular precio con promocion"""
    promotion_code: Optional[str] = Field(None, max_length=50)


class CalculatedPrice(BaseModel):
    """Precio calculado con descuentos"""
    items: List[PromotionItemResponse] = []  # Boletas incluidas
    original_price: Decimal  # Precio original (suma de areas * cantidades)
    discount_amount: Decimal = Decimal("0")  # Descuento aplicado
    service_fee: Decimal = Decimal("0")
    final_price: Decimal
    currency: str = "COP"
    applied_promotion: Optional[str] = None


class PromotionPublic(BaseModel):
    """Schema publico de promocion para compradores"""
    id: str
    promotion_name: str
    promotion_code: str
    description: Optional[str] = None
    pricing_type: str
    pricing_value: Decimal
    total_tickets: int = 0
    original_price: Optional[Decimal] = None
    final_price: Optional[Decimal] = None
    savings: Optional[Decimal] = None
    items: List[PromotionItemResponse] = []

    class Config:
        from_attributes = True


# Deprecated aliases for backwards compatibility
DiscountType = PricingType
