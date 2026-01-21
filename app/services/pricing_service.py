import logging
from typing import Optional
from decimal import Decimal
from datetime import datetime, timezone
from app.database import get_db_connection
from app.models.promotion import CalculatedPrice, PromotionValidation

logger = logging.getLogger(__name__)


async def calculate_price(
    area_id: int,
    quantity: int = 1,
    promotion_code: Optional[str] = None
) -> CalculatedPrice:
    """
    Calculate final price for tickets including:
    - Base price from area
    - Sale stage discount (automatic)
    - Promotion code discount (if provided)
    - Service fee
    """
    async with get_db_connection(use_transaction=False) as conn:
        # Get area base price
        area = await conn.fetchrow("""
            SELECT id, price, currency, service
            FROM areas WHERE id = $1
        """, area_id)

        if not area:
            raise ValueError(f"Area {area_id} not found")

        base_price = Decimal(str(area['price']))
        currency = area['currency'] or 'COP'
        service_percentage = Decimal(str(area['service'] or 0))

        # Get active sale stage (using new table structure)
        sale_stage = await conn.fetchrow("""
            SELECT ss.id, ss.stage_name, ss.price_adjustment_type, ss.price_adjustment_value
            FROM sale_stages ss
            JOIN sale_stage_areas ssa ON ss.id = ssa.sale_stage_id
            WHERE ssa.area_id = $1
              AND ss.is_active = true
              AND ss.start_time <= NOW()
              AND (ss.end_time IS NULL OR ss.end_time > NOW())
              AND (ss.quantity_available - ss.quantity_sold) > 0
            ORDER BY ss.priority_order ASC
            LIMIT 1
        """, area_id)

        sale_stage_discount = Decimal("0")
        applied_sale_stage = None

        if sale_stage:
            adjustment_type = sale_stage['price_adjustment_type']
            adjustment_value = Decimal(str(sale_stage['price_adjustment_value']))

            if adjustment_type == 'percentage':
                # Negative = discount
                sale_stage_discount = base_price * abs(adjustment_value) / 100
                if adjustment_value > 0:
                    sale_stage_discount = -sale_stage_discount  # Increase price
            elif adjustment_type == 'fixed':
                sale_stage_discount = abs(adjustment_value)
                if adjustment_value > 0:
                    sale_stage_discount = -adjustment_value

            applied_sale_stage = sale_stage['stage_name']

        # Calculate price after sale stage
        price_after_stage = base_price - sale_stage_discount

        # Apply promotion if provided
        promotion_discount = Decimal("0")
        applied_promotion = None

        if promotion_code:
            promo_validation = await validate_promotion_code(
                promotion_code, area_id=area_id, quantity=quantity
            )

            if promo_validation.is_valid:
                if promo_validation.discount_type == 'percentage':
                    promotion_discount = price_after_stage * promo_validation.discount_value / 100
                    if promo_validation.max_discount_amount:
                        promotion_discount = min(promotion_discount, promo_validation.max_discount_amount)
                elif promo_validation.discount_type == 'fixed':
                    promotion_discount = promo_validation.discount_value

                applied_promotion = promo_validation.promotion_name

        # Calculate service fee
        price_after_discounts = price_after_stage - promotion_discount
        service_fee = price_after_discounts * service_percentage / 100

        # Calculate final price (per unit)
        final_price = price_after_discounts + service_fee

        # Multiply by quantity
        return CalculatedPrice(
            base_price=base_price * quantity,
            sale_stage_discount=sale_stage_discount * quantity,
            promotion_discount=promotion_discount * quantity,
            service_fee=service_fee * quantity,
            final_price=final_price * quantity,
            currency=currency,
            applied_sale_stage=applied_sale_stage,
            applied_promotion=applied_promotion
        )


