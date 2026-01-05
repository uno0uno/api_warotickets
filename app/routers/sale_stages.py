from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.sale_stage import (
    SaleStage, SaleStageCreate, SaleStageUpdate, SaleStageSummary
)
from app.services import sale_stages_service

router = APIRouter()


@router.get("", response_model=List[SaleStageSummary])
async def list_sale_stages(
    area_id: Optional[int] = Query(None, description="Filter by area"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List sale stages for the organizer.
    """
    stages = await sale_stages_service.get_sale_stages(
        user.user_id,
        area_id=area_id,
        is_active=is_active
    )
    return stages


@router.get("/{stage_id}", response_model=SaleStage)
async def get_sale_stage(
    stage_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get sale stage details by ID.
    """
    stage = await sale_stages_service.get_sale_stage_by_id(stage_id, user.user_id)
    if not stage:
        raise HTTPException(status_code=404, detail="Sale stage not found")
    return stage


@router.post("", response_model=SaleStage, status_code=201)
async def create_sale_stage(
    data: SaleStageCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a new sale stage (Early Bird, Preventa, etc).
    """
    stage = await sale_stages_service.create_sale_stage(user.user_id, data)
    return stage


@router.patch("/{stage_id}", response_model=SaleStage)
async def update_sale_stage(
    stage_id: str,
    data: SaleStageUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update a sale stage.
    """
    stage = await sale_stages_service.update_sale_stage(stage_id, user.user_id, data)
    if not stage:
        raise HTTPException(status_code=404, detail="Sale stage not found")
    return stage


@router.delete("/{stage_id}", status_code=204)
async def delete_sale_stage(
    stage_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Delete a sale stage.
    """
    deleted = await sale_stages_service.delete_sale_stage(stage_id, user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Sale stage not found")
