from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class ValidationResult(str, Enum):
    """Resultado de validacion de QR"""
    VALID = "valid"
    INVALID_SIGNATURE = "invalid_signature"
    TICKET_NOT_FOUND = "ticket_not_found"
    ALREADY_USED = "already_used"
    WRONG_EVENT = "wrong_event"
    EVENT_NOT_STARTED = "event_not_started"
    EVENT_ENDED = "event_ended"
    TICKET_TRANSFERRED = "ticket_transferred"
    TICKET_CANCELLED = "ticket_cancelled"


class QRCodeResponse(BaseModel):
    """Respuesta con codigo QR"""
    reservation_unit_id: int
    qr_code_base64: str
    qr_code_data_url: str
    generated_at: datetime


class QRValidationRequest(BaseModel):
    """Request para validar QR"""
    qr_data: str = Field(..., description="Datos escaneados del QR")
    event_slug: str = Field(..., description="Slug del evento actual")


class QRValidationResponse(BaseModel):
    """Respuesta de validacion de QR"""
    is_valid: bool
    result: ValidationResult
    message: str

    # Info del ticket (solo si valido)
    reservation_unit_id: Optional[int] = None
    unit_id: Optional[int] = None
    unit_display_name: Optional[str] = None
    area_name: Optional[str] = None
    owner_name: Optional[str] = None
    owner_email: Optional[str] = None

    # Info del evento
    event_name: Optional[str] = None
    event_date: Optional[datetime] = None


class TicketCheckIn(BaseModel):
    """Registro de check-in"""
    reservation_unit_id: int
    checked_in_at: datetime
    checked_in_by: str  # User ID del staff que valido
    gate: Optional[str] = None  # Puerta de entrada


class CheckInStats(BaseModel):
    """Estadisticas de check-in"""
    event_id: int
    event_name: str
    total_tickets: int
    checked_in: int
    pending: int
    check_in_percentage: float
    last_check_in: Optional[datetime] = None