async def validate_promotion_code(
    code: str,
    area_id: int,
    quantity: int = 1
) -> PromotionValidation:
    """Validate a promotion code (using new table structure with promotion_areas)"""
    async with get_db_connection(use_transaction=False) as conn:
        # Find promotion by code
        promo = await conn.fetchrow("""
            SELECT p.id, p.promotion_name, p.discount_type, p.discount_value,
                   p.min_quantity, p.max_discount_amount,
                   p.quantity_available, p.uses_count, p.start_time, p.end_time, p.is_active
            FROM promotions p
            WHERE p.promotion_code = $1
        """, code.upper().strip())

        if not promo:
            return PromotionValidation(
                is_valid=False,
                error_message="Codigo promocional no encontrado"
            )

        # Check if active
        if not promo['is_active']:
            return PromotionValidation(
                is_valid=False,
                error_message="Este codigo ya no esta activo"
            )

        # Check dates
        now = datetime.now(timezone.utc)
        start_time = promo['start_time']
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        if now < start_time:
            return PromotionValidation(
                is_valid=False,
                error_message="Este codigo aun no esta vigente"
            )

        if promo['end_time']:
            end_time = promo['end_time']
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            if now > end_time:
                return PromotionValidation(
                    is_valid=False,
                    error_message="Este codigo ha expirado"
                )

        # Check minimum quantity
        if quantity < promo['min_quantity']:
            return PromotionValidation(
                is_valid=False,
                error_message=f"Se requieren minimo {promo['min_quantity']} tickets"
            )

        # Check available uses
        if promo['quantity_available'] is not None:
            remaining = promo['quantity_available'] - promo['uses_count']
            if remaining < quantity:
                return PromotionValidation(
                    is_valid=False,
                    error_message="No hay suficientes usos disponibles para este codigo"
                )

        # Check area match using promotion_areas link table
        area_match = await conn.fetchrow("""
            SELECT 1 FROM promotion_areas
            WHERE promotion_id = $1 AND area_id = $2
        """, promo['id'], area_id)

        if not area_match:
            return PromotionValidation(
                is_valid=False,
                error_message="Este codigo no aplica para esta localidad"
            )

        # Get all areas this promotion applies to
        area_ids = await conn.fetch(
            "SELECT area_id FROM promotion_areas WHERE promotion_id = $1",
            promo['id']
        )

        return PromotionValidation(
            is_valid=True,
            promotion_id=str(promo['id']),
            promotion_name=promo['promotion_name'],
            discount_type=promo['discount_type'],
            discount_value=Decimal(str(promo['discount_value'])),
            max_discount_amount=Decimal(str(promo['max_discount_amount'])) if promo['max_discount_amount'] else None,
            applies_to_areas=[r['area_id'] for r in area_ids]
        )


async def get_active_sale_stage(area_id: int) -> Optional[dict]:
    """Get currently active sale stage for an area (using new table structure)"""
    async with get_db_connection(use_transaction=False) as conn:
        stage = await conn.fetchrow("""
            SELECT ss.id, ss.stage_name, ss.price_adjustment_type, ss.price_adjustment_value,
                   (ss.quantity_available - ss.quantity_sold) as quantity_remaining,
                   ss.start_time, ss.end_time, ss.priority_order
            FROM sale_stages ss
            JOIN sale_stage_areas ssa ON ss.id = ssa.sale_stage_id
            WHERE ssa.area_id = $1
              AND ss.is_active = true
              AND ss.start_time <= NOW()
              AND (ss.end_time IS NULL OR ss.end_time > NOW())
              AND (ss.quantity_available - ss.quantity_sold) > 0
            ORDER BY ss.priority_order ASC
            LIMIT 1
        """, area_id)

        return dict(stage) if stage else None


async def get_active_promotion(area_id: int) -> Optional[dict]:
    """
    Get currently active promotion for an area.
    Note: All promotions now require codes, so this returns None.
    Kept for backwards compatibility.
    """
    # Promotions now require codes, no auto-apply promotions
    return None


async def decrement_sale_stage_quantity(stage_id: str, quantity: int = 1) -> bool:
    """Decrement available quantity in a sale stage after purchase (increment quantity_sold)"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE sale_stages
            SET quantity_sold = quantity_sold + $2,
                updated_at = NOW()
            WHERE id = $1
              AND (quantity_available - quantity_sold) >= $2
        """, stage_id, quantity)

        return result == "UPDATE 1"


async def decrement_promotion_quantity(promo_id: str, quantity: int = 1) -> bool:
    """Increment uses_count in a promotion after use"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE promotions
            SET uses_count = uses_count + $2,
                updated_at = NOW()
            WHERE id = $1
              AND (quantity_available IS NULL OR (quantity_available - uses_count) >= $2)
        """, promo_id, quantity)

        return result == "UPDATE 1"


async def increment_promotion_usage(promotion_id: str, user_id: str) -> bool:
    """Track promotion usage (for future limits implementation)"""
    # For now, just log it
    logger.info(f"Promotion {promotion_id} used by user {user_id}")
    return True
