import logging
import json
from typing import Optional, List
from datetime import datetime, timezone
from app.database import get_db_connection
from app.models.sale_stage import (
    SaleStage, SaleStageCreate, SaleStageUpdate, SaleStageSummary
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
    """Verifica que el cluster pertenece al organizador y tenant"""
    row = await conn.fetchrow(
        "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
        cluster_id, profile_id, tenant_id
    )
    return row is not None


async def verify_areas_in_cluster(conn, area_ids: List[int], cluster_id: int) -> bool:
    """Verifica que todas las areas pertenecen al cluster"""
    result = await conn.fetchval(
        "SELECT COUNT(*) FROM areas WHERE id = ANY($1) AND cluster_id = $2",
        area_ids, cluster_id
    )
    return result == len(area_ids)


async def get_cluster_dates(conn, cluster_id: int) -> tuple:
    """Get the created_at and start_date of a cluster/event"""
    row = await conn.fetchrow(
        "SELECT created_at, start_date FROM clusters WHERE id = $1",
        cluster_id
    )
    if not row:
        return None, None
    return row['created_at'], row['start_date']


async def validate_stage_dates(conn, cluster_id: int, start_time: datetime, end_time: Optional[datetime]) -> None:
    """Validate that sale stage dates are between event creation and event start"""
    event_created, event_start = await get_cluster_dates(conn, cluster_id)

    if not event_created and not event_start:
        return  # No dates, skip validation

    # Make timezone aware if needed
    if event_created and event_created.tzinfo is None:
        event_created = event_created.replace(tzinfo=timezone.utc)
    if event_start and event_start.tzinfo is None:
        event_start = event_start.replace(tzinfo=timezone.utc)

    stage_start = start_time
    if stage_start.tzinfo is None:
        stage_start = stage_start.replace(tzinfo=timezone.utc)

    # Validate minimum date (event creation)
    if event_created and stage_start < event_created:
        raise ValidationError(f"La fecha de inicio de la etapa debe ser despues de la creacion del evento ({event_created.strftime('%d/%m/%Y %H:%M')})")

    # Validate maximum date (event start)
    if event_start and stage_start >= event_start:
        raise ValidationError(f"La fecha de inicio de la etapa debe ser antes del evento ({event_start.strftime('%d/%m/%Y %H:%M')})")

    if end_time:
        stage_end = end_time
        if stage_end.tzinfo is None:
            stage_end = stage_end.replace(tzinfo=timezone.utc)

        if event_created and stage_end < event_created:
            raise ValidationError(f"La fecha de fin de la etapa debe ser despues de la creacion del evento ({event_created.strftime('%d/%m/%Y %H:%M')})")

        if event_start and stage_end > event_start:
            raise ValidationError(f"La fecha de fin de la etapa debe ser antes del evento ({event_start.strftime('%d/%m/%Y %H:%M')})")


async def get_sale_stages_by_cluster(
    cluster_id: int,
    profile_id: str,
    tenant_id: str,
    is_active: Optional[bool] = None
) -> List[SaleStageSummary]:
    """Get all sale stages for a cluster/event"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            raise ValidationError("Cluster not found or access denied")

        query = """
            SELECT
                ss.id,
                ss.cluster_id,
                ss.stage_name,
                ss.price_adjustment_type,
                ss.price_adjustment_value,
                ss.quantity_available,
                ss.quantity_sold,
                ss.start_time,
                ss.end_time,
                ss.is_active,
                ss.priority_order,
                (ss.start_time <= NOW()
                 AND (ss.end_time IS NULL OR ss.end_time > NOW())
                 AND (ss.quantity_available - ss.quantity_sold) > 0
                 AND ss.is_active = true) as is_currently_active,
                (SELECT COUNT(*) FROM sale_stage_areas ssa WHERE ssa.sale_stage_id = ss.id) as area_count,
                (SELECT json_agg(json_build_object('id', a.id, 'area_name', a.area_name))
                 FROM sale_stage_areas ssa
                 JOIN areas a ON ssa.area_id = a.id
                 WHERE ssa.sale_stage_id = ss.id) as areas
            FROM sale_stages ss
            WHERE ss.cluster_id = $1
        """
        params = [cluster_id]
        param_idx = 2

        if is_active is not None:
            query += f" AND ss.is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1

        query += " ORDER BY ss.priority_order ASC, ss.start_time ASC"

        rows = await conn.fetch(query, *params)
        result = []
        for row in rows:
            stage_dict = dict(row)
            stage_dict['id'] = str(row['id'])
            stage_dict['areas'] = _parse_json_field(row['areas'])
            result.append(SaleStageSummary(**stage_dict))
        return result


async def get_sale_stage_by_id(
    stage_id: str,
    cluster_id: int,
    profile_id: str,
    tenant_id: str
) -> Optional[SaleStage]:
    """Get sale stage by ID"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            return None

        row = await conn.fetchrow("""
            SELECT
                ss.*,
                (ss.start_time <= NOW()
                 AND (ss.end_time IS NULL OR ss.end_time > NOW())
                 AND (ss.quantity_available - ss.quantity_sold) > 0
                 AND ss.is_active = true) as is_currently_active,
                (ss.quantity_available - ss.quantity_sold) as quantity_remaining,
                (SELECT array_agg(ssa.area_id) FROM sale_stage_areas ssa WHERE ssa.sale_stage_id = ss.id) as area_ids,
                (SELECT json_agg(json_build_object('id', a.id, 'area_name', a.area_name))
                 FROM sale_stage_areas ssa
                 JOIN areas a ON ssa.area_id = a.id
                 WHERE ssa.sale_stage_id = ss.id) as areas
            FROM sale_stages ss
            WHERE ss.id = $1 AND ss.cluster_id = $2
        """, stage_id, cluster_id)

        if not row:
            return None

        stage_dict = dict(row)
        stage_dict['id'] = str(row['id'])
        stage_dict['area_ids'] = list(row['area_ids']) if row['area_ids'] else []
        stage_dict['areas'] = _parse_json_field(row['areas'])
        return SaleStage(**stage_dict)


async def create_sale_stage(
    cluster_id: int,
    profile_id: str,
    tenant_id: str,
    data: SaleStageCreate
) -> SaleStage:
    """Create a new sale stage for a cluster"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            raise ValidationError("Cluster not found or access denied")

        # Verify all areas belong to cluster
        if not await verify_areas_in_cluster(conn, data.area_ids, cluster_id):
            raise ValidationError("One or more areas do not belong to this cluster")

        # Validate dates are before event start
        await validate_stage_dates(conn, cluster_id, data.start_time, data.end_time)

        # Create sale stage
        row = await conn.fetchrow("""
            INSERT INTO sale_stages (
                cluster_id, stage_name, description, price_adjustment_type,
                price_adjustment_value, quantity_available, quantity_sold,
                start_time, end_time, is_active, priority_order,
                created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, 0, $7, $8, true, $9, NOW(), NOW()
            )
            RETURNING *
        """,
            cluster_id,
            data.stage_name,
            data.description,
            data.price_adjustment_type.value,
            data.price_adjustment_value,
            data.quantity_available,
            data.start_time,
            data.end_time,
            data.priority_order
        )

        stage_id = row['id']

        # Create area links
        for area_id in data.area_ids:
            await conn.execute("""
                INSERT INTO sale_stage_areas (sale_stage_id, area_id)
                VALUES ($1, $2)
            """, stage_id, area_id)

        logger.info(f"Created sale stage: {stage_id} - {data.stage_name} for cluster {cluster_id}")

        # Get areas for response
        areas = await conn.fetch("""
            SELECT a.id, a.area_name
            FROM sale_stage_areas ssa
            JOIN areas a ON ssa.area_id = a.id
            WHERE ssa.sale_stage_id = $1
        """, stage_id)

        stage_dict = dict(row)
        stage_dict['id'] = str(stage_id)
        stage_dict['area_ids'] = data.area_ids
        stage_dict['areas'] = [{'id': a['id'], 'area_name': a['area_name']} for a in areas]
        stage_dict['is_currently_active'] = (
            row['start_time'] <= datetime.now(timezone.utc) and
            (row['end_time'] is None or row['end_time'] > datetime.now(timezone.utc)) and
            row['quantity_available'] > 0 and
            row['is_active']
        )
        stage_dict['quantity_remaining'] = row['quantity_available']

        return SaleStage(**stage_dict)


async def update_sale_stage(
    stage_id: str,
    cluster_id: int,
    profile_id: str,
    tenant_id: str,
    data: SaleStageUpdate
) -> Optional[SaleStage]:
    """Update a sale stage"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            return None

        # Verify stage exists in cluster
        existing = await conn.fetchrow(
            "SELECT id FROM sale_stages WHERE id = $1 AND cluster_id = $2",
            stage_id, cluster_id
        )

        if not existing:
            return None

        # Handle area_ids update separately
        update_data = data.model_dump(exclude_unset=True)
        area_ids = update_data.pop('area_ids', None)

        # Validate dates if provided
        start_time = update_data.get('start_time')
        end_time = update_data.get('end_time')
        if start_time or end_time:
            # Get current values if not updating
            if not start_time or not end_time:
                current = await conn.fetchrow(
                    "SELECT start_time, end_time FROM sale_stages WHERE id = $1",
                    stage_id
                )
                if not start_time:
                    start_time = current['start_time']
                if end_time is None and 'end_time' not in update_data:
                    end_time = current['end_time']
            await validate_stage_dates(conn, cluster_id, start_time, end_time)

        # Build dynamic update for other fields
        if update_data:
            update_fields = []
            params = []
            param_idx = 1

            for field, value in update_data.items():
                if field == 'price_adjustment_type' and value:
                    value = value.value
                update_fields.append(f"{field} = ${param_idx}")
                params.append(value)
                param_idx += 1

            if update_fields:
                update_fields.append("updated_at = NOW()")
                query = f"""
                    UPDATE sale_stages
                    SET {', '.join(update_fields)}
                    WHERE id = ${param_idx}
                """
                params.append(stage_id)
                await conn.execute(query, *params)

        # Update area links if provided
        if area_ids is not None:
            # Verify all areas belong to cluster
            if area_ids and not await verify_areas_in_cluster(conn, area_ids, cluster_id):
                raise ValidationError("One or more areas do not belong to this cluster")

            # Delete existing links
            await conn.execute(
                "DELETE FROM sale_stage_areas WHERE sale_stage_id = $1",
                stage_id
            )

            # Create new links
            for area_id in area_ids:
                await conn.execute("""
                    INSERT INTO sale_stage_areas (sale_stage_id, area_id)
                    VALUES ($1, $2)
                """, stage_id, area_id)

        logger.info(f"Updated sale stage: {stage_id}")

        return await get_sale_stage_by_id(stage_id, cluster_id, profile_id, tenant_id)


async def delete_sale_stage(
    stage_id: str,
    cluster_id: int,
    profile_id: str,
    tenant_id: str
) -> bool:
    """Delete a sale stage"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id, tenant_id):
            return False

        # Verify stage exists in cluster
        existing = await conn.fetchrow(
            "SELECT id FROM sale_stages WHERE id = $1 AND cluster_id = $2",
            stage_id, cluster_id
        )

        if not existing:
            return False

        # Delete (cascade will remove sale_stage_areas entries)
        result = await conn.execute(
            "DELETE FROM sale_stages WHERE id = $1",
            stage_id
        )

        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"Deleted sale stage: {stage_id}")
        return deleted


async def get_active_sale_stage_for_area(area_id: int) -> Optional[dict]:
    """Get the currently active sale stage for an area (used by pricing)"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT
                ss.id,
                ss.stage_name,
                ss.price_adjustment_type,
                ss.price_adjustment_value,
                (ss.quantity_available - ss.quantity_sold) as quantity_remaining,
                ss.end_time
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

        if not row:
            return None

        return dict(row)


async def decrement_sale_stage_quantity(stage_id: str, quantity: int = 1) -> bool:
    """Decrement the available quantity of a sale stage after purchase"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE sale_stages
            SET quantity_sold = quantity_sold + $2,
                updated_at = NOW()
            WHERE id = $1
              AND (quantity_available - quantity_sold) >= $2
        """, stage_id, quantity)

        return result == "UPDATE 1"


