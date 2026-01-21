from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.sale_stage import (
    SaleStage, SaleStageCreate, SaleStageUpdate, SaleStageSummary
)
from app.services import sale_stages_service
from app.core.exceptions import ValidationError

router = APIRouter()


@router.get("/event/{cluster_id}", response_model=List[SaleStageSummary])
async def list_sale_stages(
    cluster_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List all sale stages for a specific event/cluster.
    Each stage can apply to multiple areas.

    - **cluster_id**: Event ID
    - **is_active**: Optional filter by active status
    """
    try:
        stages = await sale_stages_service.get_sale_stages_by_cluster(
            cluster_id=cluster_id,
            profile_id=user.user_id,
            tenant_id=user.tenant_id,
            is_active=is_active
        )
        return stages
    except ValidationError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/event/{cluster_id}/{stage_id}", response_model=SaleStage)
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
        profile_id=user.user_id,
        tenant_id=user.tenant_id
    )
    if not stage:
        raise HTTPException(status_code=404, detail="Sale stage not found")
    return stage


@router.post("/event/{cluster_id}", response_model=SaleStage, status_code=201)
async def create_sale_stage(
    cluster_id: int,
    data: SaleStageCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a new sale stage (Early Bird, Preventa, etc) for an event.
    The stage will apply to all specified areas.

    - **cluster_id**: Event ID
    - **area_ids**: List of area IDs where this stage applies
    - **stage_name**: Name like "Early Bird", "Preventa", "General"
    - **price_adjustment_type**: "percentage" or "fixed"
    - **price_adjustment_value**: Negative for discount (e.g., -20 for 20% off)
    - **quantity_available**: Total tickets available at this stage (shared across areas)
    - **start_time**: When the stage becomes active
    - **end_time**: When the stage ends (null for no end)
    - **priority_order**: Lower number = higher priority
    """
    try:
        stage = await sale_stages_service.create_sale_stage(
            cluster_id=cluster_id,
            profile_id=user.user_id,
            tenant_id=user.tenant_id,
            data=data
        )
        return stage
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/event/{cluster_id}/{stage_id}", response_model=SaleStage)
async def update_sale_stage(
    cluster_id: int,
    stage_id: str,
    data: SaleStageUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update a sale stage.
    Can update fields and/or change which areas it applies to.

    - **cluster_id**: Event ID
    - **stage_id**: Sale stage UUID
    - **area_ids**: Optional - if provided, replaces existing area links
    """
    try:
        stage = await sale_stages_service.update_sale_stage(
            stage_id=stage_id,
            cluster_id=cluster_id,
            profile_id=user.user_id,
            tenant_id=user.tenant_id,
            data=data
        )
        if not stage:
            raise HTTPException(status_code=404, detail="Sale stage not found")
        return stage
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
        profile_id=user.user_id,
        tenant_id=user.tenant_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Sale stage not found")
