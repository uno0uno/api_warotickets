import logging
import json
from typing import Optional, List
from datetime import datetime, timezone
from decimal import Decimal
from app.database import get_db_connection
from app.models.promotion import (
    Promotion, PromotionCreate, PromotionUpdate, PromotionSummary,
    PromotionItemResponse
)
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def _parse_json_field(value):
    """Parse JSON field from PostgreSQL - handles both string and already parsed values"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


async def verify_cluster_ownership(conn, cluster_id: int, profile_id: str, tenant_id: str) -> bool:
    """Verifica que el cluster pertenece al tenant (cualquier miembro puede acceder)"""
    row = await conn.fetchrow(
        "SELECT id FROM clusters WHERE id = $1 AND tenant_id = $2",
        cluster_id, tenant_id
    )
    return row is not None


async def verify_areas_in_cluster(conn, area_ids: List[int], cluster_id: int) -> bool:
    """Verifica que todas las areas pertenecen al cluster"""
    result = await conn.fetchval(
        "SELECT COUNT(*) FROM areas WHERE id = ANY($1) AND cluster_id = $2",
        area_ids, cluster_id
    )
    return result == len(area_ids)


async def calculate_max_promotion_uses(conn, items: List) -> Optional[int]:
    """
    Calcula el maximo de usos de una promocion basado en la capacidad de las areas.
    Para cada area: floor(capacidad / cantidad_en_combo)
    Retorna el minimo de todos.

    items puede ser lista de objetos con .area_id/.quantity o lista de dicts
    """
    if not items:
        return None

    # Helper to get area_id and quantity from item (dict or object)
    def get_area_id(item):
        return item.get('area_id') if isinstance(item, dict) else item.area_id

    def get_quantity(item):
        return item.get('quantity') if isinstance(item, dict) else item.quantity

    area_ids = [get_area_id(item) for item in items]
    rows = await conn.fetch(
        "SELECT id, capacity FROM areas WHERE id = ANY($1)",
        area_ids
    )

    area_capacities = {row['id']: row['capacity'] for row in rows}

    max_per_area = []
    for item in items:
        area_id = get_area_id(item)
        quantity = get_quantity(item)
        capacity = area_capacities.get(area_id)
        if capacity is None or capacity == 0 or quantity <= 0:
            continue
        max_per_area.append(capacity // quantity)

    if not max_per_area:
        return None

    return min(max_per_area)


async def get_promotions_by_cluster(
    cluster_id: int,
    profile_id: str,
    tenant_id: str,
    is_active: Optional[bool] = None
) -> List[PromotionSummary]:
    """Get all promotions for a cluster/event"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            raise ValidationError("Cluster not found or access denied")

        query = """
            SELECT
                p.id,
                p.cluster_id,
                p.promotion_name,
                p.promotion_code,
                p.pricing_type,
                p.pricing_value,
                p.quantity_available,
                p.uses_count,
                p.start_time,
                p.end_time,
                p.is_active,
                p.priority_order,
                (p.start_time <= NOW()
                 AND (p.end_time IS NULL OR p.end_time > NOW())
                 AND (p.quantity_available IS NULL OR (p.quantity_available - p.uses_count) > 0)
                 AND p.is_active = true) as is_currently_valid,
                COALESCE((SELECT SUM(pi.quantity) FROM promotion_items pi WHERE pi.promotion_id = p.id), 0) as total_tickets,
                (SELECT COUNT(*) FROM promotion_items pi WHERE pi.promotion_id = p.id) as items_count,
                (SELECT json_agg(json_build_object(
                    'area_id', a.id,
                    'area_name', a.area_name,
                    'area_price', a.price,
                    'quantity', pi.quantity
                 ))
                 FROM promotion_items pi
                 JOIN areas a ON pi.area_id = a.id
                 WHERE pi.promotion_id = p.id) as items
            FROM promotions p
            WHERE p.cluster_id = $1
        """
        params = [cluster_id]
        param_idx = 2

        if is_active is not None:
            query += f" AND p.is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1

        query += " ORDER BY p.priority_order ASC, p.start_time ASC"

        rows = await conn.fetch(query, *params)
        result = []
        for row in rows:
            promo_dict = dict(row)
            promo_dict['id'] = str(row['id'])
            promo_dict['items'] = _parse_json_field(row['items'])
            result.append(PromotionSummary(**promo_dict))
        return result


