import logging
import json
from typing import Optional, List
from datetime import datetime
from app.database import get_db_connection
from app.models.event import (
    Event, EventCreate, EventUpdate, EventSummary,
    EventImage, EventImageCreate, LegalInfo, LegalInfoCreate,
    EventCreateWithAreas, AreaCreateNested,
    EventUpdateWithAreas, AreaUpdateNested
)
from app.core.exceptions import ValidationError, DatabaseError
import re

logger = logging.getLogger(__name__)


def generate_slug(name: str) -> str:
    """Generate URL-friendly slug from event name"""
    slug = name.lower().strip()
    slug = re.sub(r'[áàäâ]', 'a', slug)
    slug = re.sub(r'[éèëê]', 'e', slug)
    slug = re.sub(r'[íìïî]', 'i', slug)
    slug = re.sub(r'[óòöô]', 'o', slug)
    slug = re.sub(r'[úùüû]', 'u', slug)
    slug = re.sub(r'[ñ]', 'n', slug)
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')
    return slug


async def get_events(
    profile_id: str,
    tenant_id: str,
    is_active: Optional[bool] = None,
    include_shadowban: bool = False,
    limit: int = 50,
    offset: int = 0
) -> List[EventSummary]:
    """Get events for a profile/organizer within a tenant"""
    async with get_db_connection(use_transaction=False) as conn:
        query = """
            SELECT
                c.id,
                c.cluster_name,
                c.slug_cluster,
                c.description,
                c.start_date,
                c.end_date,
                c.cluster_type,
                c.is_active,
                COALESCE(
                    (SELECT ei.image_url FROM event_images ei WHERE ei.cluster_id = c.id AND ei.image_type = 'cover' LIMIT 1),
                    (SELECT i.path FROM images i JOIN cluster_images ci ON ci.image_id = i.id WHERE ci.cluster_id = c.id AND ci.type_image = 'cover' LIMIT 1)
                ) as cover_image_url,
                (SELECT COALESCE(SUM(a.capacity), 0) FROM areas a WHERE a.cluster_id = c.id) as total_capacity,
                (
                    SELECT COUNT(*) FROM units u
                    JOIN areas a ON u.area_id = a.id
                    WHERE a.cluster_id = c.id AND u.status = 'available'
                ) as tickets_available,
                (
                    SELECT COUNT(*) FROM reservation_units ru
                    JOIN units u ON ru.unit_id = u.id
                    JOIN areas a ON u.area_id = a.id
                    WHERE a.cluster_id = c.id AND ru.status IN ('confirmed', 'approved', 'used')
                ) as total_sold,
                (
                    SELECT COUNT(*) FROM reservation_units ru
                    JOIN units u ON ru.unit_id = u.id
                    JOIN areas a ON u.area_id = a.id
                    WHERE a.cluster_id = c.id AND ru.status = 'used'
                ) as total_checked_in,
                (SELECT MIN(a.price) FROM areas a WHERE a.cluster_id = c.id) as min_price,
                (SELECT MAX(a.price) FROM areas a WHERE a.cluster_id = c.id) as max_price
            FROM clusters c
            WHERE c.profile_id = $1 AND c.tenant_id = $2
        """
        params = [profile_id, tenant_id]
        param_idx = 3

        if is_active is not None:
            query += f" AND c.is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1

        if not include_shadowban:
            query += f" AND c.shadowban = false"

        query += f" ORDER BY c.start_date DESC NULLS LAST LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.extend([limit, offset])

        rows = await conn.fetch(query, *params)
        return [EventSummary(**dict(row)) for row in rows]


