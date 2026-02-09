"""
Invitation models for tenant member invitations
"""
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class InvitationCreate(BaseModel):
    """Request to send an invitation"""
    name: str
    email: EmailStr
    phone: Optional[str] = None
    role: str = "admin"


class InvitationResponse(BaseModel):
    """Invitation response"""
    id: str
    tenant_id: str
    email: str
    role: str
    invited_by: Optional[str]
    status: str
    expires_at: datetime
    accepted_at: Optional[datetime]
    created_at: Optional[datetime]


class InvitationAccept(BaseModel):
    """Accept invitation request"""
    token: str
