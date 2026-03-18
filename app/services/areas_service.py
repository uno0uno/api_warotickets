import logging
import json
from typing import Optional, List
from decimal import Decimal
from app.database import get_db_connection
from app.models.area import (
    Area, AreaCreate, AreaUpdate, AreaSummary,
    AreaAvailability, AreaBulkCreate
)
from app.core.exceptions import ValidationError, DatabaseError

logger = logging.getLogger(__name__)


# Service fee configuration (from COTIZACION_WARO_TICKETS_2026.pdf)
# Formula: price * 3.26% + $1,894 fixed (flat — no capacity tiers)
SERVICE_FEE_RATE  = Decimal('0.0326')
SERVICE_FEE_FIXED = Decimal('1894')


def calculate_service_fee(price: Decimal) -> Decimal:
    """
    Calculate service fee per ticket.
    Fee = price * 3.26% + $1,894 fixed, rounded to nearest peso.
    Returns 0 for free tickets.
    """
    if price <= 0:
        return Decimal('0')
    return (price * SERVICE_FEE_RATE + SERVICE_FEE_FIXED).quantize(Decimal('1'))


async def _recalculate_cluster_service_fees(conn, cluster_id: int) -> None:
    """
    Recalculate areas.service for ALL active areas in a cluster using the flat fee formula.
    Executed as a single UPDATE query — no Python loop needed.

    Called whenever area price or capacity changes (area created, updated, or deleted).
    Areas with price = 0 keep service = 0.
    """
    await conn.execute("""
        UPDATE areas
        SET service = CASE
            WHEN price <= 0 THEN 0
            ELSE ROUND((price * 0.0326 + 1894)::numeric, 0)
        END,
        updated_at = NOW()
        WHERE cluster_id = $1
          AND status != 'disabled'
    """, cluster_id)


def _parse_extra_attributes(value):
    """Parse extra_attributes from string to dict if needed"""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


