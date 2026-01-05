import logging
from typing import Optional, List
from app.database import get_db_connection
from app.models.unit import (
    Unit, UnitCreate, UnitUpdate, UnitSummary,
    UnitBulkCreate, UnitBulkUpdate, UnitBulkResponse,
    UnitWithArea, UnitsMapView
)
from app.core.exceptions import ValidationError, DatabaseError

logger = logging.getLogger(__name__)


def generate_display_name(letter: str, number: int) -> str:
    """Generate display name for a unit"""
    if letter:
        return f"{letter}-{number}"
    return str(number)


async def get_units_by_area(
    area_id: int,
    profile_id: str,
    status: Optional[str] = None,
    limit: int = 1000,
    offset: int = 0
) -> List[UnitSummary]:
    """Get units for an area with ownership validation"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify ownership
        area = await conn.fetchrow("""
            SELECT a.id FROM areas a
            JOIN clusters c ON a.cluster_id = c.id
            WHERE a.id = $1 AND c.profile_id = $2
        """, area_id, profile_id)

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


async def get_unit_by_id(unit_id: int, profile_id: str) -> Optional[Unit]:
    """Get unit by ID with ownership validation"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT u.* FROM units u
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE u.id = $1 AND c.profile_id = $2
        """, unit_id, profile_id)

        if not row:
            return None

        unit_dict = dict(row)
        unit_dict['display_name'] = generate_display_name(
            row['nomenclature_letter_area'] or '',
            row['nomenclature_number_unit'] or row['id']
        )

        return Unit(**unit_dict)


async def create_unit(profile_id: str, data: UnitCreate) -> Unit:
    """Create a single unit"""
    async with get_db_connection() as conn:
        # Verify area ownership
        area = await conn.fetchrow("""
            SELECT a.id FROM areas a
            JOIN clusters c ON a.cluster_id = c.id
            WHERE a.id = $1 AND c.profile_id = $2
        """, data.area_id, profile_id)

        if not area:
            raise ValidationError("Area not found or access denied")

        row = await conn.fetchrow("""
            INSERT INTO units (
                area_id, status, nomenclature_letter_area,
                nomenclature_number_area, nomenclature_number_unit,
                extra_attributes, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
            RETURNING *
        """,
            data.area_id,
            data.status,
            data.nomenclature_letter_area,
            data.nomenclature_number_area,
            data.nomenclature_number_unit,
            data.extra_attributes or {}
        )

        unit_dict = dict(row)
        unit_dict['display_name'] = generate_display_name(
            row['nomenclature_letter_area'] or '',
            row['nomenclature_number_unit'] or row['id']
        )

        logger.info(f"Created unit: {row['id']}")
        return Unit(**unit_dict)


async def create_units_bulk(profile_id: str, data: UnitBulkCreate) -> UnitBulkResponse:
    """Create multiple units at once"""
    async with get_db_connection() as conn:
        # Verify area ownership
        area = await conn.fetchrow("""
            SELECT a.id, a.capacity,
                (SELECT COUNT(*) FROM units u WHERE u.area_id = a.id) as existing_count
            FROM areas a
            JOIN clusters c ON a.cluster_id = c.id
            WHERE a.id = $1 AND c.profile_id = $2
        """, data.area_id, profile_id)

        if not area:
            raise ValidationError("Area not found or access denied")

        # Check capacity
        if area['existing_count'] + data.quantity > area['capacity']:
            raise ValidationError(
                f"Cannot create {data.quantity} units. Area capacity: {area['capacity']}, existing: {area['existing_count']}",
                {"capacity": area['capacity'], "existing": area['existing_count']}
            )

        # Prepare bulk insert data
        units_data = []
        for i in range(data.quantity):
            unit_number = data.start_number + i
            units_data.append((
                data.area_id,
                data.status,
                data.nomenclature_prefix,
                None,
                unit_number,
                {}
            ))

        # Bulk insert
        await conn.executemany("""
            INSERT INTO units (
                area_id, status, nomenclature_letter_area,
                nomenclature_number_area, nomenclature_number_unit,
                extra_attributes, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
        """, units_data)

        # Fetch created units
        rows = await conn.fetch("""
            SELECT id, area_id, status, nomenclature_letter_area, nomenclature_number_unit
            FROM units
            WHERE area_id = $1
            ORDER BY id DESC
            LIMIT $2
        """, data.area_id, data.quantity)

        units = []
        for row in rows:
            unit_dict = dict(row)
            unit_dict['display_name'] = generate_display_name(
                row['nomenclature_letter_area'] or '',
                row['nomenclature_number_unit'] or row['id']
            )
            units.append(UnitSummary(**unit_dict))

        logger.info(f"Created {data.quantity} units for area {data.area_id}")

        return UnitBulkResponse(
            total_created=data.quantity,
            units=list(reversed(units))
        )


async def update_unit(unit_id: int, profile_id: str, data: UnitUpdate) -> Optional[Unit]:
    """Update a unit"""
    async with get_db_connection() as conn:
        # Verify ownership
        existing = await conn.fetchrow("""
            SELECT u.id, u.status FROM units u
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE u.id = $1 AND c.profile_id = $2
        """, unit_id, profile_id)

        if not existing:
            return None

        # Validate status transitions
        if data.status and existing['status'] == 'sold':
            raise ValidationError("Cannot change status of sold unit")

        # Build dynamic update
        update_fields = []
        params = []
        param_idx = 1

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            update_fields.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        if not update_fields:
            return await get_unit_by_id(unit_id, profile_id)

        update_fields.append("updated_at = NOW()")

        query = f"""
            UPDATE units
            SET {', '.join(update_fields)}
            WHERE id = ${param_idx}
            RETURNING *
        """
        params.append(unit_id)

        await conn.fetchrow(query, *params)
        logger.info(f"Updated unit: {unit_id}")

        return await get_unit_by_id(unit_id, profile_id)


async def update_units_bulk(profile_id: str, data: UnitBulkUpdate) -> int:
    """Update multiple units at once"""
    async with get_db_connection() as conn:
        # Verify ownership of all units
        owned = await conn.fetch("""
            SELECT u.id FROM units u
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE u.id = ANY($1) AND c.profile_id = $2
        """, data.unit_ids, profile_id)

        owned_ids = [row['id'] for row in owned]
        if len(owned_ids) != len(data.unit_ids):
            raise ValidationError("Some units not found or access denied")

        # Build update
        update_fields = ["updated_at = NOW()"]
        params = [data.unit_ids]
        param_idx = 2

        if data.status:
            update_fields.append(f"status = ${param_idx}")
            params.append(data.status)
            param_idx += 1

        if data.extra_attributes:
            update_fields.append(f"extra_attributes = ${param_idx}")
            params.append(data.extra_attributes)
            param_idx += 1

        result = await conn.execute(f"""
            UPDATE units
            SET {', '.join(update_fields)}
            WHERE id = ANY($1) AND status != 'sold'
        """, *params)

        count = int(result.split()[-1])
        logger.info(f"Bulk updated {count} units")
        return count


async def delete_unit(unit_id: int, profile_id: str) -> bool:
    """Delete a unit (only if available or blocked)"""
    async with get_db_connection() as conn:
        # Verify ownership and status
        existing = await conn.fetchrow("""
            SELECT u.id, u.status FROM units u
            JOIN areas a ON u.area_id = a.id
            JOIN clusters c ON a.cluster_id = c.id
            WHERE u.id = $1 AND c.profile_id = $2
        """, unit_id, profile_id)

        if not existing:
            return False

        if existing['status'] in ['sold', 'reserved']:
            raise ValidationError(f"Cannot delete unit with status: {existing['status']}")

        result = await conn.execute("DELETE FROM units WHERE id = $1", unit_id)
        deleted = result == "DELETE 1"

        if deleted:
            logger.info(f"Deleted unit: {unit_id}")
        return deleted


async def get_available_units(
    area_id: int,
    quantity: int = 1
) -> List[UnitSummary]:
    """Get available units for purchase (public)"""
    async with get_db_connection(use_transaction=False) as conn:
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


async def get_units_map(area_id: int) -> Optional[UnitsMapView]:
    """Get units map view for an area (for seat selection UI)"""
    async with get_db_connection(use_transaction=False) as conn:
        area = await conn.fetchrow("""
            SELECT id, area_name, extra_attributes
            FROM areas WHERE id = $1
        """, area_id)

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

        return UnitsMapView(
            area_id=area_id,
            area_name=area['area_name'],
            total_units=len(units),
            units=units,
            layout=area['extra_attributes'].get('layout') if area['extra_attributes'] else None
        )
