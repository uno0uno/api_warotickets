import logging
from typing import Optional, List
from datetime import datetime
from app.database import get_db_connection
from app.models.promotion import (
    Promotion, PromotionCreate, PromotionUpdate, PromotionSummary
)
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)


async def get_promotions(
    profile_id: str,
    cluster_id: Optional[int] = None,
    is_active: Optional[bool] = None
) -> List[PromotionSummary]:
    """Get promotions for organizer"""
    async with get_db_connection(use_transaction=False) as conn:
        query = """
            SELECT p.id, p.promotion_name, p.promotion_code,
                   p.discount_type, p.discount_value,
                   p.start_date, p.end_date, p.is_active,
                   (p.start_date <= NOW() AND p.end_date > NOW() AND p.is_active) as is_currently_valid
            FROM promotions p
            LEFT JOIN clusters c ON p.target_cluster_id = c.id
            WHERE (c.profile_id = $1 OR p.target_cluster_id IS NULL)
        """
        params = [profile_id]
        param_idx = 2

        if cluster_id:
            query += f" AND p.target_cluster_id = ${param_idx}"
            params.append(cluster_id)
            param_idx += 1

        if is_active is not None:
            query += f" AND p.is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1

        query += " ORDER BY p.created_at DESC"

        rows = await conn.fetch(query, *params)
        return [PromotionSummary(**dict(row)) for row in rows]


async def get_promotion_by_id(promo_id: str, profile_id: str) -> Optional[Promotion]:
    """Get promotion by ID"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT p.*,
                (p.start_date <= NOW() AND p.end_date > NOW() AND p.is_active) as is_currently_valid
            FROM promotions p
            LEFT JOIN clusters c ON p.target_cluster_id = c.id
            WHERE p.id = $1 AND (c.profile_id = $2 OR p.target_cluster_id IS NULL)
        """, promo_id, profile_id)

        if not row:
            return None

        return Promotion(**dict(row))


async def get_promotion_by_code(code: str) -> Optional[Promotion]:
    """Get promotion by code (for validation)"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT *,
                (start_date <= NOW() AND end_date > NOW() AND is_active) as is_currently_valid
            FROM promotions
            WHERE promotion_code = $1
        """, code.upper().strip())

        if not row:
            return None

        return Promotion(**dict(row))


async def create_promotion(profile_id: str, data: PromotionCreate) -> Promotion:
    """Create a new promotion"""
    async with get_db_connection() as conn:
        # Verify cluster ownership if target_cluster_id provided
        if data.target_cluster_id:
            cluster = await conn.fetchrow(
                "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2",
                data.target_cluster_id, profile_id
            )
            if not cluster:
                raise ValidationError("Event not found or access denied")

        # Verify area ownership if target_area_id provided
        if data.target_area_id:
            area = await conn.fetchrow("""
                SELECT a.id FROM areas a
                JOIN clusters c ON a.cluster_id = c.id
                WHERE a.id = $1 AND c.profile_id = $2
            """, data.target_area_id, profile_id)

            if not area:
                raise ValidationError("Area not found or access denied")

        # Check for duplicate code
        if data.promotion_code:
            existing = await conn.fetchrow(
                "SELECT id FROM promotions WHERE promotion_code = $1",
                data.promotion_code.upper().strip()
            )
            if existing:
                raise ValidationError("Promotion code already exists")

        row = await conn.fetchrow("""
            INSERT INTO promotions (
                promotion_name, promotion_code, description,
                discount_type, discount_value, applies_to,
                target_cluster_id, target_area_id, target_product_id, target_product_variant_id,
                min_quantity, max_discount_amount, start_date, end_date,
                is_active, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, true, NOW(), NOW()
            )
            RETURNING *
        """,
            data.promotion_name,
            data.promotion_code.upper().strip() if data.promotion_code else None,
            data.description,
            data.discount_type.value,
            data.discount_value,
            data.applies_to.value,
            data.target_cluster_id,
            data.target_area_id,
            data.target_product_id,
            data.target_product_variant_id,
            data.min_quantity,
            data.max_discount_amount,
            data.start_date,
            data.end_date
        )

        logger.info(f"Created promotion: {row['id']} - {data.promotion_name}")

        promo_dict = dict(row)
        promo_dict['is_currently_valid'] = (
            row['start_date'] <= datetime.now(row['start_date'].tzinfo) and
            row['end_date'] > datetime.now(row['start_date'].tzinfo) and
            row['is_active']
        )

        return Promotion(**promo_dict)


async def update_promotion(
    promo_id: str, profile_id: str, data: PromotionUpdate
) -> Optional[Promotion]:
    """Update a promotion"""
    async with get_db_connection() as conn:
        # Verify ownership
        existing = await conn.fetchrow("""
            SELECT p.id FROM promotions p
            LEFT JOIN clusters c ON p.target_cluster_id = c.id
            WHERE p.id = $1 AND (c.profile_id = $2 OR p.target_cluster_id IS NULL)
        """, promo_id, profile_id)

        if not existing:
            return None

        # Build dynamic update
        update_fields = []
        params = []
        param_idx = 1

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if field == 'discount_type' and value:
                value = value.value
            if field == 'applies_to' and value:
                value = value.value
            if field == 'promotion_code' and value:
                value = value.upper().strip()
            update_fields.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        if not update_fields:
            return await get_promotion_by_id(promo_id, profile_id)

        update_fields.append("updated_at = NOW()")

        query = f"""
            UPDATE promotions
            SET {', '.join(update_fields)}
            WHERE id = ${param_idx}
            RETURNING *
        """
        params.append(promo_id)

        await conn.fetchrow(query, *params)
        logger.info(f"Updated promotion: {promo_id}")

        return await get_promotion_by_id(promo_id, profile_id)


async def delete_promotion(promo_id: str, profile_id: str) -> bool:
    """Delete a promotion"""
    async with get_db_connection() as conn:
        # Verify ownership
        existing = await conn.fetchrow("""
            SELECT p.id FROM promotions p
            LEFT JOIN clusters c ON p.target_cluster_id = c.id
            WHERE p.id = $1 AND (c.profile_id = $2 OR p.target_cluster_id IS NULL)
        """, promo_id, profile_id)

        if not existing:
            return False

        result = await conn.execute(
            "DELETE FROM promotions WHERE id = $1",
            promo_id
        )

        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"Deleted promotion: {promo_id}")
        return deleted