async def get_areas_by_event(
    cluster_id: int,
    profile_id: str,
    tenant_id: str,
    include_stats: bool = True
) -> List[AreaSummary]:
    """Get all areas for an event with availability stats"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify tenant ownership (any tenant member can view)
        event = await conn.fetchrow(
            "SELECT id FROM clusters WHERE id = $1 AND tenant_id = $2",
            cluster_id, tenant_id
        )
        if not event:
            return []

        query = """
            SELECT
                a.id,
                a.area_name,
                a.description,
                a.capacity,
                a.price,
                a.currency,
                a.status,
                a.nomenclature_letter,
                a.service,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'available') as units_available,
                (
                    SELECT ss.stage_name FROM sale_stages ss
                    JOIN sale_stage_areas ssa ON ss.id = ssa.sale_stage_id
                    WHERE ssa.area_id = a.id
                      AND ss.is_active = true
                      AND ss.start_time <= NOW()
                      AND (ss.end_time IS NULL OR ss.end_time > NOW())
                      AND (ss.quantity_available - ss.quantity_sold) > 0
                    ORDER BY ss.priority_order ASC
                    LIMIT 1
                ) as active_sale_stage
            FROM areas a
            WHERE a.cluster_id = $1
            ORDER BY a.area_name
        """

        rows = await conn.fetch(query, cluster_id)
        areas = []

        for row in rows:
            area_dict = dict(row)
            # Calculate current price with sale stage
            current_price = await _calculate_current_price(conn, row['id'], row['price'])
            area_dict['current_price'] = current_price
            areas.append(AreaSummary(**area_dict))

        return areas


async def get_area_by_id(
    cluster_id: int,
    area_id: int,
    profile_id: str,
    tenant_id: str
) -> Optional[Area]:
    """Get area by ID with cluster, ownership and tenant validation"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT a.*,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id) as units_total,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'available') as units_available,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'reserved') as units_reserved,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'sold') as units_sold
            FROM areas a
            JOIN clusters c ON a.cluster_id = c.id
            WHERE a.id = $1 AND a.cluster_id = $2 AND c.tenant_id = $3
        """, area_id, cluster_id, tenant_id)

        if not row:
            return None

        area_dict = dict(row)
        # Parse extra_attributes if it's a string
        area_dict['extra_attributes'] = _parse_extra_attributes(area_dict.get('extra_attributes'))

        return Area(**area_dict)


async def create_area(
    cluster_id: int,
    profile_id: str,
    tenant_id: str,
    data: AreaCreate
) -> Area:
    """Create a new area for an event"""
    async with get_db_connection() as conn:
        # Verify tenant ownership and read current total_capacity in one query
        event = await conn.fetchrow(
            "SELECT id, total_capacity FROM clusters WHERE id = $1 AND tenant_id = $2",
            cluster_id, tenant_id
        )
        if not event:
            raise ValidationError("Event not found or access denied")

        # New cluster total = existing total + this area's capacity
        new_total_capacity = (event['total_capacity'] or 0) + data.capacity

        # For asyncpg with jsonb, pass dict directly (not JSON string)
        extra_attrs = data.extra_attributes if data.extra_attributes else {}

        # Calculate service fee using cluster total capacity (not individual area capacity)
        service_fee = calculate_service_fee(Decimal(str(data.price)))
        logger.info(f"Calculated service fee for area: ${service_fee} (price: ${data.price})")

        row = await conn.fetchrow("""
            INSERT INTO areas (
                cluster_id, area_name, description, capacity, price, currency,
                status, nomenclature_letter, unit_capacity, service, extra_attributes,
                created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, 'available', $7, $8, $9, $10::jsonb, NOW(), NOW()
            )
            RETURNING *
        """,
            cluster_id,
            data.area_name,
            data.description,
            data.capacity,
            data.price,
            data.currency,
            data.nomenclature_letter,
            data.unit_capacity,
            float(service_fee),  # Store calculated fee, not user-provided
            json.dumps(extra_attrs)
        )

        area_id = row['id']
        logger.info(f"Created area: {area_id} - {data.area_name} (cluster: {cluster_id})")

        # Update cluster total_capacity and recalculate service fees for all areas
        await conn.execute(
            "UPDATE clusters SET total_capacity = $1 WHERE id = $2",
            new_total_capacity, cluster_id
        )
        await _recalculate_cluster_service_fees(conn, cluster_id)

        # Always generate units based on capacity
        await _generate_units_for_area(
            conn, area_id, data.capacity,
            data.nomenclature_letter or ""
        )

        area_dict = dict(row)
        area_dict['extra_attributes'] = _parse_extra_attributes(area_dict.get('extra_attributes'))
        area_dict['units_total'] = data.capacity
        area_dict['units_available'] = data.capacity
        area_dict['units_reserved'] = 0
        area_dict['units_sold'] = 0

        return Area(**area_dict)


async def update_area(
    cluster_id: int,
    area_id: int,
    profile_id: str,
    tenant_id: str,
    data: AreaUpdate
) -> Optional[Area]:
    """Update an existing area.

    Si cambia capacity o price, recalcula clusters.total_capacity (si aplica)
    y el service fee de TODAS las áreas del cluster.
    Si capacity aumenta, genera las units adicionales.
    Si capacity baja, valida que no haya más unidades activas que la nueva capacidad.
    """
    async with get_db_connection() as conn:
        # Verify ownership, tenant and cluster; fetch current capacity for comparison
        existing = await conn.fetchrow("""
            SELECT a.id, a.capacity FROM areas a
            JOIN clusters c ON a.cluster_id = c.id
            WHERE a.id = $1 AND a.cluster_id = $2 AND c.tenant_id = $3
        """, area_id, cluster_id, tenant_id)

        if not existing:
            return None

        update_data = data.model_dump(exclude_unset=True)

        # Validate capacity reduction doesn't strand sold/reserved units
        if 'capacity' in update_data:
            new_capacity = update_data['capacity']
            old_capacity = existing['capacity']
            if new_capacity < old_capacity:
                active_units = await conn.fetchval("""
                    SELECT COUNT(*) FROM units
                    WHERE area_id = $1 AND status IN ('sold', 'reserved')
                """, area_id)
                if active_units > new_capacity:
                    raise ValidationError(
                        f"No se puede reducir capacidad a {new_capacity}: "
                        f"hay {active_units} unidades vendidas/reservadas",
                        {"active_units": int(active_units), "new_capacity": new_capacity}
                    )

        # service is always recalculated — never accept client-provided value
        update_data.pop('service', None)

        # Build dynamic update query
        update_fields = []
        params = []
        param_idx = 1

        for field, value in update_data.items():
            # Serialize extra_attributes dict to JSON string with cast
            if field == 'extra_attributes' and isinstance(value, dict):
                value = json.dumps(value)
                update_fields.append(f"{field} = ${param_idx}::jsonb")
            else:
                update_fields.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        if not update_fields:
            return await get_area_by_id(cluster_id, area_id, profile_id, tenant_id)

        update_fields.append("updated_at = NOW()")

        query = f"""
            UPDATE areas
            SET {', '.join(update_fields)}
            WHERE id = ${param_idx}
            RETURNING *
        """
        params.append(area_id)

        await conn.fetchrow(query, *params)

        # Recalculate cluster service fees if capacity or price changed
        capacity_changed = 'capacity' in update_data
        price_changed = 'price' in update_data

        if capacity_changed or price_changed:
            # Source of truth: sum from DB after the UPDATE above
            new_total_capacity = await conn.fetchval("""
                SELECT COALESCE(SUM(capacity), 0) FROM areas
                WHERE cluster_id = $1 AND status != 'disabled'
            """, cluster_id)

            if capacity_changed:
                await conn.execute(
                    "UPDATE clusters SET total_capacity = $1 WHERE id = $2",
                    new_total_capacity, cluster_id
                )
                # Generate additional units if capacity increased
                new_cap = update_data['capacity']
                old_cap = existing['capacity']
                if new_cap > old_cap:
                    nomenclature = await conn.fetchval(
                        "SELECT nomenclature_letter FROM areas WHERE id = $1", area_id
                    )
                    await _generate_units_for_area(
                        conn, area_id, new_cap - old_cap, nomenclature or ""
                    )
                    logger.info(
                        f"Generated {new_cap - old_cap} additional units for area {area_id} "
                        f"(capacity: {old_cap} → {new_cap})"
                    )

            await _recalculate_cluster_service_fees(conn, cluster_id)
            logger.info(
                f"Recalculated service fees for cluster {cluster_id} "
                f"(trigger: {'capacity' if capacity_changed else 'price'})"
            )

        return await get_area_by_id(cluster_id, area_id, profile_id, tenant_id)


async def delete_area(
    cluster_id: int,
    area_id: int,
    profile_id: str,
    tenant_id: str
) -> bool:
    """Delete an area (only if no sold tickets or reservations)"""
    async with get_db_connection() as conn:
        # Verify ownership, tenant, cluster and check for sold/reserved tickets
        check = await conn.fetchrow("""
            SELECT a.id,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'sold') as sold_count,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'reserved') as reserved_count
            FROM areas a
            JOIN clusters c ON a.cluster_id = c.id
            WHERE a.id = $1 AND a.cluster_id = $2 AND c.tenant_id = $3
        """, area_id, cluster_id, tenant_id)

        if not check:
            return False

        if check['sold_count'] > 0:
            raise ValidationError(
                f"Cannot delete area with {check['sold_count']} sold tickets",
                {"sold_count": check['sold_count']}
            )

        if check['reserved_count'] > 0:
            raise ValidationError(
                f"Cannot delete area with {check['reserved_count']} active reservations",
                {"reserved_count": check['reserved_count']}
            )

        # Delete units first
        await conn.execute("DELETE FROM units WHERE area_id = $1", area_id)

        # Delete area
        result = await conn.execute("DELETE FROM areas WHERE id = $1", area_id)

        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"Deleted area: {area_id} (cluster: {cluster_id})")

            # Recalculate cluster total_capacity and service fees for remaining areas
            new_total_capacity = await conn.fetchval(
                "SELECT COALESCE(SUM(capacity), 0) FROM areas WHERE cluster_id = $1 AND status != 'disabled'",
                cluster_id
            )
            await conn.execute(
                "UPDATE clusters SET total_capacity = $1 WHERE id = $2",
                new_total_capacity, cluster_id
            )
            await _recalculate_cluster_service_fees(conn, cluster_id)

        return deleted


async def get_area_availability(cluster_id: int, area_id: int) -> Optional[AreaAvailability]:
    """Get availability info for an area (public)"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT
                a.id as area_id,
                a.area_name,
                a.price as base_price,
                a.currency,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id) as total_units,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'available') as available_units,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'reserved') as reserved_units,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'sold') as sold_units
            FROM areas a
            WHERE a.id = $1 AND a.cluster_id = $2 AND a.status = 'available'
        """, area_id, cluster_id)

        if not row:
            return None

        availability_dict = dict(row)

        # Calculate current price with sale stage
        current_price = await _calculate_current_price(conn, area_id, row['base_price'])
        availability_dict['current_price'] = current_price

        # Get active sale stage name
        sale_stage = await conn.fetchrow("""
            SELECT ss.stage_name FROM sale_stages ss
            JOIN sale_stage_areas ssa ON ss.id = ssa.sale_stage_id
            WHERE ssa.area_id = $1
              AND ss.is_active = true
              AND ss.start_time <= NOW()
              AND (ss.end_time IS NULL OR ss.end_time > NOW())
              AND (ss.quantity_available - ss.quantity_sold) > 0
            ORDER BY ss.priority_order ASC
            LIMIT 1
        """, area_id)

        availability_dict['active_sale_stage'] = sale_stage['stage_name'] if sale_stage else None
        availability_dict['active_promotion'] = None

        return AreaAvailability(**availability_dict)


async def get_public_areas(cluster_id: int) -> List[AreaSummary]:
    """Get areas for public event view"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify event is public
        event = await conn.fetchrow("""
            SELECT id FROM clusters
            WHERE id = $1 AND is_active = true AND shadowban = false
        """, cluster_id)

        if not event:
            return []

        rows = await conn.fetch("""
            SELECT
                a.id,
                a.area_name,
                a.description,
                a.capacity,
                a.price,
                a.currency,
                a.status,
                a.nomenclature_letter,
                a.service,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'available') as units_available,
                (
                    SELECT ss.stage_name FROM sale_stages ss
                    JOIN sale_stage_areas ssa ON ss.id = ssa.sale_stage_id
                    WHERE ssa.area_id = a.id
                      AND ss.is_active = true
                      AND ss.start_time <= NOW()
                      AND (ss.end_time IS NULL OR ss.end_time > NOW())
                      AND (ss.quantity_available - ss.quantity_sold) > 0
                    ORDER BY ss.priority_order ASC
                    LIMIT 1
                ) as active_sale_stage
            FROM areas a
            WHERE a.cluster_id = $1 AND a.status = 'available'
            ORDER BY a.price ASC
        """, cluster_id)

        areas = []
        for row in rows:
            area_dict = dict(row)
            current_price = await _calculate_current_price(conn, row['id'], row['price'])
            area_dict['current_price'] = current_price
            areas.append(AreaSummary(**area_dict))

        return areas


