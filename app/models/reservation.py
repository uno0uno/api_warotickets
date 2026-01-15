from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional, List, Union
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


class ReservationStatus(str, Enum):
    """Estados de una reservacion"""
    PENDING = "pending"       # Creada, esperando pago
    ACTIVE = "active"         # Pagada y activa
    COMPLETED = "completed"   # Evento terminado
    CANCELLED = "cancelled"   # Cancelada
    EXPIRED = "expired"       # Expiro sin pago


class ReservationUnitStatus(str, Enum):
    """Estados de una unidad reservada"""
    RESERVED = "reserved"       # Reservada (pendiente pago)
    CONFIRMED = "confirmed"     # Confirmada (pagada)
    USED = "used"              # Usada (ingreso al evento)
    TRANSFERRED = "transferred" # Transferida a otro usuario
    CANCELLED = "cancelled"     # Cancelada


class ReservationBase(BaseModel):
    """Campos base de reservacion"""
    start_date: datetime = Field(..., description="Fecha del evento")
    end_date: datetime = Field(..., description="Fecha fin del evento")
    extra_attributes: Optional[dict] = Field(default_factory=dict)


class ReservationCreate(BaseModel):
    """Schema para crear reservacion"""
    cluster_id: int = Field(..., description="ID del evento")
    unit_ids: List[int] = Field(..., min_length=1, max_length=20, description="IDs de unidades a reservar")
    promotion_code: Optional[str] = Field(None, description="Codigo promocional")
    email: EmailStr = Field(..., description="Correo electronico del cliente")


class ReservationUpdate(BaseModel):
    """Schema para actualizar reservacion"""
    status: Optional[str] = None
    extra_attributes: Optional[dict] = None


class ReservationUnit(BaseModel):
    """Unidad dentro de una reservacion"""
    id: int
    reservation_id: str
    unit_id: int
    status: str
    original_user_id: str
    transfer_date: Optional[datetime] = None
    applied_sale_stage_id: Optional[str] = None
    applied_promotion_id: Optional[str] = None
    updated_at: datetime

    # Info de la unidad
    unit_display_name: Optional[str] = None
    area_name: Optional[str] = None
    area_id: Optional[int] = None

    # Precios
    base_price: Optional[Decimal] = None
    final_price: Optional[Decimal] = None

    @field_validator('reservation_id', 'original_user_id', 'applied_sale_stage_id', 'applied_promotion_id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class Reservation(ReservationBase):
    """Schema completo de reservacion"""
    id: str  # UUID
    user_id: str
    reservation_date: datetime
    status: str = "pending"
    updated_at: datetime

    # Info del evento
    cluster_id: Optional[int] = None
    cluster_name: Optional[str] = None
    cluster_slug: Optional[str] = None

    # Unidades reservadas
    units: List[ReservationUnit] = []

    # Totales
    total_units: int = 0
    subtotal: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    service_fee: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    currency: str = "COP"

    @field_validator('id', 'user_id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class ReservationSummary(BaseModel):
    """Schema resumido de reservacion"""
    id: str
    user_id: str
    cluster_name: Optional[str] = None
    start_date: datetime
    status: str
    total_units: int
    total: Decimal
    currency: str
    reservation_date: datetime

    @field_validator('id', 'user_id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class ReservationWithPayment(Reservation):
    """Reservacion con info de pago"""
    payment_id: Optional[int] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    payment_date: Optional[datetime] = None


class CreateReservationResponse(BaseModel):
    """Respuesta al crear reservacion"""
    reservation: Reservation
    expires_at: datetime  # Tiempo limite para pagar
    payment_url: Optional[str] = None  # URL de pasarela de pago


class ReservationTimeout(BaseModel):
    """Info de timeout de reservacion"""
    reservation_id: str
    created_at: datetime
    expires_at: datetime
    seconds_remaining: int
    is_expired: bool

    @field_validator('reservation_id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v


class MyTicket(BaseModel):
    """Ticket del usuario"""
    reservation_unit_id: int
    reservation_id: str
    unit_id: int
    unit_display_name: str
    area_name: str
    event_name: str
    event_slug: str
    event_date: datetime
    status: str
    qr_code: Optional[str] = None  # Unique token for validation
    qr_data: Optional[dict] = None  # Full QR data JSON
    qr_code_url: Optional[str] = None  # URL to QR image (generated on demand)
    can_transfer: bool = True

    @field_validator('reservation_id', mode='before')
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True
