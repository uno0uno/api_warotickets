from fastapi import APIRouter, HTTPException, Header, Query, Cookie
from typing import Optional
from pydantic import BaseModel, Field
from app.models.ticket_cart import (
    TicketCartCreate, TicketCartItemCreate, TicketCartItemUpdate,
    CartCheckout, TicketCartResponse, CartSummary, CheckoutResponse
)
from app.services import ticket_cart_service
from app.core.exceptions import ValidationError
import uuid

router = APIRouter()


def get_session_id(x_session_id: Optional[str] = Header(None), session_id: Optional[str] = Cookie(None)) -> str:
    """Get or generate session ID"""
    return x_session_id or session_id or str(uuid.uuid4())


@router.get("/summary", response_model=CartSummary)
async def get_cart_summary(
    x_session_id: Optional[str] = Header(None),
    session_id: Optional[str] = Cookie(None),
    user_id: Optional[str] = Header(None, alias="x-user-id")
):
    """Get cart summary for header display"""
    sid = get_session_id(x_session_id, session_id)
    return await ticket_cart_service.get_cart_summary(
        session_id=sid,
        user_id=user_id
    )


@router.post("", response_model=TicketCartResponse)
async def create_or_get_cart(
    data: TicketCartCreate,
    x_session_id: Optional[str] = Header(None),
    session_id: Optional[str] = Cookie(None),
    user_id: Optional[str] = Header(None, alias="x-user-id"),
    promoter_ref: Optional[str] = Header(None, alias="x-promoter-ref")
):
    """Create new cart or get existing one for the event"""
    sid = get_session_id(x_session_id, session_id)

    cart = await ticket_cart_service.get_or_create_cart(
        session_id=sid,
        user_id=user_id,
        cluster_id=data.cluster_id,
        promoter_code=promoter_ref
    )

    if not cart:
        raise HTTPException(status_code=400, detail="No se pudo crear el carrito")

    # Add initial items if provided
    if data.items:
        for item in data.items:
            await ticket_cart_service.add_item(
                str(cart['id']),
                item.area_id,
                item.quantity
            )

    return await ticket_cart_service.get_cart(str(cart['id']))


@router.get("/{cart_id}", response_model=TicketCartResponse)
async def get_cart(cart_id: str):
    """Get cart by ID"""
    try:
        return await ticket_cart_service.get_cart(cart_id)
    except ValidationError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{cart_id}/items", response_model=TicketCartResponse)
async def add_item_to_cart(cart_id: str, data: TicketCartItemCreate):
    """Add item to cart"""
    try:
        return await ticket_cart_service.add_item(
            cart_id,
            data.area_id,
            data.quantity
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{cart_id}/items/{area_id}", response_model=TicketCartResponse)
async def update_cart_item(cart_id: str, area_id: int, data: TicketCartItemUpdate):
    """Update item quantity in cart"""
    try:
        return await ticket_cart_service.update_item(
            cart_id,
            area_id,
            data.quantity
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{cart_id}/items/{area_id}", response_model=TicketCartResponse)
async def remove_cart_item(cart_id: str, area_id: int):
    """Remove item from cart"""
    try:
        return await ticket_cart_service.remove_item(cart_id, area_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


class PromotionPackageAdd(BaseModel):
    """Schema for adding promotion package"""
    quantity: int = Field(default=1, ge=1, le=5, description="Cantidad de paquetes")


@router.post("/{cart_id}/promotion-package/{promotion_id}", response_model=TicketCartResponse)
async def add_promotion_package(
    cart_id: str,
    promotion_id: str,
    data: Optional[PromotionPackageAdd] = None
):
    """Add promotional package(s) to cart"""
    try:
        quantity = data.quantity if data else 1
        return await ticket_cart_service.add_promotion_package(
            cart_id,
            promotion_id,
            quantity
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{cart_id}/promotion-package/{promotion_id}", response_model=TicketCartResponse)
async def remove_promotion_package(cart_id: str, promotion_id: str):
    """Remove promotional package from cart"""
    try:
        return await ticket_cart_service.remove_promotion_from_cart(cart_id, promotion_id)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{cart_id}/checkout", response_model=CheckoutResponse)
async def checkout_cart(cart_id: str, data: CartCheckout):
    """Convert cart to reservation and create payment"""
    try:
        return await ticket_cart_service.checkout(
            cart_id=cart_id,
            customer_email=data.customer_email,
            customer_name=data.customer_name,
            customer_phone=data.customer_phone,
            return_url=data.return_url or "http://localhost:8888/pago/resultado"
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{cart_id}", response_model=dict)
async def clear_cart(cart_id: str):
    """Clear all items from cart"""
    try:
        await ticket_cart_service.clear_cart(cart_id)
        return {"success": True, "message": "Carrito vaciado"}
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