async def get_promotion_by_id(
    promo_id: str,
    cluster_id: int,
    profile_id: str,
    tenant_id: str
) -> Optional[Promotion]:
    """Get promotion by ID"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            return None

        row = await conn.fetchrow("""
            SELECT
                p.*,
                (p.start_time <= NOW()
                 AND (p.end_time IS NULL OR p.end_time > NOW())
                 AND (p.quantity_available IS NULL OR (p.quantity_available - p.uses_count) > 0)
                 AND p.is_active = true) as is_currently_valid,
                CASE WHEN p.quantity_available IS NOT NULL
                     THEN p.quantity_available - p.uses_count
                     ELSE NULL END as uses_remaining,
                COALESCE((SELECT SUM(pi.quantity) FROM promotion_items pi WHERE pi.promotion_id = p.id), 0) as total_tickets,
                (SELECT json_agg(json_build_object(
                    'area_id', a.id,
                    'area_name', a.area_name,
                    'area_price', a.price,
                    'quantity', pi.quantity
                 ))
                 FROM promotion_items pi
                 JOIN areas a ON pi.area_id = a.id
                 WHERE pi.promotion_id = p.id) as items,
                (SELECT SUM(a.price * pi.quantity)
                 FROM promotion_items pi
                 JOIN areas a ON pi.area_id = a.id
                 WHERE pi.promotion_id = p.id) as original_price
            FROM promotions p
            WHERE p.id = $1 AND p.cluster_id = $2
        """, promo_id, cluster_id)

        if not row:
            return None

        promo_dict = dict(row)
        promo_dict['id'] = str(row['id'])
        promo_dict['items'] = _parse_json_field(row['items'])
        return Promotion(**promo_dict)


async def create_promotion(
    cluster_id: int,
    profile_id: str,
    tenant_id: str,
    data: PromotionCreate
) -> Promotion:
    """Create a new promotion for a cluster"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            raise ValidationError("Cluster not found or access denied")

        # Get area_ids from items
        area_ids = [item.area_id for item in data.items]

        # Verify all areas belong to cluster
        if not await verify_areas_in_cluster(conn, area_ids, cluster_id):
            raise ValidationError("One or more areas do not belong to this cluster")

        # Validate quantity_available against area capacities
        if data.quantity_available is not None:
            max_available = await calculate_max_promotion_uses(conn, data.items)
            if max_available is not None and data.quantity_available > max_available:
                raise ValidationError(
                    f"Cantidad disponible ({data.quantity_available}) excede el maximo permitido "
                    f"segun la capacidad de las areas ({max_available})"
                )

        # Create promotion
        row = await conn.fetchrow("""
            INSERT INTO promotions (
                cluster_id, promotion_name, description,
                pricing_type, pricing_value, max_discount_amount,
                quantity_available, uses_count,
                start_time, end_time, is_active, priority_order,
                created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, 0, $8, $9, true, $10, NOW(), NOW()
            )
            RETURNING *
        """,
            cluster_id,
            data.promotion_name,
            data.description,
            data.pricing_type.value,
            data.pricing_value,
            data.max_discount_amount,
            data.quantity_available,
            data.start_time,
            data.end_time,
            data.priority_order
        )

        promo_id = row['id']

        # Create promotion items (area + quantity)
        for item in data.items:
            await conn.execute("""
                INSERT INTO promotion_items (promotion_id, area_id, quantity)
                VALUES ($1, $2, $3)
            """, promo_id, item.area_id, item.quantity)

        logger.info(f"Created promotion: {promo_id} - {data.promotion_name} for cluster {cluster_id}")

        # Get items for response
        items_rows = await conn.fetch("""
            SELECT a.id as area_id, a.area_name, a.price as area_price, pi.quantity
            FROM promotion_items pi
            JOIN areas a ON pi.area_id = a.id
            WHERE pi.promotion_id = $1
        """, promo_id)

        items = [PromotionItemResponse(
            area_id=r['area_id'],
            quantity=r['quantity'],
            area_name=r['area_name'],
            area_price=r['area_price']
        ) for r in items_rows]

        # Calculate totals
        total_tickets = sum(item.quantity for item in items)
        original_price = sum((item.area_price or Decimal('0')) * item.quantity for item in items)

        promo_dict = dict(row)
        promo_dict['id'] = str(promo_id)
        promo_dict['items'] = [item.model_dump() for item in items]
        promo_dict['total_tickets'] = total_tickets
        promo_dict['original_price'] = original_price
        promo_dict['is_currently_valid'] = (
            row['start_time'] <= datetime.now(timezone.utc) and
            (row['end_time'] is None or row['end_time'] > datetime.now(timezone.utc)) and
            (row['quantity_available'] is None or row['quantity_available'] > 0) and
            row['is_active']
        )
        promo_dict['uses_remaining'] = row['quantity_available'] if row['quantity_available'] else None

        return Promotion(**promo_dict)


