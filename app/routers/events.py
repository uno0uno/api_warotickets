from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import datetime
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.core.middleware import require_valid_session
from app.models.event import (
    Event, EventSummary,
    EventImageCreate, EventImage, LegalInfoCreate, LegalInfo,
    EventCreateWithAreas, EventCreatedResponse,
    EventUpdateWithAreas, EventUpdatedResponse
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


@router.post("", response_model=EventCreatedResponse, status_code=201)
async def create_event(
    data: EventCreateWithAreas,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a new event, optionally with nested areas and auto-generated units.

    **Simple event (no areas):**
    ```json
    {
        "cluster_name": "My Event",
        "description": "Event description",
        "start_date": "2026-03-15T18:00:00",
        "cluster_type": "concert"
    }
    ```

    **Event with areas and units:**
    ```json
    {
        "cluster_name": "Rock Festival 2026",
        "description": "The best rock festival",
        "start_date": "2026-03-15T18:00:00",
        "cluster_type": "festival",
        "areas": [
            {
                "area_name": "VIP",
                "capacity": 100,
                "price": 500000,
                "nomenclature_letter": "V"
            },
            {
                "area_name": "General",
                "capacity": 1000,
                "price": 150000,
                "nomenclature_letter": "G"
            }
        ]
    }
    ```
    """
    result = await events_service.create_event_with_areas(user.user_id, user.tenant_id, data)
    return EventCreatedResponse(
        event=result["event"],
        areas_created=result["areas_created"],
        units_created=result["units_created"],
        message=f"Event created with {result['areas_created']} areas and {result['units_created']} units"
    )


@router.patch("/{event_id}", response_model=EventUpdatedResponse)
async def update_event(
    event_id: int,
    data: EventUpdateWithAreas,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update an existing event, optionally with area modifications.

    **Update event only:**
    ```json
    {
        "cluster_name": "Updated Event Name",
        "description": "New description"
    }
    ```

    **Update event and modify areas:**
    ```json
    {
        "cluster_name": "Updated Festival",
        "areas": [
            {"id": 60, "price": 600000},
            {"id": 61, "capacity": 1200},
            {"id": 62, "is_deleted": true},
            {"area_name": "New Section", "capacity": 50, "price": 80000}
        ]
    }
    ```

    **Business rules:**
    - Cannot decrease area capacity below sold/reserved units
    - Cannot delete areas with sold/reserved units
    - If capacity increases, new units are auto-generated
    """
    result = await events_service.update_event_with_areas(event_id, user.user_id, user.tenant_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Event not found")
    return EventUpdatedResponse(
        event=result["event"],
        areas_updated=result["areas_updated"],
        areas_created=result["areas_created"],
        areas_deleted=result["areas_deleted"],
        units_created=result["units_created"],
        message=f"Event updated: {result['areas_updated']} areas modified, {result['areas_created']} created, {result['areas_deleted']} deleted"
    )


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
