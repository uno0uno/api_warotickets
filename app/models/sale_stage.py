from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from decimal import Decimal
from enum import Enum


class PriceAdjustmentType(str, Enum):
    """Tipo de ajuste de precio"""
    PERCENTAGE = "percentage"  # Porcentaje (+10 = +10%, -20 = -20%)
    FIXED = "fixed"            # Valor fijo (+5000 = +5000 COP)


class AreaSaleStageBase(BaseModel):
    """Campos base de etapa de venta para areas"""
    stage_name: str = Field(..., min_length=1, max_length=100, description="Nombre de la etapa (Early Bird, Preventa, etc)")
    description: Optional[str] = Field(None, description="Descripcion de la etapa")
    price_adjustment_type: PriceAdjustmentType = Field(..., description="Tipo de ajuste: percentage o fixed")
    price_adjustment_value: Decimal = Field(..., description="Valor del ajuste (negativo = descuento)")
    quantity_available: int = Field(..., ge=0, description="Cantidad de tickets disponibles en esta etapa")
    start_time: datetime = Field(..., description="Inicio de la etapa")
    end_time: Optional[datetime] = Field(None, description="Fin de la etapa (None = sin fin)")
    priority_order: int = Field(default=0, description="Orden de prioridad (menor = mayor prioridad)")


class AreaSaleStageCreate(AreaSaleStageBase):
    """Schema para crear etapa de venta"""
    area_id: int = Field(..., description="ID del area")


class AreaSaleStageUpdate(BaseModel):
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


class AreaSaleStage(AreaSaleStageBase):
    """Schema completo de etapa de venta"""
    id: str  # UUID
    area_id: int
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    # Campos calculados
    tickets_sold_in_stage: Optional[int] = None
    is_currently_active: Optional[bool] = None

    # Campos de contexto (opcionales, para respuestas enriquecidas)
    area_name: Optional[str] = None
    cluster_id: Optional[int] = None

    class Config:
        from_attributes = True


class AreaSaleStageSummary(BaseModel):
    """Schema resumido de etapa"""
    id: str
    area_id: int
    area_name: Optional[str] = None
    stage_name: str
    price_adjustment_type: str
    price_adjustment_value: Decimal
    quantity_available: int
    start_time: datetime
    end_time: Optional[datetime] = None
    is_active: bool
    is_currently_active: bool

    class Config:
        from_attributes = True


class ActiveAreaSaleStage(BaseModel):
    """Etapa de venta activa para un area"""
    stage_id: str
    stage_name: str
    base_price: Decimal
    adjusted_price: Decimal
    discount_percentage: Optional[Decimal] = None
    tickets_remaining: int
    ends_at: Optional[datetime] = None


# Aliases para compatibilidad (deprecados, usar Area* versions)
SaleStageBase = AreaSaleStageBase
SaleStageCreate = AreaSaleStageCreate
SaleStageUpdate = AreaSaleStageUpdate
SaleStage = AreaSaleStage
SaleStageSummary = AreaSaleStageSummary
ActiveSaleStage = ActiveAreaSaleStage