async def update_promotion(
    promo_id: str,
    cluster_id: int,
    profile_id: str,
    tenant_id: str,
    data: PromotionUpdate
) -> Optional[Promotion]:
    """Update a promotion"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            return None

        # Verify promotion exists in cluster
        existing = await conn.fetchrow(
            "SELECT id FROM promotions WHERE id = $1 AND cluster_id = $2",
            promo_id, cluster_id
        )

        if not existing:
            return None

        # Handle items update separately
        update_data = data.model_dump(exclude_unset=True)
        items = update_data.pop('items', None)

        # Build dynamic update for other fields
        if update_data:
            update_fields = []
            params = []
            param_idx = 1

            for field, value in update_data.items():
                if field == 'pricing_type' and value:
                    value = value.value
                update_fields.append(f"{field} = ${param_idx}")
                params.append(value)
                param_idx += 1

            if update_fields:
                update_fields.append("updated_at = NOW()")
                query = f"""
                    UPDATE promotions
                    SET {', '.join(update_fields)}
                    WHERE id = ${param_idx}
                """
                params.append(promo_id)
                await conn.execute(query, *params)

        # Validate quantity_available against area capacities
        quantity_available = update_data.get('quantity_available') if update_data else None
        if quantity_available is not None or items is not None:
            # Get items to validate (new items or existing)
            items_to_check = items
            if items_to_check is None:
                # Get existing items from DB
                existing_items = await conn.fetch(
                    "SELECT area_id, quantity FROM promotion_items WHERE promotion_id = $1",
                    promo_id
                )
                items_to_check = [type('Item', (), {'area_id': r['area_id'], 'quantity': r['quantity']})() for r in existing_items]

            # Get quantity_available to validate (new or existing)
            qty_to_check = quantity_available
            if qty_to_check is None and 'quantity_available' not in (update_data or {}):
                qty_row = await conn.fetchrow(
                    "SELECT quantity_available FROM promotions WHERE id = $1",
                    promo_id
                )
                qty_to_check = qty_row['quantity_available'] if qty_row else None

            if qty_to_check is not None and items_to_check:
                max_available = await calculate_max_promotion_uses(conn, items_to_check)
                if max_available is not None and qty_to_check > max_available:
                    raise ValidationError(
                        f"Cantidad disponible ({qty_to_check}) excede el maximo permitido "
                        f"segun la capacidad de las areas ({max_available})"
                    )

        # Update items if provided
        if items is not None:
            # Helper to get values from dict or object
            def get_val(item, key):
                return item.get(key) if isinstance(item, dict) else getattr(item, key)

            # Get area_ids from items
            area_ids = [get_val(item, 'area_id') for item in items]

            # Verify all areas belong to cluster
            if area_ids and not await verify_areas_in_cluster(conn, area_ids, cluster_id):
                raise ValidationError("One or more areas do not belong to this cluster")

            # Delete existing items
            await conn.execute(
                "DELETE FROM promotion_items WHERE promotion_id = $1",
                promo_id
            )

            # Create new items
            for item in items:
                await conn.execute("""
                    INSERT INTO promotion_items (promotion_id, area_id, quantity)
                    VALUES ($1, $2, $3)
                """, promo_id, get_val(item, 'area_id'), get_val(item, 'quantity'))

        logger.info(f"Updated promotion: {promo_id}")

        return await get_promotion_by_id(promo_id, cluster_id, profile_id, tenant_id)


async def delete_promotion(
    promo_id: str,
    cluster_id: int,
    profile_id: str,
    tenant_id: str
) -> bool:
    """Delete a promotion"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            return False

        # Verify promotion exists in cluster
        existing = await conn.fetchrow(
            "SELECT id FROM promotions WHERE id = $1 AND cluster_id = $2",
            promo_id, cluster_id
        )

        if not existing:
            return False

        # Delete (cascade will remove promotion_items entries)
        result = await conn.execute(
            "DELETE FROM promotions WHERE id = $1",
            promo_id
        )

        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"Deleted promotion: {promo_id}")
        return deleted


