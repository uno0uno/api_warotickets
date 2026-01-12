from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.area_promotion import (
    AreaPromotion, AreaPromotionCreate, AreaPromotionUpdate,
    AreaPromotionSummary, PromotionValidation, ValidatePromotionRequest,
    CalculatePriceRequest, CalculatedPrice
)
from app.services import area_promotions_service, pricing_service
from app.core.exceptions import ValidationError

router = APIRouter()


@router.get("/event/{cluster_id}", response_model=List[AreaPromotionSummary])
async def list_promotions(
    cluster_id: int,
    area_id: Optional[int] = Query(None, description="Filter by area"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List promotions for a specific event/cluster.

    - **cluster_id**: Event ID
    - **area_id**: Optional filter by area
    - **is_active**: Optional filter by active status
    """
    try:
        promotions = await area_promotions_service.get_promotions_by_cluster(
            cluster_id=cluster_id,
            profile_id=user.user_id,
            area_id=area_id,
            is_active=is_active
        )
        return promotions
    except ValidationError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/event/{cluster_id}/{promo_id}", response_model=AreaPromotion)
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
    promo = await area_promotions_service.get_promotion_by_id(
        promo_id=promo_id,
        cluster_id=cluster_id,
        profile_id=user.user_id
    )
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    return promo


@router.post("/event/{cluster_id}", response_model=AreaPromotion, status_code=201)
async def create_promotion(
    cluster_id: int,
    data: AreaPromotionCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a new promotion for an event area.

    - **cluster_id**: Event ID
    - **area_id**: Area to apply the promotion to
    - **promotion_name**: Name of the promotion
    - **promotion_code**: Optional code (e.g., DESCUENTO20)
    - **discount_type**: "percentage" or "fixed"
    - **discount_value**: Discount amount (e.g., 20 for 20% or 10000 for $10,000)
    - **max_discount_amount**: Maximum discount for percentage types
    - **min_quantity**: Minimum tickets required
    - **quantity_available**: Number of times code can be used (null for unlimited)
    - **start_time**: When the promotion becomes active
    - **end_time**: When the promotion ends (null for no end)
    - **priority_order**: Lower number = higher priority
    """
    try:
        promo = await area_promotions_service.create_promotion(
            cluster_id=cluster_id,
            profile_id=user.user_id,
            data=data
        )
        return promo
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/event/{cluster_id}/{promo_id}", response_model=AreaPromotion)
async def update_promotion(
    cluster_id: int,
    promo_id: str,
    data: AreaPromotionUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update a promotion.

    - **cluster_id**: Event ID
    - **promo_id**: Promotion UUID
    """
    promo = await area_promotions_service.update_promotion(
        promo_id=promo_id,
        cluster_id=cluster_id,
        profile_id=user.user_id,
        data=data
    )
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    return promo


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
    deleted = await area_promotions_service.delete_promotion(
        promo_id=promo_id,
        cluster_id=cluster_id,
        profile_id=user.user_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Promotion not found")


@router.post("/validate", response_model=PromotionValidation)
async def validate_promotion_code(data: ValidatePromotionRequest):
    """
    Validate a promotion code (public endpoint).

    - **promotion_code**: The code to validate
    - **area_id**: The area ID to check against
    - **quantity**: Number of tickets
    """
    validation = await area_promotions_service.validate_promotion_code(
        code=data.promotion_code,
        area_id=data.area_id,
        quantity=data.quantity
    )
    return validation


@router.post("/calculate-price", response_model=CalculatedPrice)
async def calculate_price(data: CalculatePriceRequest):
    """
    Calculate final price with discounts (public endpoint).

    - **area_id**: The area ID
    - **quantity**: Number of tickets
    - **promotion_code**: Optional promotion code
    """
    price = await pricing_service.calculate_price(
        area_id=data.area_id,
        quantity=data.quantity,
        promotion_code=data.promotion_code
    )
    return price
