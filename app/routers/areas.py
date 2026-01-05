from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.area import (
    Area, AreaCreate, AreaUpdate, AreaSummary, AreaAvailability
)
from app.services import areas_service

router = APIRouter()


@router.get("/event/{cluster_id}", response_model=List[AreaSummary])
async def list_areas_by_event(
    cluster_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List all areas for an event.
    """
    areas = await areas_service.get_areas_by_event(cluster_id, user.user_id)
    return areas


@router.get("/{area_id}", response_model=Area)
async def get_area(
    area_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get area details by ID.
    """
    area = await areas_service.get_area_by_id(area_id, user.user_id)
    if not area:
        raise HTTPException(status_code=404, detail="Area not found")
    return area


@router.post("", response_model=Area, status_code=201)
async def create_area(
    data: AreaCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a new area for an event.
    If auto_generate_units is true, units will be created automatically.
    """
    area = await areas_service.create_area(user.user_id, data)
    return area


@router.patch("/{area_id}", response_model=Area)
async def update_area(
    area_id: int,
    data: AreaUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update an existing area.
    """
    area = await areas_service.update_area(area_id, user.user_id, data)
    if not area:
        raise HTTPException(status_code=404, detail="Area not found")
    return area


@router.delete("/{area_id}", status_code=204)
async def delete_area(
    area_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Delete an area (only if no tickets have been sold).
    """
    deleted = await areas_service.delete_area(area_id, user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Area not found")


@router.get("/{area_id}/availability", response_model=AreaAvailability)
async def get_area_availability(
    area_id: int
):
    """
    Get availability info for an area (public endpoint).
    Includes current price with active sale stage.
    """
    availability = await areas_service.get_area_availability(area_id)
    if not availability:
        raise HTTPException(status_code=404, detail="Area not found or not available")
    return availability
