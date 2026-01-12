import logging
from typing import Optional, List
from datetime import datetime
from app.database import get_db_connection
from app.models.sale_stage import (
    AreaSaleStage, AreaSaleStageCreate, AreaSaleStageUpdate, AreaSaleStageSummary
)
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


async def verify_cluster_ownership(conn, cluster_id: int, profile_id: str) -> bool:
    """Verifica que el cluster pertenece al organizador"""
    row = await conn.fetchrow(
        "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2",
        cluster_id, profile_id
    )
    return row is not None


async def verify_area_in_cluster(conn, area_id: int, cluster_id: int) -> bool:
    """Verifica que el area pertenece al cluster"""
    row = await conn.fetchrow(
        "SELECT id FROM areas WHERE id = $1 AND cluster_id = $2",
        area_id, cluster_id
    )
    return row is not None


async def get_sale_stages_by_cluster(
    cluster_id: int,
    profile_id: str,
    area_id: Optional[int] = None,
    is_active: Optional[bool] = None
) -> List[AreaSaleStageSummary]:
    """Get sale stages for a specific cluster/event"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            raise ValidationError("Cluster not found or access denied")

        query = """
            SELECT
                ass.id,
                ass.area_id,
                a.area_name,
                ass.stage_name,
                ass.price_adjustment_type,
                ass.price_adjustment_value,
                ass.quantity_available,
                ass.start_time,
                ass.end_time,
                ass.is_active,
                (ass.start_time <= NOW()
                 AND (ass.end_time IS NULL OR ass.end_time > NOW())
                 AND ass.quantity_available > 0
                 AND ass.is_active = true) as is_currently_active
            FROM area_sale_stages ass
            JOIN areas a ON ass.area_id = a.id
            WHERE a.cluster_id = $1
        """
        params = [cluster_id]
        param_idx = 2

        if area_id:
            query += f" AND ass.area_id = ${param_idx}"
            params.append(area_id)
            param_idx += 1

        if is_active is not None:
            query += f" AND ass.is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1

        query += " ORDER BY ass.priority_order ASC, ass.start_time ASC"

        rows = await conn.fetch(query, *params)
        result = []
        for row in rows:
            stage_dict = dict(row)
            stage_dict['id'] = str(row['id'])
            result.append(AreaSaleStageSummary(**stage_dict))
        return result


async def get_sale_stage_by_id(
    stage_id: str,
    cluster_id: int,
    profile_id: str
) -> Optional[AreaSaleStage]:
    """Get sale stage by ID within a cluster"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            return None

        row = await conn.fetchrow("""
            SELECT
                ass.*,
                a.area_name,
                a.cluster_id,
                (ass.start_time <= NOW()
                 AND (ass.end_time IS NULL OR ass.end_time > NOW())
                 AND ass.quantity_available > 0
                 AND ass.is_active = true) as is_currently_active
            FROM area_sale_stages ass
            JOIN areas a ON ass.area_id = a.id
            WHERE ass.id = $1 AND a.cluster_id = $2
        """, stage_id, cluster_id)

        if not row:
            return None

        stage_dict = dict(row)
        stage_dict['id'] = str(row['id'])
        return AreaSaleStage(**stage_dict)


