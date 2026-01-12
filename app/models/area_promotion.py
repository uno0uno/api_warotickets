from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from decimal import Decimal
from enum import Enum


class DiscountType(str, Enum):
    """Tipo de descuento"""
    PERCENTAGE = "percentage"  # Porcentaje de descuento
    FIXED = "fixed"            # Monto fijo de descuento


class AreaPromotionBase(BaseModel):
    """Campos base de promocion para areas"""
    promotion_name: str = Field(..., min_length=1, max_length=100, description="Nombre de la promocion")
    promotion_code: Optional[str] = Field(None, max_length=50, description="Codigo promocional (ej: DESCUENTO20)")
    description: Optional[str] = Field(None, description="Descripcion de la promocion")
    discount_type: DiscountType = Field(..., description="Tipo de descuento: percentage o fixed")
    discount_value: Decimal = Field(..., gt=0, description="Valor del descuento")
    max_discount_amount: Optional[Decimal] = Field(None, description="Descuento maximo (para porcentajes)")
    min_quantity: int = Field(default=1, ge=1, description="Cantidad minima de tickets para aplicar")
    quantity_available: Optional[int] = Field(None, ge=0, description="Cantidad de usos disponibles (None = ilimitado)")
    start_time: datetime = Field(..., description="Inicio de vigencia")
    end_time: Optional[datetime] = Field(None, description="Fin de vigencia (None = sin fin)")
    priority_order: int = Field(default=0, description="Orden de prioridad (menor = mayor prioridad)")


class AreaPromotionCreate(AreaPromotionBase):
    """Schema para crear promocion"""
    area_id: int = Field(..., description="ID del area")


class AreaPromotionUpdate(BaseModel):
    """Schema para actualizar promocion"""
    promotion_name: Optional[str] = None
    promotion_code: Optional[str] = None
    description: Optional[str] = None
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[Decimal] = None
    max_discount_amount: Optional[Decimal] = None
    min_quantity: Optional[int] = None
    quantity_available: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_active: Optional[bool] = None
    priority_order: Optional[int] = None


class AreaPromotion(AreaPromotionBase):
    """Schema completo de promocion"""
    id: str  # UUID
    area_id: int
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    # Campos calculados
    is_currently_valid: Optional[bool] = None

    # Campos de contexto (opcionales, para respuestas enriquecidas)
    area_name: Optional[str] = None
    cluster_id: Optional[int] = None

    class Config:
        from_attributes = True


class AreaPromotionSummary(BaseModel):
    """Schema resumido de promocion"""
    id: str
    area_id: int
    area_name: Optional[str] = None
    promotion_name: str
    promotion_code: Optional[str] = None
    discount_type: str
    discount_value: Decimal
    start_time: datetime
    end_time: Optional[datetime] = None
    is_active: bool
    is_currently_valid: bool

    class Config:
        from_attributes = True


class PromotionValidation(BaseModel):
    """Resultado de validacion de codigo promocional"""
    is_valid: bool
    promotion_id: Optional[str] = None
    promotion_name: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[Decimal] = None
    max_discount_amount: Optional[Decimal] = None
    error_message: Optional[str] = None


class ValidatePromotionRequest(BaseModel):
    """Request para validar codigo promocional"""
    promotion_code: str = Field(..., min_length=1, max_length=50)
    area_id: int = Field(..., description="ID del area")
    quantity: int = Field(default=1, ge=1)


class CalculatePriceRequest(BaseModel):
    """Request para calcular precio"""
    area_id: int = Field(..., description="ID del area")
    quantity: int = Field(default=1, ge=1)
    promotion_code: Optional[str] = Field(None, max_length=50)


class CalculatedPrice(BaseModel):
    """Precio calculado con descuentos"""
    base_price: Decimal
    sale_stage_discount: Decimal = Decimal("0")
    promotion_discount: Decimal = Decimal("0")
    service_fee: Decimal = Decimal("0")
    final_price: Decimal
    currency: str = "COP"
    applied_sale_stage: Optional[str] = None
    applied_promotion: Optional[str] = None
