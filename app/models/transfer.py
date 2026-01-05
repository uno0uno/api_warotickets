from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class TransferStatus(str, Enum):
    """Estados de transferencia"""
    PENDING = "pending"      # Esperando aceptacion
    ACCEPTED = "accepted"    # Aceptada por destinatario
    REJECTED = "rejected"    # Rechazada por destinatario
    CANCELLED = "cancelled"  # Cancelada por remitente
    EXPIRED = "expired"      # Expiro sin respuesta


class TransferInitiateRequest(BaseModel):
    """Request para iniciar transferencia"""
    reservation_unit_id: int = Field(..., description="ID del boleto a transferir")
    recipient_email: str = Field(..., description="Email del destinatario")
    message: Optional[str] = Field(None, max_length=500, description="Mensaje opcional")


class TransferAcceptRequest(BaseModel):
    """Request para aceptar transferencia"""
    transfer_token: str = Field(..., description="Token de transferencia")


class Transfer(BaseModel):
    """Modelo de transferencia"""
    id: int
    reservation_unit_id: int
    from_user_id: str
    to_user_id: Optional[str] = None
    to_email: str
    transfer_token: str
    status: TransferStatus
    message: Optional[str] = None
    initiated_at: datetime
    responded_at: Optional[datetime] = None
    expires_at: datetime

    # Info adicional
    from_user_name: Optional[str] = None
    from_user_email: Optional[str] = None
    to_user_name: Optional[str] = None

    # Info del boleto
    event_name: Optional[str] = None
    event_date: Optional[datetime] = None
    area_name: Optional[str] = None
    unit_display_name: Optional[str] = None

    class Config:
        from_attributes = True


class TransferSummary(BaseModel):
    """Resumen de transferencia"""
    id: int
    reservation_unit_id: int
    to_email: str
    status: str
    initiated_at: datetime
    event_name: Optional[str] = None
    unit_display_name: Optional[str] = None

    class Config:
        from_attributes = True


class TransferLogEntry(BaseModel):
    """Entrada en el log de transferencias"""
    id: int
    reservation_unit_id: int
    from_user_id: str
    to_user_id: str
    transfer_date: datetime
    transfer_reason: Optional[str] = None
    from_user_name: Optional[str] = None
    to_user_name: Optional[str] = None

    class Config:
        from_attributes = True


class PendingTransfer(BaseModel):
    """Transferencia pendiente para el destinatario"""
    id: int
    transfer_token: str
    from_user_name: str
    from_user_email: str
    event_name: str
    event_date: Optional[datetime] = None
    area_name: str
    unit_display_name: str
    message: Optional[str] = None
    initiated_at: datetime
    expires_at: datetime

    class Config:
        from_attributes = True


class TransferResult(BaseModel):
    """Resultado de operacion de transferencia"""
    success: bool
    message: str
    transfer_id: Optional[int] = None
    new_qr_code: Optional[str] = None
