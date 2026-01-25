import logging
from typing import Optional
from decimal import Decimal
from app.database import get_db_connection

logger = logging.getLogger(__name__)


async def get_active_sale_stage(area_id: int) -> Optional[dict]:
    """Get currently active sale stage for an area"""
    async with get_db_connection(use_transaction=False) as conn:
        stage = await conn.fetchrow("""
            SELECT ss.id, ss.stage_name, ss.price_adjustment_type, ss.price_adjustment_value,
                   ssa.quantity as bundle_size,
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


async def calculate_area_price(
    area_id: int,
    quantity: int = 1
) -> dict:
    """
    Calculate price for an area considering active sale stage.
    Returns pricing info without promotion codes.
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
        stage = await get_active_sale_stage(area_id)

        unit_price = base_price
        bundle_size = 1
        stage_name = None

        if stage:
            bundle_size = stage.get('bundle_size') or 1
            stage_name = stage['stage_name']
            adj_type = stage['price_adjustment_type']
            adj_value = Decimal(str(stage['price_adjustment_value']))

            if adj_type == 'percentage':
                unit_price = base_price * (1 + adj_value / 100)
            elif adj_type == 'fixed':
                bundle_total = base_price * bundle_size
                discounted_total = bundle_total + adj_value
                unit_price = discounted_total / bundle_size
            elif adj_type == 'fixed_price':
                unit_price = adj_value / bundle_size

            unit_price = max(Decimal('0'), unit_price)

        # Calculate totals
        tickets_count = quantity * bundle_size
        subtotal = unit_price * tickets_count
        service_fee = subtotal * service_percentage / 100
        final_price = subtotal + service_fee

        return {
            'base_price': base_price,
            'unit_price': unit_price,
            'bundle_size': bundle_size,
            'quantity': quantity,
            'tickets_count': tickets_count,
            'subtotal': subtotal,
            'service_fee': service_fee,
            'final_price': final_price,
            'currency': currency,
            'stage_name': stage_name
        }


async def decrement_sale_stage_quantity(stage_id: str, quantity: int = 1) -> bool:
    """Decrement available quantity in a sale stage after purchase"""
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