async def get_event_by_id(event_id: int, profile_id: str, tenant_id: str) -> Optional[Event]:
    """Get event by ID with ownership and tenant validation"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT
                c.*,
                (SELECT COALESCE(SUM(a.capacity), 0) FROM areas a WHERE a.cluster_id = c.id) as total_capacity,
                (
                    SELECT COUNT(*) FROM units u
                    JOIN areas a ON u.area_id = a.id
                    WHERE a.cluster_id = c.id AND u.status IN ('sold', 'reserved')
                ) as tickets_sold,
                (
                    SELECT COUNT(*) FROM units u
                    JOIN areas a ON u.area_id = a.id
                    WHERE a.cluster_id = c.id AND u.status = 'available'
                ) as tickets_available
            FROM clusters c
            WHERE c.id = $1 AND c.profile_id = $2 AND c.tenant_id = $3
        """, event_id, profile_id, tenant_id)

        if not row:
            return None

        event_dict = dict(row)

        # Convert UUID to string
        if event_dict.get('profile_id'):
            event_dict['profile_id'] = str(event_dict['profile_id'])

        # Parse extra_attributes if it's a string
        if isinstance(event_dict.get('extra_attributes'), str):
            try:
                event_dict['extra_attributes'] = json.loads(event_dict['extra_attributes'])
            except (json.JSONDecodeError, TypeError):
                event_dict['extra_attributes'] = {}

        # Get images
        images = await conn.fetch("""
            SELECT ci.*, i.path as image_url
            FROM cluster_images ci
            LEFT JOIN images i ON ci.image_id = i.id
            WHERE ci.cluster_id = $1
        """, event_id)

        # Convert image UUIDs to strings
        event_dict['images'] = []
        for img in images:
            img_dict = dict(img)
            if img_dict.get('image_id'):
                img_dict['image_id'] = str(img_dict['image_id'])
            event_dict['images'].append(img_dict)

        return Event(**event_dict)


async def get_event_by_slug(slug: str, tenant_id: Optional[str] = None) -> Optional[Event]:
    """Get event by slug (public access)"""
    async with get_db_connection(use_transaction=False) as conn:
        query = """
            SELECT
                c.*,
                (SELECT COALESCE(SUM(a.capacity), 0) FROM areas a WHERE a.cluster_id = c.id) as total_capacity,
                (
                    SELECT COUNT(*) FROM units u
                    JOIN areas a ON u.area_id = a.id
                    WHERE a.cluster_id = c.id AND u.status = 'available'
                ) as tickets_available
            FROM clusters c
            WHERE c.slug_cluster = $1
              AND c.is_active = true
              AND c.shadowban = false
        """
        params = [slug]

        if tenant_id:
            query += " AND c.tenant_id = $2"
            params.append(tenant_id)

        row = await conn.fetchrow(query, *params)

        if not row:
            return None

        event_dict = dict(row)
        event_dict['tickets_sold'] = event_dict.get('total_capacity', 0) - event_dict.get('tickets_available', 0)

        # Convert UUID to string
        if event_dict.get('profile_id'):
            event_dict['profile_id'] = str(event_dict['profile_id'])

        # Parse extra_attributes if it's a string
        if isinstance(event_dict.get('extra_attributes'), str):
            try:
                event_dict['extra_attributes'] = json.loads(event_dict['extra_attributes'])
            except (json.JSONDecodeError, TypeError):
                event_dict['extra_attributes'] = {}

        # Get images
        images = await conn.fetch("""
            SELECT ci.*, i.path as image_url
            FROM cluster_images ci
            LEFT JOIN images i ON ci.image_id = i.id
            WHERE ci.cluster_id = $1
        """, row['id'])

        # Convert image UUIDs to strings
        event_dict['images'] = []
        for img in images:
            img_dict = dict(img)
            if img_dict.get('image_id'):
                img_dict['image_id'] = str(img_dict['image_id'])
            event_dict['images'].append(img_dict)

        return Event(**event_dict)