async def _calculate_current_price(conn, area_id: int, base_price: Decimal) -> Decimal:
    """Calculate current price with active sale stage

    For bundles (quantity > 1), the discount applies to the bundle total,
    and we return the per-ticket price within the bundle.
    Example: 2x1 with $30k discount on $30k tickets = ($60k - $30k) / 2 = $15k per ticket
    """
    sale_stage = await conn.fetchrow("""
        SELECT ss.price_adjustment_type, ss.price_adjustment_value, ssa.quantity
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

    if not sale_stage:
        return base_price

    quantity = sale_stage['quantity'] or 1
    adjustment_type = sale_stage['price_adjustment_type']
    adjustment_value = Decimal(str(sale_stage['price_adjustment_value']))

    if adjustment_type == 'percentage':
        # Percentage applies to base price (same for bundles and single tickets)
        current_price = base_price * (1 + adjustment_value / 100)
    elif adjustment_type == 'fixed':
        # Fixed discount applies to bundle total, then divide by quantity
        # Example: 2 tickets at $30k each, -$30k discount = ($60k - $30k) / 2 = $15k each
        bundle_total = base_price * quantity
        discounted_total = bundle_total + adjustment_value
        current_price = discounted_total / quantity
    elif adjustment_type == 'fixed_price':
        # fixed_price is the total bundle price, divide by quantity for per-ticket
        current_price = adjustment_value / quantity
    else:
        current_price = base_price

    return max(Decimal('0'), current_price)


async def _generate_units_for_area(conn, area_id: int, capacity: int, prefix: str):
    """Generate units for an area"""
    units_data = []
    for i in range(1, capacity + 1):
        units_data.append((
            area_id,
            'available',
            prefix,
            None,
            i,
            '{}'  # JSON string for jsonb column with explicit cast
        ))

    # Bulk insert with explicit jsonb cast
    await conn.executemany("""
        INSERT INTO units (
            area_id, status, nomenclature_letter_area,
            nomenclature_number_area, nomenclature_number_unit, extra_attributes,
            created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, NOW(), NOW())
    """, units_data)

    logger.info(f"Generated {capacity} units for area {area_id}")