async def get_public_sale_stages(cluster_id: int) -> List[dict]:
    """Get active sale stages for public event view"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify event is public
        event = await conn.fetchrow("""
            SELECT id FROM clusters
            WHERE id = $1 AND is_active = true AND shadowban = false
        """, cluster_id)

        if not event:
            return []

        now = datetime.now(timezone.utc)

        # Get active sale stages
        stages = await conn.fetch("""
            SELECT
                ss.id,
                ss.stage_name,
                ss.description,
                ss.price_adjustment_type,
                ss.price_adjustment_value,
                ss.quantity_available,
                ss.quantity_sold,
                ss.start_time,
                ss.end_time
            FROM sale_stages ss
            WHERE ss.cluster_id = $1
              AND ss.is_active = true
              AND ss.start_time <= $2
              AND (ss.end_time IS NULL OR ss.end_time > $2)
              AND (ss.quantity_available - ss.quantity_sold) > 0
            ORDER BY ss.priority_order ASC
        """, cluster_id, now)

        result = []
        for stage in stages:
            # Get areas for this stage
            areas_rows = await conn.fetch("""
                SELECT a.id, a.area_name, a.price
                FROM sale_stage_areas ssa
                JOIN areas a ON ssa.area_id = a.id
                WHERE ssa.sale_stage_id = $1
            """, stage['id'])

            areas = []
            for a in areas_rows:
                base_price = float(a['price']) if a['price'] else 0
                adj_type = stage['price_adjustment_type']
                adj_value = float(stage['price_adjustment_value']) if stage['price_adjustment_value'] else 0

                if adj_type == 'percentage':
                    current_price = base_price * (1 + adj_value / 100)
                    discount = base_price - current_price if adj_value < 0 else 0
                elif adj_type == 'fixed':
                    current_price = base_price + adj_value
                    discount = -adj_value if adj_value < 0 else 0
                else:
                    current_price = base_price
                    discount = 0

                areas.append({
                    'area_id': a['id'],
                    'area_name': a['area_name'],
                    'base_price': base_price,
                    'current_price': max(0, current_price),
                    'discount': abs(discount)
                })

            remaining = stage['quantity_available'] - stage['quantity_sold']

            result.append({
                'id': str(stage['id']),
                'stage_name': stage['stage_name'],
                'description': stage['description'],
                'price_adjustment_type': stage['price_adjustment_type'],
                'price_adjustment_value': float(stage['price_adjustment_value']) if stage['price_adjustment_value'] else 0,
                'tickets_remaining': remaining,
                'end_time': stage['end_time'].isoformat() if stage['end_time'] else None,
                'areas': areas
            })

        return result


# Aliases for backwards compatibility
get_sale_stages = get_sale_stages_by_cluster