async def increment_promotion_uses(promo_id: str, quantity: int = 1) -> bool:
    """Increment the uses count of a promotion after use"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE promotions
            SET uses_count = uses_count + $2,
                updated_at = NOW()
            WHERE id = $1
              AND (quantity_available IS NULL OR (quantity_available - uses_count) >= $2)
        """, promo_id, quantity)

        return result == "UPDATE 1"


async def get_active_promotion_for_area(area_id: int) -> Optional[dict]:
    """Get the active promotion for an area (used by pricing, for auto-apply promotions)"""
    # Note: Currently promotions require codes, so this returns None
    # In future, could add auto-apply promotions without codes
    return None


async def get_public_promotions(cluster_id: int) -> List[dict]:
    """Get active promotions for public event view"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify event is public
        event = await conn.fetchrow("""
            SELECT id FROM clusters
            WHERE id = $1 AND is_active = true AND shadowban = false
        """, cluster_id)

        if not event:
            return []

        now = datetime.now(timezone.utc)

        # Get active promotions
        promos = await conn.fetch("""
            SELECT
                p.id,
                p.promotion_name,
                p.description,
                p.pricing_type,
                p.pricing_value,
                p.quantity_available,
                p.uses_count
            FROM promotions p
            WHERE p.cluster_id = $1
              AND p.is_active = true
              AND p.start_time <= $2
              AND (p.end_time IS NULL OR p.end_time > $2)
              AND (p.quantity_available IS NULL OR (p.quantity_available - p.uses_count) > 0)
            ORDER BY p.priority_order ASC
        """, cluster_id, now)

        result = []
        for promo in promos:
            # Get items for this promotion
            items_rows = await conn.fetch("""
                SELECT a.id as area_id, a.area_name, a.price as area_price, pi.quantity
                FROM promotion_items pi
                JOIN areas a ON pi.area_id = a.id
                WHERE pi.promotion_id = $1
            """, promo['id'])

            items = [{
                'area_id': r['area_id'],
                'quantity': r['quantity'],
                'area_name': r['area_name'],
                'area_price': float(r['area_price']) if r['area_price'] else 0
            } for r in items_rows]

            # Calculate totals
            total_tickets = sum(item['quantity'] for item in items)
            original_price = sum(item['area_price'] * item['quantity'] for item in items)

            # Calculate final price based on pricing type
            pricing_type = promo['pricing_type']
            pricing_value = float(promo['pricing_value'])

            if pricing_type == 'percentage':
                discount = original_price * (pricing_value / 100)
                final_price = original_price - discount
            elif pricing_type == 'fixed_discount':
                discount = pricing_value
                final_price = max(0, original_price - discount)
            elif pricing_type == 'fixed_price':
                final_price = pricing_value
                discount = original_price - final_price
            else:
                final_price = original_price
                discount = 0

            result.append({
                'id': str(promo['id']),
                'promotion_name': promo['promotion_name'],
                'description': promo['description'],
                'pricing_type': pricing_type,
                'pricing_value': pricing_value,
                'total_tickets': total_tickets,
                'original_price': original_price,
                'final_price': final_price,
                'savings': discount,
                'items': items
            })

        return result


# Aliases for backwards compatibility
get_promotions = get_promotions_by_cluster
decrement_promotion_quantity = increment_promotion_uses
