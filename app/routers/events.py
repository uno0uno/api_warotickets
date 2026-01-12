from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import datetime
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.event import (
    Event, EventCreate, EventUpdate, EventSummary,
    EventImageCreate, EventImage, LegalInfoCreate, LegalInfo
)
from app.services import events_service

router = APIRouter()


@router.get("", response_model=List[EventSummary])
async def list_events(
    user: AuthenticatedUser = Depends(get_authenticated_user),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    List all events for the current user/organizer within their tenant.
    """
    events = await events_service.get_events(
        profile_id=user.user_id,
        tenant_id=user.tenant_id,
        is_active=is_active,
        limit=limit,
        offset=offset
    )
    return events


@router.get("/{event_id}", response_model=Event)
async def get_event(
    event_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get event details by ID.
    """
    event = await events_service.get_event_by_id(event_id, user.user_id, user.tenant_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("", response_model=Event, status_code=201)
async def create_event(
    data: EventCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a new event.

    Areas should be created separately using POST /areas/event/{cluster_id}
    """
    event = await events_service.create_event(user.user_id, user.tenant_id, data)
    return event


@router.patch("/{event_id}", response_model=Event)
async def update_event(
    event_id: int,
    data: EventUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update an existing event.

    Only updates event information. Areas should be managed separately via /areas endpoints.
    """
    event = await events_service.update_event(event_id, user.user_id, user.tenant_id, data)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Soft delete an event (sets is_active = false).
    """
    deleted = await events_service.delete_event(event_id, user.user_id, user.tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Event not found")


@router.post("/{event_id}/images", response_model=EventImage, status_code=201)
async def add_event_image(
    event_id: int,
    data: EventImageCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Add an image to an event.
    """
    image = await events_service.add_event_image(event_id, user.user_id, user.tenant_id, data)
    if not image:
        raise HTTPException(status_code=404, detail="Event not found")
    return image


@router.delete("/{event_id}/images/{image_id}", status_code=204)
async def remove_event_image(
    event_id: int,
    image_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Remove an image from an event.
    """
    deleted = await events_service.remove_event_image(event_id, user.user_id, user.tenant_id, image_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Event or image not found")


@router.post("/legal-info", response_model=LegalInfo, status_code=201)
async def create_legal_info(
    data: LegalInfoCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create legal info for event organizer (PULEP registration, etc).
    """
    legal_info = await events_service.create_legal_info(data)
    return legal_info
