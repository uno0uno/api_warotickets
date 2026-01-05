from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class UnitStatus(str, Enum):
    """Estados de una unidad/boleto"""
    AVAILABLE = "available"
    RESERVED = "reserved"  # Reservado temporalmente (en proceso de compra)
    SOLD = "sold"          # Vendido y pagado
    BLOCKED = "blocked"    # Bloqueado por admin
    DISABLED = "disabled"  # Deshabilitado


class UnitBase(BaseModel):
    """Campos base de una unidad"""
    nomenclature_letter_area: Optional[str] = Field(None, max_length=10, description="Letra del area")
    nomenclature_number_area: Optional[int] = Field(None, description="Numero del area")
    nomenclature_number_unit: Optional[int] = Field(None, description="Numero de la unidad")
    extra_attributes: Optional[dict] = Field(default_factory=dict, description="Atributos adicionales (fila, columna, etc)")


class UnitCreate(UnitBase):
    """Schema para crear una unidad"""
    area_id: int = Field(..., description="ID del area a la que pertenece")
    status: str = Field(default="available", description="Estado inicial")


class UnitUpdate(BaseModel):
    """Schema para actualizar una unidad"""
    status: Optional[str] = None
    nomenclature_letter_area: Optional[str] = None
    nomenclature_number_area: Optional[int] = None
    nomenclature_number_unit: Optional[int] = None
    extra_attributes: Optional[dict] = None


class Unit(UnitBase):
    """Schema completo de unidad"""
    id: int
    area_id: int
    status: str = "available"
    created_at: datetime
    updated_at: datetime

    # Campos calculados/relacionados
    display_name: Optional[str] = None  # Ej: "A-12" o "Mesa 5"

    class Config:
        from_attributes = True


class UnitSummary(BaseModel):
    """Schema resumido de unidad"""
    id: int
    area_id: int
    status: str
    display_name: Optional[str] = None
    nomenclature_letter_area: Optional[str] = None
    nomenclature_number_unit: Optional[int] = None

    class Config:
        from_attributes = True


class UnitBulkCreate(BaseModel):
    """Schema para crear multiples unidades"""
    area_id: int = Field(..., description="ID del area")
    quantity: int = Field(..., gt=0, le=10000, description="Cantidad de unidades a crear")
    nomenclature_prefix: Optional[str] = Field(None, description="Prefijo para nomenclatura (ej: 'A')")
    start_number: int = Field(default=1, description="Numero inicial")
    status: str = Field(default="available", description="Estado inicial de todas las unidades")


class UnitBulkUpdate(BaseModel):
    """Schema para actualizar multiples unidades"""
    unit_ids: List[int] = Field(..., description="IDs de las unidades a actualizar")
    status: Optional[str] = None
    extra_attributes: Optional[dict] = None


class UnitBulkResponse(BaseModel):
    """Respuesta de operacion bulk"""
    total_created: int
    units: List[UnitSummary]


class UnitAvailabilityQuery(BaseModel):
    """Query para buscar unidades disponibles"""
    area_id: Optional[int] = None
    cluster_id: Optional[int] = None
    status: Optional[str] = "available"
    quantity: Optional[int] = Field(None, gt=0, description="Cantidad requerida")


class UnitSelection(BaseModel):
    """Schema para seleccion de unidades (proceso de compra)"""
    unit_ids: List[int] = Field(..., min_length=1, description="IDs de unidades seleccionadas")


class UnitWithArea(Unit):
    """Unidad con info del area"""
    area_name: Optional[str] = None
    area_price: Optional[float] = None
    area_currency: Optional[str] = None


class UnitsMapView(BaseModel):
    """Vista de mapa de unidades para un area"""
    area_id: int
    area_name: str
    total_units: int
    units: List[UnitSummary]
    layout: Optional[dict] = None  # Para renderizar mapa de asientos
