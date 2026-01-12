import logging
import json
from typing import Optional, List
from app.database import get_db_connection
from app.models.unit import Unit, UnitUpdate, UnitSummary, UnitsMapView
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


def _parse_extra_attributes(value) -> dict:
    """Parse extra_attributes from DB (may come as string or dict)"""
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


def generate_display_name(letter: str, number: int) -> str:
    """Generate display name for a unit"""
    if letter:
        return f"{letter}-{number}"
    return str(number)


async def get_units_by_area(
    cluster_id: int,
    area_id: int,
    profile_id: str,
    tenant_id: str,
    status: Optional[str] = None,
    limit: int = 1000,
    offset: int = 0
) -> List[UnitSummary]:
    """Get units for an area with ownership, cluster and tenant validation"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify ownership, cluster and tenant
        area = await conn.fetchrow("""
            SELECT a.id FROM areas a
            JOIN clusters c ON a.cluster_id = c.id
            WHERE a.id = $1 AND c.id = $2 AND c.profile_id = $3 AND c.tenant_id = $4
        """, area_id, cluster_id, profile_id, tenant_id)

        if not area:
            return []

        query = """
            SELECT id, area_id, status,
                   nomenclature_letter_area,
                   nomenclature_number_unit
            FROM units
            WHERE area_id = $1
        """
        params = [area_id]
        param_idx = 2

        if status:
            query += f" AND status = ${param_idx}"
            params.append(status)
            param_idx += 1

        query += f" ORDER BY nomenclature_number_unit ASC LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.extend([limit, offset])

        rows = await conn.fetch(query, *params)

        units = []
        for row in rows:
            unit_dict = dict(row)
            unit_dict['display_name'] = generate_display_name(
                row['nomenclature_letter_area'] or '',
                row['nomenclature_number_unit'] or row['id']
            )
            units.append(UnitSummary(**unit_dict))

        return units


async def get_unit_by_id(
    cluster_id: int,
    unit_id: int,
    profile_id: str,
    tenant_id: str
) -> Optional[Unit]:
    """Get unit by ID with ownership, cluster and tenant validation"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT u.* FROM units u
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE u.id = $1 AND c.id = $2 AND c.profile_id = $3 AND c.tenant_id = $4
        """, unit_id, cluster_id, profile_id, tenant_id)

        if not row:
            return None

        unit_dict = dict(row)
        unit_dict['display_name'] = generate_display_name(
            row['nomenclature_letter_area'] or '',
            row['nomenclature_number_unit'] or row['id']
        )
        if 'extra_attributes' in unit_dict:
            unit_dict['extra_attributes'] = _parse_extra_attributes(unit_dict['extra_attributes'])

        return Unit(**unit_dict)


async def update_unit_status(
    cluster_id: int,
    unit_id: int,
    profile_id: str,
    tenant_id: str,
    data: UnitUpdate
) -> Optional[Unit]:
    """Update unit status only"""
    async with get_db_connection() as conn:
        # Verify ownership, cluster and tenant
        existing = await conn.fetchrow("""
            SELECT u.id, u.status FROM units u
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE u.id = $1 AND c.id = $2 AND c.profile_id = $3 AND c.tenant_id = $4
        """, unit_id, cluster_id, profile_id, tenant_id)

        if not existing:
            return None

        # Validate status transitions
        if data.status and existing['status'] == 'sold':
            raise ValidationError("Cannot change status of sold unit")

        if not data.status:
            return await get_unit_by_id(cluster_id, unit_id, profile_id, tenant_id)

        await conn.fetchrow("""
            UPDATE units
            SET status = $1, updated_at = NOW()
            WHERE id = $2
            RETURNING *
        """, data.status, unit_id)

        return await get_unit_by_id(cluster_id, unit_id, profile_id, tenant_id)


async def get_available_units(
    cluster_id: int,
    area_id: int,
    quantity: int = 1
) -> List[UnitSummary]:
    """Get available units for purchase (public) with cluster validation"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify area belongs to cluster
        area = await conn.fetchrow("""
            SELECT a.id FROM areas a
            WHERE a.id = $1 AND a.cluster_id = $2
        """, area_id, cluster_id)

        if not area:
            return []

        rows = await conn.fetch("""
            SELECT id, area_id, status, nomenclature_letter_area, nomenclature_number_unit
            FROM units
            WHERE area_id = $1 AND status = 'available'
            ORDER BY nomenclature_number_unit ASC
            LIMIT $2
        """, area_id, quantity)

        units = []
        for row in rows:
            unit_dict = dict(row)
            unit_dict['display_name'] = generate_display_name(
                row['nomenclature_letter_area'] or '',
                row['nomenclature_number_unit'] or row['id']
            )
            units.append(UnitSummary(**unit_dict))

        return units


async def reserve_units(unit_ids: List[int], reservation_id: str) -> int:
    """Reserve units for a reservation (atomic operation)"""
    async with get_db_connection() as conn:
        # Lock and update only available units
        result = await conn.execute("""
            UPDATE units
            SET status = 'reserved', updated_at = NOW()
            WHERE id = ANY($1) AND status = 'available'
        """, unit_ids)

        count = int(result.split()[-1])

        if count != len(unit_ids):
            # Rollback - some units were not available
            await conn.execute("""
                UPDATE units
                SET status = 'available', updated_at = NOW()
                WHERE id = ANY($1) AND status = 'reserved'
            """, unit_ids)
            raise ValidationError(
                f"Only {count} of {len(unit_ids)} units were available",
                {"requested": len(unit_ids), "available": count}
            )

        logger.info(f"Reserved {count} units for reservation {reservation_id}")
        return count


async def release_units(unit_ids: List[int]) -> int:
    """Release reserved units back to available"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE units
            SET status = 'available', updated_at = NOW()
            WHERE id = ANY($1) AND status = 'reserved'
        """, unit_ids)

        count = int(result.split()[-1])
        logger.info(f"Released {count} units back to available")
        return count


async def mark_units_sold(unit_ids: List[int]) -> int:
    """Mark units as sold after payment confirmation"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE units
            SET status = 'sold', updated_at = NOW()
            WHERE id = ANY($1) AND status = 'reserved'
        """, unit_ids)

        count = int(result.split()[-1])
        logger.info(f"Marked {count} units as sold")
        return count


async def get_units_map(cluster_id: int, area_id: int) -> Optional[UnitsMapView]:
    """Get units map view for an area (for seat selection UI) with cluster validation"""
    async with get_db_connection(use_transaction=False) as conn:
        area = await conn.fetchrow("""
            SELECT id, area_name, extra_attributes
            FROM areas WHERE id = $1 AND cluster_id = $2
        """, area_id, cluster_id)

        if not area:
            return None

        rows = await conn.fetch("""
            SELECT id, area_id, status, nomenclature_letter_area, nomenclature_number_unit
            FROM units
            WHERE area_id = $1
            ORDER BY nomenclature_number_unit ASC
        """, area_id)

        units = []
        for row in rows:
            unit_dict = dict(row)
            unit_dict['display_name'] = generate_display_name(
                row['nomenclature_letter_area'] or '',
                row['nomenclature_number_unit'] or row['id']
            )
            units.append(UnitSummary(**unit_dict))

        extra_attrs = _parse_extra_attributes(area['extra_attributes'])
        return UnitsMapView(
            area_id=area_id,
            area_name=area['area_name'],
            total_units=len(units),
            units=units,
            layout=extra_attrs.get('layout') if extra_attrs else None
        )