async def create_event(profile_id: str, tenant_id: str, data: EventCreate) -> Event:
    """Create a new event"""
    async with get_db_connection() as conn:
        # Generate slug if not provided
        slug = data.slug_cluster or generate_slug(data.cluster_name)

        # Ensure slug is unique within tenant
        existing = await conn.fetchrow(
            "SELECT id FROM clusters WHERE slug_cluster = $1 AND tenant_id = $2",
            slug, tenant_id
        )
        if existing:
            # Append timestamp to make unique
            slug = f"{slug}-{int(datetime.now().timestamp())}"

        # Serialize extra_attributes to JSON string for asyncpg
        extra_attrs_json = json.dumps(data.extra_attributes) if data.extra_attributes else '{}'

        row = await conn.fetchrow("""
            INSERT INTO clusters (
                profile_id, tenant_id, cluster_name, description, start_date, end_date,
                cluster_type, slug_cluster, extra_attributes, legal_info_id,
                is_active, shadowban, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, true, false, NOW(), NOW()
            )
            RETURNING *
        """,
            profile_id,
            tenant_id,
            data.cluster_name,
            data.description,
            data.start_date,
            data.end_date,
            data.cluster_type,
            slug,
            extra_attrs_json,
            data.legal_info_id
        )

        logger.info(f"Created event: {row['id']} - {data.cluster_name} (tenant: {tenant_id})")

        event_dict = dict(row)

        # Convert UUID to string
        if event_dict.get('profile_id'):
            event_dict['profile_id'] = str(event_dict['profile_id'])

        # Parse extra_attributes if it's a string
        if isinstance(event_dict.get('extra_attributes'), str):
            try:
                event_dict['extra_attributes'] = json.loads(event_dict['extra_attributes'])
            except (json.JSONDecodeError, TypeError):
                event_dict['extra_attributes'] = {}

        event_dict['images'] = []
        event_dict['total_capacity'] = 0
        event_dict['tickets_sold'] = 0
        event_dict['tickets_available'] = 0

        return Event(**event_dict)


async def update_event(event_id: int, profile_id: str, tenant_id: str, data: EventUpdate) -> Optional[Event]:
    """Update an existing event"""
    async with get_db_connection() as conn:
        # Verify ownership and tenant
        existing = await conn.fetchrow(
            "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            event_id, profile_id, tenant_id
        )
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
            return await get_event_by_id(event_id, profile_id, tenant_id)

        update_fields.append("updated_at = NOW()")

        query = f"""
            UPDATE clusters
            SET {', '.join(update_fields)}
            WHERE id = ${param_idx} AND profile_id = ${param_idx + 1} AND tenant_id = ${param_idx + 2}
            RETURNING *
        """
        params.extend([event_id, profile_id, tenant_id])

        await conn.fetchrow(query, *params)

        return await get_event_by_id(event_id, profile_id, tenant_id)


async def delete_event(event_id: int, profile_id: str, tenant_id: str) -> bool:
    """Soft delete an event (set is_active = false)"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE clusters
            SET is_active = false, updated_at = NOW()
            WHERE id = $1 AND profile_id = $2 AND tenant_id = $3
        """, event_id, profile_id, tenant_id)

        deleted = result == "UPDATE 1"
        if deleted:
            logger.info(f"Soft deleted event: {event_id}")
        return deleted


async def add_event_image(event_id: int, profile_id: str, tenant_id: str, data: EventImageCreate) -> Optional[EventImage]:
    """Add image to event"""
    async with get_db_connection() as conn:
        # Verify ownership and tenant
        existing = await conn.fetchrow(
            "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            event_id, profile_id, tenant_id
        )
        if not existing:
            return None

        row = await conn.fetchrow("""
            INSERT INTO cluster_images (cluster_id, image_id, type_image, created_at)
            VALUES ($1, $2, $3, NOW())
            RETURNING *
        """, event_id, data.image_id, data.type_image)

        return EventImage(**dict(row))


async def remove_event_image(event_id: int, profile_id: str, tenant_id: str, image_id: int) -> bool:
    """Remove image from event"""
    async with get_db_connection() as conn:
        # Verify ownership and tenant
        existing = await conn.fetchrow(
            "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            event_id, profile_id, tenant_id
        )
        if not existing:
            return False

        result = await conn.execute("""
            DELETE FROM cluster_images
            WHERE id = $1 AND cluster_id = $2
        """, image_id, event_id)

        return result == "DELETE 1"


