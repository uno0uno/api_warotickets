from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.promotion import (
    Promotion, PromotionCreate, PromotionUpdate, PromotionSummary,
    PromotionValidation, ApplyPromotionRequest, CalculatedPrice
)
from app.services import promotions_service, pricing_service

router = APIRouter()


@router.get("", response_model=List[PromotionSummary])
async def list_promotions(
    cluster_id: Optional[int] = Query(None, description="Filter by event"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    List promotions for the organizer.
    """
    promotions = await promotions_service.get_promotions(
        user.user_id,
        cluster_id=cluster_id,
        is_active=is_active
    )
    return promotions


@router.get("/{promo_id}", response_model=Promotion)
async def get_promotion(
    promo_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get promotion details by ID.
    """
    promo = await promotions_service.get_promotion_by_id(promo_id, user.user_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    return promo


@router.post("", response_model=Promotion, status_code=201)
async def create_promotion(
    data: PromotionCreate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Create a new promotion code.
    """
    promo = await promotions_service.create_promotion(user.user_id, data)
    return promo


@router.patch("/{promo_id}", response_model=Promotion)
async def update_promotion(
    promo_id: str,
    data: PromotionUpdate,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Update a promotion.
    """
    promo = await promotions_service.update_promotion(promo_id, user.user_id, data)
    if not promo:
        raise HTTPException(status_code=404, detail="Promotion not found")
    return promo


@router.delete("/{promo_id}", status_code=204)
async def delete_promotion(
    promo_id: str,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Delete a promotion.
    """
    deleted = await promotions_service.delete_promotion(promo_id, user.user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Promotion not found")


@router.post("/validate", response_model=PromotionValidation)
async def validate_promotion_code(
    data: ApplyPromotionRequest
):
    """
    Validate a promotion code (public endpoint).
    """
    validation = await pricing_service.validate_promotion_code(
        data.promotion_code,
        area_id=data.area_id,
        cluster_id=data.cluster_id,
        quantity=data.quantity
    )
    return validation


@router.post("/calculate-price", response_model=CalculatedPrice)
async def calculate_price(
    area_id: int,
    quantity: int = Query(1, ge=1, le=20),
    promotion_code: Optional[str] = Query(None)
):
    """
    Calculate final price with discounts (public endpoint).
    """
    price = await pricing_service.calculate_price(
        area_id,
        quantity=quantity,
        promotion_code=promotion_code
    )
    return price
