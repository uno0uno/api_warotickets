import logging
from typing import Optional, List
from datetime import datetime
from app.database import get_db_connection
from app.models.sale_stage import (
    SaleStage, SaleStageCreate, SaleStageUpdate, SaleStageSummary
)
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


async def get_sale_stages(
    profile_id: str,
    area_id: Optional[int] = None,
    is_active: Optional[bool] = None
) -> List[SaleStageSummary]:
    """Get sale stages for organizer"""
    async with get_db_connection(use_transaction=False) as conn:
        query = """
            SELECT ss.id, ss.stage_name, ss.price_adjustment_type,
                   ss.price_adjustment_value, ss.quantity_available,
                   ss.start_time, ss.end_time, ss.is_active,
                   (ss.start_time <= NOW() AND (ss.end_time IS NULL OR ss.end_time > NOW()) AND ss.quantity_available > 0) as is_currently_active
            FROM sale_stages ss
            LEFT JOIN areas a ON ss.target_area_id = a.id
            LEFT JOIN clusters c ON a.cluster_id = c.id
            WHERE (c.profile_id = $1 OR ss.target_area_id IS NULL)
        """
        params = [profile_id]
        param_idx = 2

        if area_id:
            query += f" AND ss.target_area_id = ${param_idx}"
            params.append(area_id)
            param_idx += 1

        if is_active is not None:
            query += f" AND ss.is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1

        query += " ORDER BY ss.priority_order ASC, ss.start_time ASC"

        rows = await conn.fetch(query, *params)
        return [SaleStageSummary(**dict(row)) for row in rows]


async def get_sale_stage_by_id(stage_id: str, profile_id: str) -> Optional[SaleStage]:
    """Get sale stage by ID"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT ss.*,
                (ss.start_time <= NOW() AND (ss.end_time IS NULL OR ss.end_time > NOW()) AND ss.quantity_available > 0) as is_currently_active
            FROM sale_stages ss
            LEFT JOIN areas a ON ss.target_area_id = a.id
            LEFT JOIN clusters c ON a.cluster_id = c.id
            WHERE ss.id = $1 AND (c.profile_id = $2 OR ss.target_area_id IS NULL)
        """, stage_id, profile_id)

        if not row:
            return None

        return SaleStage(**dict(row))


async def create_sale_stage(profile_id: str, data: SaleStageCreate) -> SaleStage:
    """Create a new sale stage"""
    async with get_db_connection() as conn:
        # Verify area ownership if target_area_id provided
        if data.target_area_id:
            area = await conn.fetchrow("""
                SELECT a.id FROM areas a
                JOIN clusters c ON a.cluster_id = c.id
                WHERE a.id = $1 AND c.profile_id = $2
            """, data.target_area_id, profile_id)

            if not area:
                raise ValidationError("Area not found or access denied")

        row = await conn.fetchrow("""
            INSERT INTO sale_stages (
                stage_name, description, price_adjustment_type, price_adjustment_value,
                quantity_available, start_time, end_time, is_active, priority_order,
                target_area_id, target_product_variant_id, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, true, $8, $9, $10, NOW(), NOW()
            )
            RETURNING *
        """,
            data.stage_name,
            data.description,
            data.price_adjustment_type.value,
            data.price_adjustment_value,
            data.quantity_available,
            data.start_time,
            data.end_time,
            data.priority_order,
            data.target_area_id,
            data.target_product_variant_id
        )

        logger.info(f"Created sale stage: {row['id']} - {data.stage_name}")

        stage_dict = dict(row)
        stage_dict['is_currently_active'] = (
            row['start_time'] <= datetime.now(row['start_time'].tzinfo) and
            (row['end_time'] is None or row['end_time'] > datetime.now(row['start_time'].tzinfo)) and
            row['quantity_available'] > 0
        )

        return SaleStage(**stage_dict)


async def update_sale_stage(
    stage_id: str, profile_id: str, data: SaleStageUpdate
) -> Optional[SaleStage]:
    """Update a sale stage"""
    async with get_db_connection() as conn:
        # Verify ownership
        existing = await conn.fetchrow("""
            SELECT ss.id FROM sale_stages ss
            LEFT JOIN areas a ON ss.target_area_id = a.id
            LEFT JOIN clusters c ON a.cluster_id = c.id
            WHERE ss.id = $1 AND (c.profile_id = $2 OR ss.target_area_id IS NULL)
        """, stage_id, profile_id)

        if not existing:
            return None

        # Build dynamic update
        update_fields = []
        params = []
        param_idx = 1

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field == 'price_adjustment_type' and value:
                value = value.value
            update_fields.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        if not update_fields:
            return await get_sale_stage_by_id(stage_id, profile_id)

        update_fields.append("updated_at = NOW()")

        query = f"""
            UPDATE sale_stages
            SET {', '.join(update_fields)}
            WHERE id = ${param_idx}
            RETURNING *
        """
        params.append(stage_id)

        await conn.fetchrow(query, *params)
        logger.info(f"Updated sale stage: {stage_id}")

        return await get_sale_stage_by_id(stage_id, profile_id)


async def delete_sale_stage(stage_id: str, profile_id: str) -> bool:
    """Delete a sale stage"""
    async with get_db_connection() as conn:
        # Verify ownership
        existing = await conn.fetchrow("""
            SELECT ss.id FROM sale_stages ss
            LEFT JOIN areas a ON ss.target_area_id = a.id
            LEFT JOIN clusters c ON a.cluster_id = c.id
            WHERE ss.id = $1 AND (c.profile_id = $2 OR ss.target_area_id IS NULL)
        """, stage_id, profile_id)

        if not existing:
            return False

        result = await conn.execute(
            "DELETE FROM sale_stages WHERE id = $1",
            stage_id
        )

        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"Deleted sale stage: {stage_id}")
        return deleted