async def get_public_events(
    tenant_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    event_type: Optional[str] = None,
    start_date_from: Optional[datetime] = None,
    start_date_to: Optional[datetime] = None,
    city: Optional[str] = None
) -> List[EventSummary]:
    """Get public events (for public listing)"""
    async with get_db_connection(use_transaction=False) as conn:
        query = """
            SELECT
                c.id,
                c.cluster_name,
                c.slug_cluster,
                c.description,
                c.start_date,
                c.end_date,
                c.cluster_type,
                c.is_active,
                COALESCE(
                    (SELECT ei.image_url FROM event_images ei WHERE ei.cluster_id = c.id AND ei.image_type = 'cover' LIMIT 1),
                    (SELECT i.path FROM images i JOIN cluster_images ci ON ci.image_id = i.id WHERE ci.cluster_id = c.id AND ci.type_image = 'cover' LIMIT 1)
                ) as cover_image_url,
                (SELECT COALESCE(SUM(a.capacity), 0) FROM areas a WHERE a.cluster_id = c.id) as total_capacity,
                (
                    SELECT COUNT(*) FROM units u
                    JOIN areas a ON u.area_id = a.id
                    WHERE a.cluster_id = c.id AND u.status = 'available'
                ) as tickets_available,
                (SELECT MIN(a.price) FROM areas a WHERE a.cluster_id = c.id) as min_price,
                (SELECT MAX(a.price) FROM areas a WHERE a.cluster_id = c.id) as max_price
            FROM clusters c
            WHERE c.is_active = true AND c.shadowban = false
              AND EXISTS (SELECT 1 FROM areas a WHERE a.cluster_id = c.id)
        """
        params = []
        param_idx = 1

        if tenant_id:
            query += f" AND c.tenant_id = ${param_idx}"
            params.append(tenant_id)
            param_idx += 1

        if event_type:
            query += f" AND c.cluster_type = ${param_idx}"
            params.append(event_type)
            param_idx += 1

        if start_date_from:
            query += f" AND c.start_date >= ${param_idx}"
            params.append(start_date_from)
            param_idx += 1

        if start_date_to:
            query += f" AND c.start_date <= ${param_idx}"
            params.append(start_date_to)
            param_idx += 1

        if city:
            query += f" AND LOWER(c.extra_attributes->>'city') = LOWER(${param_idx})"
            params.append(city)
            param_idx += 1

        query += f" ORDER BY c.start_date ASC NULLS LAST LIMIT ${param_idx} OFFSET ${param_idx + 1}"
        params.extend([limit, offset])

        rows = await conn.fetch(query, *params)
        return [EventSummary(**dict(row)) for row in rows]


async def create_legal_info(data: LegalInfoCreate) -> LegalInfo:
    """Create legal info record"""
    async with get_db_connection() as conn:
        row = await conn.fetchrow("""
            INSERT INTO legal_info (nit, legal_name, puleb_code, address, city, country)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
        """,
            data.nit, data.legal_name, data.puleb_code,
            data.address, data.city, data.country
        )
        return LegalInfo(**dict(row))


async def create_event_with_areas(
    profile_id: str,
    tenant_id: str,
    data: EventCreateWithAreas
) -> dict:
    """
    Create event with nested areas and auto-generated units in a single transaction.
    Returns dict with event, areas_created count, and units_created count.
    """
    async with get_db_connection() as conn:
        # Generate slug
        slug = data.slug_cluster or generate_slug(data.cluster_name)

        # Ensure unique slug within tenant
        existing = await conn.fetchrow(
            "SELECT id FROM clusters WHERE slug_cluster = $1 AND tenant_id = $2",
            slug, tenant_id
        )
        if existing:
            slug = f"{slug}-{int(datetime.now().timestamp())}"

        # Serialize extra_attributes
        extra_attrs_json = json.dumps(data.extra_attributes) if data.extra_attributes else '{}'

        # Create event
        event_row = await conn.fetchrow("""
            INSERT INTO clusters (
                profile_id, tenant_id, cluster_name, description, start_date, end_date,
                cluster_type, slug_cluster, extra_attributes, legal_info_id,
                is_active, shadowban, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, true, false, NOW(), NOW()
            )
            RETURNING *
        """,
            profile_id, tenant_id, data.cluster_name, data.description,
            data.start_date, data.end_date, data.cluster_type, slug,
            extra_attrs_json, data.legal_info_id
        )

        event_id = event_row['id']
        areas_created = 0
        units_created = 0

        # Create areas if provided
        if data.areas:
            for area_data in data.areas:
                # Serialize area extra_attributes
                area_extra_json = json.dumps(area_data.extra_attributes) if area_data.extra_attributes else '{}'

                area_row = await conn.fetchrow("""
                    INSERT INTO areas (
                        cluster_id, area_name, description, capacity, price, currency,
                        nomenclature_letter, unit_capacity, service, extra_attributes,
                        status, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'available', NOW(), NOW()
                    )
                    RETURNING id
                """,
                    event_id, area_data.area_name, area_data.description,
                    area_data.capacity, area_data.price, area_data.currency,
                    area_data.nomenclature_letter, area_data.unit_capacity,
                    area_data.service, area_extra_json
                )
                areas_created += 1
                area_id = area_row['id']

                # Auto-generate units if requested
                if area_data.auto_generate_units and area_data.capacity > 0:
                    prefix = area_data.nomenclature_letter or ""

                    # Bulk insert units
                    unit_values = []
                    for i in range(1, area_data.capacity + 1):
                        unit_values.append((
                            area_id,
                            prefix,
                            i,
                            i,
                            'available',
                            '{}'
                        ))

                    await conn.executemany("""
                        INSERT INTO units (
                            area_id, nomenclature_letter_area, nomenclature_number_area,
                            nomenclature_number_unit, status, extra_attributes,
                            created_at, updated_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
                    """, unit_values)

                    units_created += area_data.capacity

        logger.info(f"Created event {event_id} with {areas_created} areas and {units_created} units (tenant: {tenant_id})")

        # Build response event
        event_dict = dict(event_row)
        if event_dict.get('profile_id'):
            event_dict['profile_id'] = str(event_dict['profile_id'])
        if isinstance(event_dict.get('extra_attributes'), str):
            try:
                event_dict['extra_attributes'] = json.loads(event_dict['extra_attributes'])
            except (json.JSONDecodeError, TypeError):
                event_dict['extra_attributes'] = {}

        event_dict['images'] = []
        event_dict['total_capacity'] = units_created
        event_dict['tickets_sold'] = 0
        event_dict['tickets_available'] = units_created

        return {
            "event": Event(**event_dict),
            "areas_created": areas_created,
            "units_created": units_created
        }


