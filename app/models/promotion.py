from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class DiscountType(str, Enum):
    """Tipo de descuento"""
    PERCENTAGE = "percentage"  # Porcentaje de descuento
    FIXED = "fixed"            # Monto fijo de descuento


class AppliesTo(str, Enum):
    """A que aplica la promocion"""
    ALL = "all"           # Todos los productos/areas
    CLUSTER = "cluster"   # Evento especifico
    AREA = "area"         # Area especifica
    PRODUCT = "product"   # Producto especifico


class PromotionBase(BaseModel):
    """Campos base de promocion"""
    promotion_name: str = Field(..., min_length=1, max_length=100, description="Nombre de la promocion")
    promotion_code: Optional[str] = Field(None, max_length=50, description="Codigo promocional (ej: DESCUENTO20)")
    description: Optional[str] = Field(None, description="Descripcion")
    discount_type: DiscountType = Field(..., description="Tipo: percentage o fixed")
    discount_value: Decimal = Field(..., gt=0, description="Valor del descuento")
    applies_to: AppliesTo = Field(default=AppliesTo.ALL, description="A que aplica")
    min_quantity: int = Field(default=1, ge=1, description="Cantidad minima para aplicar")
    max_discount_amount: Optional[Decimal] = Field(None, description="Descuento maximo (para porcentajes)")
    start_date: datetime = Field(..., description="Inicio de vigencia")
    end_date: datetime = Field(..., description="Fin de vigencia")


class PromotionCreate(PromotionBase):
    """Schema para crear promocion"""
    target_cluster_id: Optional[int] = Field(None, description="Evento especifico")
    target_area_id: Optional[int] = Field(None, description="Area especifica")
    target_product_id: Optional[str] = Field(None, description="Producto especifico")
    target_product_variant_id: Optional[str] = Field(None, description="Variante especifica")
    max_uses: Optional[int] = Field(None, description="Usos maximos totales")
    max_uses_per_user: Optional[int] = Field(None, description="Usos maximos por usuario")


class PromotionUpdate(BaseModel):
    """Schema para actualizar promocion"""
    promotion_name: Optional[str] = None
    promotion_code: Optional[str] = None
    description: Optional[str] = None
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[Decimal] = None
    applies_to: Optional[AppliesTo] = None
    min_quantity: Optional[int] = None
    max_discount_amount: Optional[Decimal] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None
    target_cluster_id: Optional[int] = None
    target_area_id: Optional[int] = None


class Promotion(PromotionBase):
    """Schema completo de promocion"""
    id: str  # UUID
    target_cluster_id: Optional[int] = None
    target_area_id: Optional[int] = None
    target_product_id: Optional[str] = None
    target_product_variant_id: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    # Campos calculados
    times_used: Optional[int] = None
    is_currently_valid: Optional[bool] = None

    class Config:
        from_attributes = True


class PromotionSummary(BaseModel):
    """Schema resumido"""
    id: str
    promotion_name: str
    promotion_code: Optional[str] = None
    discount_type: str
    discount_value: Decimal
    start_date: datetime
    end_date: datetime
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


class ApplyPromotionRequest(BaseModel):
    """Request para aplicar codigo promocional"""
    promotion_code: str = Field(..., min_length=1, max_length=50)
    area_id: Optional[int] = None
    cluster_id: Optional[int] = None
    quantity: int = Field(default=1, ge=1)


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
