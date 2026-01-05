from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    """Tipos de eventos"""
    CONCERT = "concert"
    FESTIVAL = "festival"
    THEATER = "theater"
    SPORTS = "sports"
    CONFERENCE = "conference"
    PARTY = "party"
    OTHER = "other"


class EventStatus(str, Enum):
    """Estados de un evento"""
    DRAFT = "draft"
    PUBLISHED = "published"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


# Base model with common fields
class EventBase(BaseModel):
    cluster_name: str = Field(..., min_length=1, max_length=255, description="Nombre del evento")
    description: Optional[str] = Field(None, description="Descripcion del evento")
    start_date: Optional[datetime] = Field(None, description="Fecha y hora de inicio")
    end_date: Optional[datetime] = Field(None, description="Fecha y hora de fin")
    cluster_type: Optional[str] = Field(None, description="Tipo de evento")
    extra_attributes: Optional[dict] = Field(default_factory=dict, description="Atributos adicionales (JSON)")


class EventCreate(EventBase):
    """Schema para crear un evento"""
    slug_cluster: Optional[str] = Field(None, description="Slug unico del evento (se genera automaticamente si no se proporciona)")
    legal_info_id: Optional[int] = Field(None, description="ID de la info legal del organizador")


class EventUpdate(BaseModel):
    """Schema para actualizar un evento"""
    cluster_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    cluster_type: Optional[str] = None
    extra_attributes: Optional[dict] = None
    is_active: Optional[bool] = None
    shadowban: Optional[bool] = None
    legal_info_id: Optional[int] = None


class EventImage(BaseModel):
    """Schema para imagenes de evento"""
    id: int
    cluster_id: int
    image_id: str
    type_image: Optional[str] = None
    created_at: datetime
    image_url: Optional[str] = None


class EventImageCreate(BaseModel):
    """Schema para agregar imagen a evento"""
    image_id: str
    type_image: str = Field(..., description="Tipo: cover, banner, thumbnail, gallery")


class Event(EventBase):
    """Schema completo de evento"""
    id: int
    profile_id: str  # UUID del organizador (tenant)
    slug_cluster: str
    is_active: bool = True
    shadowban: bool = False
    legal_info_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    # Campos calculados/relacionados
    images: List[EventImage] = []
    total_capacity: Optional[int] = None
    tickets_sold: Optional[int] = None
    tickets_available: Optional[int] = None

    class Config:
        from_attributes = True


class EventSummary(BaseModel):
    """Schema resumido para listados"""
    id: int
    cluster_name: str
    slug_cluster: str
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    cluster_type: Optional[str] = None
    is_active: bool
    cover_image_url: Optional[str] = None
    total_capacity: Optional[int] = None
    tickets_available: Optional[int] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None

    class Config:
        from_attributes = True


class EventWithAreas(Event):
    """Schema de evento con sus areas incluidas"""
    areas: List[Any] = []  # Se resuelve como List[Area] en runtime


class EventPublic(BaseModel):
    """Schema publico de evento (sin datos sensibles)"""
    id: int
    cluster_name: str
    slug_cluster: str
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    cluster_type: Optional[str] = None
    cover_image_url: Optional[str] = None
    banner_image_url: Optional[str] = None
    extra_attributes: Optional[dict] = None

    class Config:
        from_attributes = True


class LegalInfo(BaseModel):
    """Schema para informacion legal del organizador"""
    id: int
    nit: Optional[str] = None
    legal_name: Optional[str] = None
    puleb_code: Optional[str] = None  # Registro PULEP
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None

    class Config:
        from_attributes = True


class LegalInfoCreate(BaseModel):
    """Schema para crear info legal"""
    nit: Optional[str] = None
    legal_name: Optional[str] = None
    puleb_code: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


# Nested creation schemas
class AreaCreateNested(BaseModel):
    """Area creation within event (no cluster_id needed)"""
    area_name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    capacity: int = Field(..., gt=0)
    price: float = Field(..., ge=0)
    currency: str = Field(default="COP")
    nomenclature_letter: Optional[str] = Field(None, max_length=10)
    unit_capacity: Optional[int] = None
    service: Optional[float] = Field(None, ge=0)
    extra_attributes: Optional[dict] = Field(default_factory=dict)
    auto_generate_units: bool = Field(default=True, description="Auto-generate units based on capacity")


class EventCreateWithAreas(EventBase):
    """Create event with nested areas in a single request"""
    slug_cluster: Optional[str] = None
    legal_info_id: Optional[int] = None
    areas: Optional[List[AreaCreateNested]] = Field(default=None, description="Areas to create with the event")


class EventCreatedResponse(BaseModel):
    """Response after creating event with areas"""
    event: Event
    areas_created: int = 0
    units_created: int = 0
    message: str = "Event created successfully"


class AreaUpdateNested(BaseModel):
    """Area update within event update"""
    id: Optional[int] = None  # If provided, updates existing area. If None, creates new area.
    area_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    capacity: Optional[int] = Field(None, gt=0)  # Can only increase, not decrease below sold
    price: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = None
    nomenclature_letter: Optional[str] = Field(None, max_length=10)
    unit_capacity: Optional[int] = None
    service: Optional[float] = Field(None, ge=0)
    extra_attributes: Optional[dict] = None
    is_deleted: bool = Field(default=False, description="Mark area for deletion (only if no sold units)")


class EventUpdateWithAreas(BaseModel):
    """Update event with nested area modifications"""
    cluster_name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    cluster_type: Optional[str] = None
    extra_attributes: Optional[dict] = None
    is_active: Optional[bool] = None
    legal_info_id: Optional[int] = None
    areas: Optional[List[AreaUpdateNested]] = Field(default=None, description="Areas to update/create/delete")


class EventUpdatedResponse(BaseModel):
    """Response after updating event with areas"""
    event: Event
    areas_updated: int = 0
    areas_created: int = 0
    areas_deleted: int = 0
    units_created: int = 0
    message: str = "Event updated successfully"
