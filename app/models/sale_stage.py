from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class PriceAdjustmentType(str, Enum):
    """Tipo de ajuste de precio"""
    PERCENTAGE = "percentage"  # Porcentaje (+10 = +10%, -20 = -20%)
    FIXED = "fixed"            # Valor fijo (+5000 = +5000 COP)
    FIXED_PRICE = "fixed_price"  # Precio fijo total del paquete


class SaleStageAreaItem(BaseModel):
    """Item de area con cantidad para etapa de venta (bundle)"""
    area_id: int = Field(..., description="ID del area")
    quantity: int = Field(default=1, ge=1, description="Cantidad de boletas de esta area")


class SaleStageBase(BaseModel):
    """Campos base de etapa de venta (nivel evento/cluster)"""
    stage_name: str = Field(..., min_length=1, max_length=100, description="Nombre de la etapa (Early Bird, Preventa, etc)")
    description: Optional[str] = Field(None, description="Descripcion de la etapa")
    price_adjustment_type: PriceAdjustmentType = Field(..., description="Tipo de ajuste: percentage o fixed")
    price_adjustment_value: Decimal = Field(..., description="Valor del ajuste (negativo = descuento)")
    quantity_available: int = Field(..., ge=0, description="Cantidad total de tickets disponibles en esta etapa")
    start_time: datetime = Field(..., description="Inicio de la etapa")
    end_time: Optional[datetime] = Field(None, description="Fin de la etapa (None = sin fin)")
    priority_order: int = Field(default=0, description="Orden de prioridad (menor = mayor prioridad)")


class SaleStageCreate(SaleStageBase):
    """Schema para crear etapa de venta - aplica a multiples areas"""
    area_ids: Optional[List[int]] = Field(None, description="IDs de las areas (cantidad=1 por defecto)")
    area_items: Optional[List[SaleStageAreaItem]] = Field(None, description="Areas con cantidades especificas (bundle)")


class SaleStageUpdate(BaseModel):
    """Schema para actualizar etapa de venta"""
    stage_name: Optional[str] = None
    description: Optional[str] = None
    price_adjustment_type: Optional[PriceAdjustmentType] = None
    price_adjustment_value: Optional[Decimal] = None
    quantity_available: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_active: Optional[bool] = None
    priority_order: Optional[int] = None
    area_ids: Optional[List[int]] = Field(None, description="Actualizar areas (cantidad=1 por defecto)")
    area_items: Optional[List[SaleStageAreaItem]] = Field(None, description="Actualizar areas con cantidades (bundle)")


class SaleStage(SaleStageBase):
    """Schema completo de etapa de venta"""
    id: str  # UUID
    cluster_id: int
    quantity_sold: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    # Campos calculados
    is_currently_active: Optional[bool] = None
    quantity_remaining: Optional[int] = None

    # Areas vinculadas con cantidades
    area_ids: List[int] = []
    areas: List[dict] = []  # [{id, area_name, quantity}]

    # Info de bundle
    is_bundle: bool = False  # True si tiene cantidades > 1
    total_tickets: int = 0  # Total de boletas en el bundle

    class Config:
        from_attributes = True


class SaleStageSummary(BaseModel):
    """Schema resumido de etapa para listados"""
    id: str
    cluster_id: int
    stage_name: str
    price_adjustment_type: str
    price_adjustment_value: Decimal
    quantity_available: int
    quantity_sold: int
    start_time: datetime
    end_time: Optional[datetime] = None
    is_active: bool
    is_currently_active: bool
    priority_order: int
    area_count: int = 0
    areas: List[dict] = []  # [{id, area_name, quantity}]
    is_bundle: bool = False
    total_tickets: int = 0

    class Config:
        from_attributes = True


class ActiveSaleStage(BaseModel):
    """Etapa de venta activa para un area (usado en pricing)"""
    stage_id: str
    stage_name: str
    base_price: Decimal
    adjusted_price: Decimal
    discount_percentage: Optional[Decimal] = None
    tickets_remaining: int
    ends_at: Optional[datetime] = None


# Aliases para compatibilidad con codigo existente (deprecados)
AreaSaleStageBase = SaleStageBase
AreaSaleStageCreate = SaleStageCreate
AreaSaleStageUpdate = SaleStageUpdate
AreaSaleStage = SaleStage
AreaSaleStageSummary = SaleStageSummary
ActiveAreaSaleStage = ActiveSaleStage
