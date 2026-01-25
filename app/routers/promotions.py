from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.promotion import (
    Promotion, PromotionCreate, PromotionUpdate, PromotionSummary
)
from app.services import promotions_service
from app.core.exceptions import ValidationError

router = APIRouter()


@router.get("/event/{cluster_id}", response_model=List[PromotionSummary])
async def list_promotions(
    cluster_id: int,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List all promotions for a specific event/cluster.
    Each promotion is a combo/package of tickets (areas + quantities).

    - **cluster_id**: Event ID
    - **is_active**: Optional filter by active status
    """
    try:
        promotions = await promotions_service.get_promotions_by_cluster(
            cluster_id=cluster_id,
            profile_id=user.user_id,
            tenant_id=user.tenant_id,
            is_active=is_active
        )
        return promotions
    except ValidationError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/event/{cluster_id}/{promo_id}", response_model=Promotion)
async def get_promotion(
    cluster_id: int,
    promo_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get promotion details by ID.

    - **cluster_id**: Event ID
    - **promo_id**: Promotion UUID
    """
    promo = await promotions_service.get_promotion_by_id(
        promo_id=promo_id,
        cluster_id=cluster_id,
        profile_id=user.user_id,
        tenant_id=user.tenant_id
    )
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    return promo


@router.post("/event/{cluster_id}", response_model=Promotion, status_code=201)
async def create_promotion(
    cluster_id: int,
    data: PromotionCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a new promotion (combo/package) for an event.

    Promotions are packages of tickets that can have:
    - Multiple areas with specific quantities (e.g., 2 VIP + 2 General)
    - Three pricing types:
      - **percentage**: Discount percentage off the original price
      - **fixed_discount**: Fixed amount off the original price
      - **fixed_price**: Fixed total price for the entire package

    - **cluster_id**: Event ID
    - **promotion_name**: Name of the promotion (e.g., "Pack Familiar")
    - **items**: List of areas and quantities in the package
    - **pricing_type**: "percentage", "fixed_discount", or "fixed_price"
    - **pricing_value**: Discount % or amount, or fixed package price
    - **max_discount_amount**: Maximum discount (only for percentage type)
    - **quantity_available**: Number of packages available (null = unlimited)
    - **start_time**: When the promotion becomes active
    - **end_time**: When the promotion ends (null = no end)
    - **priority_order**: Lower number = higher priority
    """
    try:
        promo = await promotions_service.create_promotion(
            cluster_id=cluster_id,
            profile_id=user.user_id,
            tenant_id=user.tenant_id,
            data=data
        )
        return promo
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/event/{cluster_id}/{promo_id}", response_model=Promotion)
async def update_promotion(
    cluster_id: int,
    promo_id: str,
    data: PromotionUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update a promotion.
    Can update fields and/or change the items (areas + quantities).

    - **cluster_id**: Event ID
    - **promo_id**: Promotion UUID
    - **items**: Optional - if provided, replaces existing items
    """
    try:
        promo = await promotions_service.update_promotion(
            promo_id=promo_id,
            cluster_id=cluster_id,
            profile_id=user.user_id,
            tenant_id=user.tenant_id,
            data=data
        )
        if not promo:
            raise HTTPException(status_code=404, detail="Promotion not found")
        return promo
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/event/{cluster_id}/{promo_id}", status_code=204)
async def delete_promotion(
    cluster_id: int,
    promo_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Delete a promotion.

    - **cluster_id**: Event ID
    - **promo_id**: Promotion UUID
    """
    deleted = await promotions_service.delete_promotion(
        promo_id=promo_id,
        cluster_id=cluster_id,
        profile_id=user.user_id,
        tenant_id=user.tenant_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Promotion not found")


