from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.sale_stage import (
    AreaSaleStage, AreaSaleStageCreate, AreaSaleStageUpdate, AreaSaleStageSummary
)
from app.services import sale_stages_service
from app.core.exceptions import ValidationError

router = APIRouter()


@router.get("/event/{cluster_id}", response_model=List[AreaSaleStageSummary])
async def list_sale_stages(
    cluster_id: int,
    area_id: Optional[int] = Query(None, description="Filter by area"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List sale stages for a specific event/cluster.

    - **cluster_id**: Event ID
    - **area_id**: Optional filter by area
    - **is_active**: Optional filter by active status
    """
    try:
        stages = await sale_stages_service.get_sale_stages_by_cluster(
            cluster_id=cluster_id,
            profile_id=user.user_id,
            area_id=area_id,
            is_active=is_active
        )
        return stages
    except ValidationError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/event/{cluster_id}/{stage_id}", response_model=AreaSaleStage)
async def get_sale_stage(
    cluster_id: int,
    stage_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get sale stage details by ID.

    - **cluster_id**: Event ID
    - **stage_id**: Sale stage UUID
    """
    stage = await sale_stages_service.get_sale_stage_by_id(
        stage_id=stage_id,
        cluster_id=cluster_id,
        profile_id=user.user_id
    )
    if not stage:
        raise HTTPException(status_code=404, detail="Sale stage not found")
    return stage


@router.post("/event/{cluster_id}", response_model=AreaSaleStage, status_code=201)
async def create_sale_stage(
    cluster_id: int,
    data: AreaSaleStageCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a new sale stage (Early Bird, Preventa, etc) for an event.

    - **cluster_id**: Event ID
    - **area_id**: Area to apply the stage to
    - **stage_name**: Name like "Early Bird", "Preventa", "General"
    - **price_adjustment_type**: "percentage" or "fixed"
    - **price_adjustment_value**: Negative for discount (e.g., -20 for 20% off)
    - **quantity_available**: Number of tickets available at this stage
    - **start_time**: When the stage becomes active
    - **end_time**: When the stage ends (null for no end)
    - **priority_order**: Lower number = higher priority
    """
    try:
        stage = await sale_stages_service.create_sale_stage(
            cluster_id=cluster_id,
            profile_id=user.user_id,
            data=data
        )
        return stage
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/event/{cluster_id}/{stage_id}", response_model=AreaSaleStage)
async def update_sale_stage(
    cluster_id: int,
    stage_id: str,
    data: AreaSaleStageUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update a sale stage.

    - **cluster_id**: Event ID
    - **stage_id**: Sale stage UUID
    """
    stage = await sale_stages_service.update_sale_stage(
        stage_id=stage_id,
        cluster_id=cluster_id,
        profile_id=user.user_id,
        data=data
    )
    if not stage:
        raise HTTPException(status_code=404, detail="Sale stage not found")
    return stage


@router.delete("/event/{cluster_id}/{stage_id}", status_code=204)
async def delete_sale_stage(
    cluster_id: int,
    stage_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Delete a sale stage.

    - **cluster_id**: Event ID
    - **stage_id**: Sale stage UUID
    """
    deleted = await sale_stages_service.delete_sale_stage(
        stage_id=stage_id,
        cluster_id=cluster_id,
        profile_id=user.user_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Sale stage not found")
