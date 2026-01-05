import logging
from typing import Optional, Tuple
from decimal import Decimal
from datetime import datetime
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

        # Get active sale stage
        sale_stage = await conn.fetchrow("""
            SELECT id, stage_name, price_adjustment_type, price_adjustment_value
            FROM sale_stages
            WHERE (target_area_id = $1 OR target_area_id IS NULL)
              AND is_active = true
              AND start_time <= NOW()
              AND (end_time IS NULL OR end_time > NOW())
              AND quantity_available > 0
            ORDER BY priority_order ASC
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
    area_id: Optional[int] = None,
    cluster_id: Optional[int] = None,
    quantity: int = 1
) -> PromotionValidation:
    """Validate a promotion code"""
    async with get_db_connection(use_transaction=False) as conn:
        # Find promotion by code
        promo = await conn.fetchrow("""
            SELECT id, promotion_name, discount_type, discount_value,
                   applies_to, target_cluster_id, target_area_id,
                   min_quantity, max_discount_amount, start_date, end_date, is_active
            FROM promotions
            WHERE promotion_code = $1
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
        now = datetime.now(promo['start_date'].tzinfo)
        if now < promo['start_date']:
            return PromotionValidation(
                is_valid=False,
                error_message="Este codigo aun no esta vigente"
            )

        if now > promo['end_date']:
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

        # Check target restrictions
        applies_to = promo['applies_to']

        if applies_to == 'cluster' and promo['target_cluster_id']:
            if cluster_id and cluster_id != promo['target_cluster_id']:
                return PromotionValidation(
                    is_valid=False,
                    error_message="Este codigo no aplica para este evento"
                )

        if applies_to == 'area' and promo['target_area_id']:
            if area_id and area_id != promo['target_area_id']:
                return PromotionValidation(
                    is_valid=False,
                    error_message="Este codigo no aplica para esta localidad"
                )

        return PromotionValidation(
            is_valid=True,
            promotion_id=str(promo['id']),
            promotion_name=promo['promotion_name'],
            discount_type=promo['discount_type'],
            discount_value=Decimal(str(promo['discount_value'])),
            max_discount_amount=Decimal(str(promo['max_discount_amount'])) if promo['max_discount_amount'] else None
        )


async def get_active_sale_stage(area_id: int) -> Optional[dict]:
    """Get currently active sale stage for an area"""
    async with get_db_connection(use_transaction=False) as conn:
        stage = await conn.fetchrow("""
            SELECT id, stage_name, price_adjustment_type, price_adjustment_value,
                   quantity_available, start_time, end_time, priority_order
            FROM sale_stages
            WHERE (target_area_id = $1 OR target_area_id IS NULL)
              AND is_active = true
              AND start_time <= NOW()
              AND (end_time IS NULL OR end_time > NOW())
              AND quantity_available > 0
            ORDER BY priority_order ASC
            LIMIT 1
        """, area_id)

        return dict(stage) if stage else None


async def decrement_sale_stage_quantity(stage_id: str, quantity: int = 1) -> bool:
    """Decrement available quantity in a sale stage after purchase"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE sale_stages
            SET quantity_available = quantity_available - $2,
                updated_at = NOW()
            WHERE id = $1 AND quantity_available >= $2
        """, stage_id, quantity)

        return result == "UPDATE 1"


async def increment_promotion_usage(promotion_id: str, user_id: str) -> bool:
    """Track promotion usage (for future limits implementation)"""
    # For now, just log it
    logger.info(f"Promotion {promotion_id} used by user {user_id}")
    return True
