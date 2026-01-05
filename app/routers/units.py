from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.unit import (
    Unit, UnitCreate, UnitUpdate, UnitSummary,
    UnitBulkCreate, UnitBulkUpdate, UnitBulkResponse,
    UnitsMapView
)
from app.services import units_service

router = APIRouter()


@router.get("/area/{area_id}", response_model=List[UnitSummary])
async def list_units_by_area(
    area_id: int,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List all units for an area.
    """
    units = await units_service.get_units_by_area(
        area_id, user.user_id,
        status=status,
        limit=limit,
        offset=offset
    )
    return units


@router.get("/{unit_id}", response_model=Unit)
async def get_unit(
    unit_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get unit details by ID.
    """
    unit = await units_service.get_unit_by_id(unit_id, user.user_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


@router.post("", response_model=Unit, status_code=201)
async def create_unit(
    data: UnitCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a single unit.
    """
    unit = await units_service.create_unit(user.user_id, data)
    return unit


@router.post("/bulk", response_model=UnitBulkResponse, status_code=201)
async def create_units_bulk(
    data: UnitBulkCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create multiple units at once.
    """
    result = await units_service.create_units_bulk(user.user_id, data)
    return result


@router.patch("/{unit_id}", response_model=Unit)
async def update_unit(
    unit_id: int,
    data: UnitUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update a unit.
    """
    unit = await units_service.update_unit(unit_id, user.user_id, data)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


@router.patch("/bulk", response_model=dict)
async def update_units_bulk(
    data: UnitBulkUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update multiple units at once.
    """
    count = await units_service.update_units_bulk(user.user_id, data)
    return {"updated_count": count}


@router.delete("/{unit_id}", status_code=204)
async def delete_unit(
    unit_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Delete a unit (only if available or blocked).
    """
    deleted = await units_service.delete_unit(unit_id, user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Unit not found")


@router.get("/area/{area_id}/available", response_model=List[UnitSummary])
async def get_available_units(
    area_id: int,
    quantity: int = Query(1, ge=1, le=100, description="Number of units needed")
):
    """
    Get available units for purchase (public endpoint).
    """
    units = await units_service.get_available_units(area_id, quantity)
    return units


@router.get("/area/{area_id}/map", response_model=UnitsMapView)
async def get_units_map(
    area_id: int
):
    """
    Get units map view for seat selection (public endpoint).
    """
    map_view = await units_service.get_units_map(area_id)
    if not map_view:
        raise HTTPException(status_code=404, detail="Area not found")
    return map_view
