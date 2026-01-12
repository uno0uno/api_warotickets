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
        # Verify ownership and tenant
        event = await conn.fetchrow(
            "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            cluster_id, profile_id, tenant_id
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
                    SELECT ass.stage_name FROM area_sale_stages ass
                    WHERE ass.area_id = a.id
                      AND ass.is_active = true
                      AND ass.start_time <= NOW()
                      AND (ass.end_time IS NULL OR ass.end_time > NOW())
                      AND ass.quantity_available > 0
                    ORDER BY ass.priority_order ASC
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
            WHERE a.id = $1 AND a.cluster_id = $2 AND c.profile_id = $3 AND c.tenant_id = $4
        """, area_id, cluster_id, profile_id, tenant_id)

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
        # Verify event ownership and tenant
        event = await conn.fetchrow(
            "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            cluster_id, profile_id, tenant_id
        )
        if not event:
            raise ValidationError("Event not found or access denied")

        # Serialize extra_attributes to JSON string
        extra_attrs_json = json.dumps(data.extra_attributes) if data.extra_attributes else '{}'

        row = await conn.fetchrow("""
            INSERT INTO areas (
                cluster_id, area_name, description, capacity, price, currency,
                status, nomenclature_letter, unit_capacity, service, extra_attributes,
                created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, 'available', $7, $8, $9, $10, NOW(), NOW()
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
            data.service,
            extra_attrs_json
        )

        area_id = row['id']
        logger.info(f"Created area: {area_id} - {data.area_name} (cluster: {cluster_id})")

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
    """Update an existing area"""
    async with get_db_connection() as conn:
        # Verify ownership, tenant and cluster
        existing = await conn.fetchrow("""
            SELECT a.id FROM areas a
            JOIN clusters c ON a.cluster_id = c.id
            WHERE a.id = $1 AND a.cluster_id = $2 AND c.profile_id = $3 AND c.tenant_id = $4
        """, area_id, cluster_id, profile_id, tenant_id)

        if not existing:
            return None

        # Build dynamic update query
        update_fields = []
        params = []
        param_idx = 1

        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            # Serialize extra_attributes dict to JSON string
            if field == 'extra_attributes' and isinstance(value, dict):
                value = json.dumps(value)
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
            WHERE a.id = $1 AND a.cluster_id = $2 AND c.profile_id = $3 AND c.tenant_id = $4
        """, area_id, cluster_id, profile_id, tenant_id)

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
            SELECT stage_name FROM area_sale_stages
            WHERE area_id = $1
              AND is_active = true
              AND start_time <= NOW()
              AND (end_time IS NULL OR end_time > NOW())
              AND quantity_available > 0
            ORDER BY priority_order ASC
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
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id AND u.status = 'available') as units_available
            FROM areas a
            WHERE a.cluster_id = $1 AND a.status = 'available'
            ORDER BY a.price ASC
        """, cluster_id)

        areas = []
        for row in rows:
            area_dict = dict(row)
            current_price = await _calculate_current_price(conn, row['id'], row['price'])
            area_dict['current_price'] = current_price
            area_dict['active_sale_stage'] = None
            areas.append(AreaSummary(**area_dict))

        return areas


async def _calculate_current_price(conn, area_id: int, base_price: Decimal) -> Decimal:
    """Calculate current price with active sale stage"""
    sale_stage = await conn.fetchrow("""
        SELECT price_adjustment_type, price_adjustment_value
        FROM area_sale_stages
        WHERE area_id = $1
          AND is_active = true
          AND start_time <= NOW()
          AND (end_time IS NULL OR end_time > NOW())
          AND quantity_available > 0
        ORDER BY priority_order ASC
        LIMIT 1
    """, area_id)

    if not sale_stage:
        return base_price

    adjustment_type = sale_stage['price_adjustment_type']
    adjustment_value = Decimal(str(sale_stage['price_adjustment_value']))

    if adjustment_type == 'percentage':
        # Negative percentage = discount, positive = increase
        return base_price * (1 + adjustment_value / 100)
    elif adjustment_type == 'fixed':
        return base_price + adjustment_value
    else:
        return base_price


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
            '{}'
        ))

    # Bulk insert
    await conn.executemany("""
        INSERT INTO units (
            area_id, status, nomenclature_letter_area,
            nomenclature_number_area, nomenclature_number_unit, extra_attributes,
            created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
    """, units_data)

    logger.info(f"Generated {capacity} units for area {area_id}")
