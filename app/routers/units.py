from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.unit import Unit, UnitUpdate, UnitSummary, UnitsMapView
from app.services import units_service

router = APIRouter()


@router.get("/event/{cluster_id}/area/{area_id}", response_model=List[UnitSummary])
async def list_units_by_area(
    cluster_id: int,
    area_id: int,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List all units for an area within a specific event.
    """
    units = await units_service.get_units_by_area(
        cluster_id, area_id, user.user_id, user.tenant_id,
        status=status,
        limit=limit,
        offset=offset
    )
    return units


@router.get("/event/{cluster_id}/{unit_id}", response_model=Unit)
async def get_unit(
    cluster_id: int,
    unit_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get unit details by ID within a specific event.
    """
    unit = await units_service.get_unit_by_id(cluster_id, unit_id, user.user_id, user.tenant_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


@router.patch("/event/{cluster_id}/{unit_id}", response_model=Unit)
async def update_unit_status(
    cluster_id: int,
    unit_id: int,
    data: UnitUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update unit status within a specific event.
    """
    unit = await units_service.update_unit_status(cluster_id, unit_id, user.user_id, user.tenant_id, data)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


@router.get("/event/{cluster_id}/area/{area_id}/available", response_model=List[UnitSummary])
async def get_available_units(
    cluster_id: int,
    area_id: int,
    quantity: int = Query(1, ge=1, le=100, description="Number of units needed")
):
    """
    Get available units for purchase (public endpoint).
    """
    units = await units_service.get_available_units(cluster_id, area_id, quantity)
    return units


@router.get("/event/{cluster_id}/area/{area_id}/map", response_model=UnitsMapView)
async def get_units_map(
    cluster_id: int,
    area_id: int
):
    """
    Get units map view for seat selection (public endpoint).
    """
    map_view = await units_service.get_units_map(cluster_id, area_id)
    if not map_view:
        raise HTTPException(status_code=404, detail="Area not found")
    return map_view