async def create_sale_stage(
    cluster_id: int,
    profile_id: str,
    data: AreaSaleStageCreate
) -> AreaSaleStage:
    """Create a new sale stage for an area in a cluster"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            raise ValidationError("Cluster not found or access denied")

        # Verify area belongs to cluster
        if not await verify_area_in_cluster(conn, data.area_id, cluster_id):
            raise ValidationError("Area not found in this cluster")

        row = await conn.fetchrow("""
            INSERT INTO area_sale_stages (
                area_id, stage_name, description, price_adjustment_type,
                price_adjustment_value, quantity_available, start_time,
                end_time, is_active, priority_order, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, true, $9, NOW(), NOW()
            )
            RETURNING *
        """,
            data.area_id,
            data.stage_name,
            data.description,
            data.price_adjustment_type.value,
            data.price_adjustment_value,
            data.quantity_available,
            data.start_time,
            data.end_time,
            data.priority_order
        )

        logger.info(f"Created area sale stage: {row['id']} - {data.stage_name} for area {data.area_id}")

        # Get area info for response
        area_row = await conn.fetchrow(
            "SELECT area_name, cluster_id FROM areas WHERE id = $1",
            data.area_id
        )

        stage_dict = dict(row)
        # Convert UUID to string
        stage_dict['id'] = str(row['id'])
        stage_dict['area_name'] = area_row['area_name'] if area_row else None
        stage_dict['cluster_id'] = area_row['cluster_id'] if area_row else None
        stage_dict['is_currently_active'] = (
            row['start_time'] <= datetime.now(row['start_time'].tzinfo) and
            (row['end_time'] is None or row['end_time'] > datetime.now(row['start_time'].tzinfo)) and
            row['quantity_available'] > 0 and
            row['is_active']
        )

        return AreaSaleStage(**stage_dict)


async def update_sale_stage(
    stage_id: str,
    cluster_id: int,
    profile_id: str,
    data: AreaSaleStageUpdate
) -> Optional[AreaSaleStage]:
    """Update a sale stage"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            return None

        # Verify stage exists in cluster
        existing = await conn.fetchrow("""
            SELECT ass.id FROM area_sale_stages ass
            JOIN areas a ON ass.area_id = a.id
            WHERE ass.id = $1 AND a.cluster_id = $2
        """, stage_id, cluster_id)

        if not existing:
            return None

        # Build dynamic update
        update_fields = []
        params = []
        param_idx = 1

        update_data = data.model_dump(exclude_unset=True)
        logger.info(f"Update data received: {update_data}")

        for field, value in update_data.items():
            if field == 'price_adjustment_type' and value:
                value = value.value
            update_fields.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        if not update_fields:
            return await get_sale_stage_by_id(stage_id, cluster_id, profile_id)

        update_fields.append("updated_at = NOW()")

        query = f"""
            UPDATE area_sale_stages
            SET {', '.join(update_fields)}
            WHERE id = ${param_idx}
            RETURNING *
        """
        params.append(stage_id)

        logger.info(f"Update query: {query}")
        logger.info(f"Update params: {params}")

        result = await conn.fetchrow(query, *params)
        logger.info(f"Update result: {result}")
        logger.info(f"Updated area sale stage: {stage_id}")

        # Get updated data from same connection to ensure we see the committed changes
        updated_row = await conn.fetchrow("""
            SELECT
                ass.*,
                a.area_name,
                a.cluster_id,
                (ass.start_time <= NOW()
                 AND (ass.end_time IS NULL OR ass.end_time > NOW())
                 AND ass.quantity_available > 0
                 AND ass.is_active = true) as is_currently_active
            FROM area_sale_stages ass
            JOIN areas a ON ass.area_id = a.id
            WHERE ass.id = $1
        """, stage_id)

        if not updated_row:
            return None

        stage_dict = dict(updated_row)
        stage_dict['id'] = str(updated_row['id'])
        return AreaSaleStage(**stage_dict)


async def delete_sale_stage(
    stage_id: str,
    cluster_id: int,
    profile_id: str
) -> bool:
    """Delete a sale stage"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            return False

        # Verify stage exists in cluster
        existing = await conn.fetchrow("""
            SELECT ass.id FROM area_sale_stages ass
            JOIN areas a ON ass.area_id = a.id
            WHERE ass.id = $1 AND a.cluster_id = $2
        """, stage_id, cluster_id)

        if not existing:
            return False

        result = await conn.execute(
            "DELETE FROM area_sale_stages WHERE id = $1",
            stage_id
        )

        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"Deleted area sale stage: {stage_id}")
        return deleted


async def get_active_sale_stage_for_area(area_id: int) -> Optional[dict]:
    """Get the currently active sale stage for an area (used by pricing)"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT
                id,
                stage_name,
                price_adjustment_type,
                price_adjustment_value,
                quantity_available,
                end_time
            FROM area_sale_stages
            WHERE area_id = $1
              AND is_active = true
              AND start_time <= NOW()
              AND (end_time IS NULL OR end_time > NOW())
              AND quantity_available > 0
            ORDER BY priority_order ASC
            LIMIT 1
        """, area_id)

        if not row:
            return None

        return dict(row)


async def decrement_sale_stage_quantity(stage_id: str, quantity: int = 1) -> bool:
    """Decrement the available quantity of a sale stage after purchase"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE area_sale_stages
            SET quantity_available = quantity_available - $2,
                updated_at = NOW()
            WHERE id = $1 AND quantity_available >= $2
        """, stage_id, quantity)

        return result == "UPDATE 1"


# Aliases for backwards compatibility
get_sale_stages = get_sale_stages_by_cluster