async def update_event_with_areas(
    event_id: int,
    profile_id: str,
    tenant_id: str,
    data: EventUpdateWithAreas
) -> dict:
    """
    Update event with nested area modifications.
    Validates business rules:
    - Cannot decrease area capacity below sold/reserved units
    - Cannot delete areas with sold/reserved units
    """
    async with get_db_connection() as conn:
        # Verify ownership and tenant
        existing = await conn.fetchrow(
            "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            event_id, profile_id, tenant_id
        )
        if not existing:
            return None

        # Update event fields
        update_data = data.model_dump(exclude_unset=True, exclude={'areas'})
        if update_data:
            update_fields = []
            params = []
            param_idx = 1

            for field, value in update_data.items():
                if field == 'extra_attributes' and isinstance(value, dict):
                    value = json.dumps(value)
                update_fields.append(f"{field} = ${param_idx}")
                params.append(value)
                param_idx += 1

            if update_fields:
                update_fields.append("updated_at = NOW()")
                query = f"""
                    UPDATE clusters
                    SET {', '.join(update_fields)}
                    WHERE id = ${param_idx} AND profile_id = ${param_idx + 1} AND tenant_id = ${param_idx + 2}
                """
                params.extend([event_id, profile_id, tenant_id])
                await conn.execute(query, *params)

        areas_updated = 0
        areas_created = 0
        areas_deleted = 0
        units_created = 0

        # Process areas if provided
        if data.areas:
            for area_data in data.areas:
                if area_data.id:
                    # Existing area - verify it belongs to this event
                    area_row = await conn.fetchrow(
                        "SELECT id, capacity FROM areas WHERE id = $1 AND cluster_id = $2",
                        area_data.id, event_id
                    )
                    if not area_row:
                        raise ValidationError(f"Area {area_data.id} not found in this event")

                    # Get sold/reserved count for this area
                    sold_reserved = await conn.fetchval("""
                        SELECT COUNT(*) FROM units
                        WHERE area_id = $1 AND status IN ('sold', 'reserved')
                    """, area_data.id)

                    if area_data.is_deleted:
                        # Validate no sold/reserved units
                        if sold_reserved > 0:
                            raise ValidationError(
                                f"Cannot delete area '{area_data.id}': has {sold_reserved} sold/reserved units"
                            )
                        # Delete units first, then area
                        await conn.execute("DELETE FROM units WHERE area_id = $1", area_data.id)
                        await conn.execute("DELETE FROM areas WHERE id = $1", area_data.id)
                        areas_deleted += 1
                    else:
                        # Update existing area
                        current_capacity = area_row['capacity']

                        # Validate capacity change
                        if area_data.capacity is not None and area_data.capacity < sold_reserved:
                            raise ValidationError(
                                f"Cannot reduce capacity to {area_data.capacity}: "
                                f"area has {sold_reserved} sold/reserved units"
                            )

                        # Build update query
                        area_update_fields = []
                        area_params = []
                        area_param_idx = 1

                        area_update_data = area_data.model_dump(exclude_unset=True, exclude={'id', 'is_deleted'})
                        for field, value in area_update_data.items():
                            if field == 'extra_attributes' and isinstance(value, dict):
                                value = json.dumps(value)
                            area_update_fields.append(f"{field} = ${area_param_idx}")
                            area_params.append(value)
                            area_param_idx += 1

                        if area_update_fields:
                            area_update_fields.append("updated_at = NOW()")
                            area_query = f"""
                                UPDATE areas SET {', '.join(area_update_fields)}
                                WHERE id = ${area_param_idx}
                            """
                            area_params.append(area_data.id)
                            await conn.execute(area_query, *area_params)
                            areas_updated += 1

                            # If capacity increased, generate additional units
                            if area_data.capacity and area_data.capacity > current_capacity:
                                new_units_count = area_data.capacity - current_capacity

                                # Get last unit number
                                last_unit = await conn.fetchval("""
                                    SELECT COALESCE(MAX(nomenclature_number_unit), 0)
                                    FROM units WHERE area_id = $1
                                """, area_data.id)

                                # Get nomenclature from area
                                area_info = await conn.fetchrow(
                                    "SELECT nomenclature_letter FROM areas WHERE id = $1",
                                    area_data.id
                                )
                                prefix = area_info['nomenclature_letter'] or ""

                                # Generate new units
                                unit_values = []
                                for i in range(1, new_units_count + 1):
                                    unit_num = last_unit + i
                                    unit_values.append((
                                        area_data.id, prefix, unit_num, unit_num, 'available', '{}'
                                    ))

                                await conn.executemany("""
                                    INSERT INTO units (
                                        area_id, nomenclature_letter_area, nomenclature_number_area,
                                        nomenclature_number_unit, status, extra_attributes,
                                        created_at, updated_at
                                    ) VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
                                """, unit_values)

                                units_created += new_units_count
                else:
                    # New area - create it
                    area_extra_json = json.dumps(area_data.extra_attributes) if area_data.extra_attributes else '{}'

                    new_area = await conn.fetchrow("""
                        INSERT INTO areas (
                            cluster_id, area_name, description, capacity, price, currency,
                            nomenclature_letter, unit_capacity, service, extra_attributes,
                            status, created_at, updated_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'available', NOW(), NOW()
                        )
                        RETURNING id
                    """,
                        event_id, area_data.area_name, area_data.description,
                        area_data.capacity, area_data.price, area_data.currency or 'COP',
                        area_data.nomenclature_letter, area_data.unit_capacity,
                        area_data.service, area_extra_json
                    )
                    areas_created += 1

                    # Auto-generate units for new area
                    if area_data.capacity and area_data.capacity > 0:
                        prefix = area_data.nomenclature_letter or ""
                        unit_values = []
                        for i in range(1, area_data.capacity + 1):
                            unit_values.append((
                                new_area['id'], prefix, i, i, 'available', '{}'
                            ))

                        await conn.executemany("""
                            INSERT INTO units (
                                area_id, nomenclature_letter_area, nomenclature_number_area,
                                nomenclature_number_unit, status, extra_attributes,
                                created_at, updated_at
                            ) VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
                        """, unit_values)

                        units_created += area_data.capacity

        logger.info(f"Updated event {event_id}: {areas_updated} areas updated, {areas_created} created, {areas_deleted} deleted, {units_created} units created")

        # Get updated event
        event = await get_event_by_id(event_id, profile_id, tenant_id)

        return {
            "event": event,
            "areas_updated": areas_updated,
            "areas_created": areas_created,
            "areas_deleted": areas_deleted,
            "units_created": units_created
        }
