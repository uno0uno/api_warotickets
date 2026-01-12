from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class AreaStatus(str, Enum):
    """Estados de un area"""
    AVAILABLE = "available"
    SOLD_OUT = "sold_out"
    DISABLED = "disabled"


class AreaBase(BaseModel):
    """Campos base de un area"""
    area_name: str = Field(..., min_length=1, max_length=255, description="Nombre del area/localidad")
    description: Optional[str] = Field(None, description="Descripcion del area")
    capacity: int = Field(..., gt=0, description="Capacidad total del area")
    price: Decimal = Field(..., ge=0, description="Precio base por unidad")
    currency: str = Field(default="COP", description="Moneda (COP, USD)")
    nomenclature_letter: Optional[str] = Field(None, max_length=10, description="Letra de nomenclatura (ej: A, B, VIP)")
    unit_capacity: Optional[int] = Field(None, description="Capacidad por unidad (para mesas/palcos)")
    service: Optional[float] = Field(None, ge=0, description="Cargo por servicio (porcentaje)")
    extra_attributes: Optional[dict] = Field(default_factory=dict, description="Atributos adicionales")


class AreaCreate(AreaBase):
    """Schema para crear un area - units se generan automaticamente basado en capacity"""
    pass


class AreaUpdate(BaseModel):
    """Schema para actualizar un area"""
    area_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    capacity: Optional[int] = Field(None, gt=0)
    price: Optional[Decimal] = Field(None, ge=0)
    currency: Optional[str] = None
    status: Optional[str] = None
    nomenclature_letter: Optional[str] = None
    unit_capacity: Optional[int] = None
    service: Optional[float] = None
    extra_attributes: Optional[dict] = None


class Area(AreaBase):
    """Schema completo de area"""
    id: int
    cluster_id: int
    status: str = "available"
    created_at: datetime
    updated_at: datetime

    # Campos calculados
    units_total: Optional[int] = None
    units_available: Optional[int] = None
    units_reserved: Optional[int] = None
    units_sold: Optional[int] = None

    class Config:
        from_attributes = True


class AreaSummary(BaseModel):
    """Schema resumido para listados"""
    id: int
    area_name: str
    description: Optional[str] = None
    capacity: int
    price: Decimal
    currency: str
    status: str
    nomenclature_letter: Optional[str] = None
    units_available: Optional[int] = None
    service: Optional[float] = None

    # Precio con etapa de venta aplicada
    current_price: Optional[Decimal] = None
    active_sale_stage: Optional[str] = None

    class Config:
        from_attributes = True


class AreaWithUnits(Area):
    """Schema de area con sus unidades"""
    units: List["Unit"] = []


class AreaAvailability(BaseModel):
    """Schema de disponibilidad de un area"""
    area_id: int
    area_name: str
    total_units: int
    available_units: int
    reserved_units: int
    sold_units: int
    base_price: Decimal
    current_price: Decimal  # Con sale_stage aplicado
    currency: str
    active_sale_stage: Optional[str] = None
    active_promotion: Optional[str] = None


class AreaBulkCreate(BaseModel):
    """Schema para crear multiples areas"""
    cluster_id: int
    areas: List[AreaCreate]


# Import para evitar circular dependency
from app.models.unit import Unit
AreaWithUnits.model_rebuild()
