import logging
from typing import Optional, List
from datetime import datetime
from app.database import get_db_connection
from app.models.area_promotion import (
    AreaPromotion, AreaPromotionCreate, AreaPromotionUpdate,
    AreaPromotionSummary, PromotionValidation
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


async def get_promotions_by_cluster(
    cluster_id: int,
    profile_id: str,
    area_id: Optional[int] = None,
    is_active: Optional[bool] = None
) -> List[AreaPromotionSummary]:
    """Get promotions for a specific cluster/event"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            raise ValidationError("Cluster not found or access denied")

        query = """
            SELECT
                ap.id,
                ap.area_id,
                a.area_name,
                ap.promotion_name,
                ap.promotion_code,
                ap.discount_type,
                ap.discount_value,
                ap.start_time,
                ap.end_time,
                ap.is_active,
                (ap.start_time <= NOW()
                 AND (ap.end_time IS NULL OR ap.end_time > NOW())
                 AND (ap.quantity_available IS NULL OR ap.quantity_available > 0)
                 AND ap.is_active = true) as is_currently_valid
            FROM area_promotions ap
            JOIN areas a ON ap.area_id = a.id
            WHERE a.cluster_id = $1
        """
        params = [cluster_id]
        param_idx = 2

        if area_id:
            query += f" AND ap.area_id = ${param_idx}"
            params.append(area_id)
            param_idx += 1

        if is_active is not None:
            query += f" AND ap.is_active = ${param_idx}"
            params.append(is_active)
            param_idx += 1

        query += " ORDER BY ap.priority_order ASC, ap.start_time ASC"

        rows = await conn.fetch(query, *params)
        result = []
        for row in rows:
            promo_dict = dict(row)
            promo_dict['id'] = str(row['id'])
            result.append(AreaPromotionSummary(**promo_dict))
        return result


async def get_promotion_by_id(
    promo_id: str,
    cluster_id: int,
    profile_id: str
) -> Optional[AreaPromotion]:
    """Get promotion by ID within a cluster"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            return None

        row = await conn.fetchrow("""
            SELECT
                ap.*,
                a.area_name,
                a.cluster_id,
                (ap.start_time <= NOW()
                 AND (ap.end_time IS NULL OR ap.end_time > NOW())
                 AND (ap.quantity_available IS NULL OR ap.quantity_available > 0)
                 AND ap.is_active = true) as is_currently_valid
            FROM area_promotions ap
            JOIN areas a ON ap.area_id = a.id
            WHERE ap.id = $1 AND a.cluster_id = $2
        """, promo_id, cluster_id)

        if not row:
            return None

        promo_dict = dict(row)
        promo_dict['id'] = str(row['id'])
        return AreaPromotion(**promo_dict)


async def get_promotion_by_code(code: str) -> Optional[dict]:
    """Get promotion by code (for public validation)"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT
                ap.*,
                a.area_name,
                a.cluster_id,
                (ap.start_time <= NOW()
                 AND (ap.end_time IS NULL OR ap.end_time > NOW())
                 AND (ap.quantity_available IS NULL OR ap.quantity_available > 0)
                 AND ap.is_active = true) as is_currently_valid
            FROM area_promotions ap
            JOIN areas a ON ap.area_id = a.id
            WHERE ap.promotion_code = $1
        """, code.upper().strip())

        if not row:
            return None

        return dict(row)


async def create_promotion(
    cluster_id: int,
    profile_id: str,
    data: AreaPromotionCreate
) -> AreaPromotion:
    """Create a new promotion for an area in a cluster"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            raise ValidationError("Cluster not found or access denied")

        # Verify area belongs to cluster
        if not await verify_area_in_cluster(conn, data.area_id, cluster_id):
            raise ValidationError("Area not found in this cluster")

        # Check for duplicate code
        if data.promotion_code:
            existing = await conn.fetchrow(
                "SELECT id FROM area_promotions WHERE promotion_code = $1",
                data.promotion_code.upper().strip()
            )
            if existing:
                raise ValidationError("Promotion code already exists")

        row = await conn.fetchrow("""
            INSERT INTO area_promotions (
                area_id, promotion_name, promotion_code, description,
                discount_type, discount_value, max_discount_amount,
                min_quantity, quantity_available, start_time,
                end_time, is_active, priority_order, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, true, $12, NOW(), NOW()
            )
            RETURNING *
        """,
            data.area_id,
            data.promotion_name,
            data.promotion_code.upper().strip() if data.promotion_code else None,
            data.description,
            data.discount_type.value,
            data.discount_value,
            data.max_discount_amount,
            data.min_quantity,
            data.quantity_available,
            data.start_time,
            data.end_time,
            data.priority_order
        )

        logger.info(f"Created area promotion: {row['id']} - {data.promotion_name} for area {data.area_id}")

        # Get area info for response
        area_row = await conn.fetchrow(
            "SELECT area_name, cluster_id FROM areas WHERE id = $1",
            data.area_id
        )

        promo_dict = dict(row)
        promo_dict['id'] = str(row['id'])
        promo_dict['area_name'] = area_row['area_name'] if area_row else None
        promo_dict['cluster_id'] = area_row['cluster_id'] if area_row else None
        promo_dict['is_currently_valid'] = (
            row['start_time'] <= datetime.now(row['start_time'].tzinfo) and
            (row['end_time'] is None or row['end_time'] > datetime.now(row['start_time'].tzinfo)) and
            (row['quantity_available'] is None or row['quantity_available'] > 0) and
            row['is_active']
        )

        return AreaPromotion(**promo_dict)


async def update_promotion(
    promo_id: str,
    cluster_id: int,
    profile_id: str,
    data: AreaPromotionUpdate
) -> Optional[AreaPromotion]:
    """Update a promotion"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            return None

        # Verify promotion exists in cluster
        existing = await conn.fetchrow("""
            SELECT ap.id FROM area_promotions ap
            JOIN areas a ON ap.area_id = a.id
            WHERE ap.id = $1 AND a.cluster_id = $2
        """, promo_id, cluster_id)

        if not existing:
            return None

        # Build dynamic update
        update_fields = []
        params = []
        param_idx = 1

        update_data = data.model_dump(exclude_unset=True)
        logger.info(f"Update data received: {update_data}")

        for field, value in update_data.items():
            if field == 'discount_type' and value:
                value = value.value
            if field == 'promotion_code' and value:
                value = value.upper().strip()
            update_fields.append(f"{field} = ${param_idx}")
            params.append(value)
            param_idx += 1

        if not update_fields:
            return await get_promotion_by_id(promo_id, cluster_id, profile_id)

        update_fields.append("updated_at = NOW()")

        query = f"""
            UPDATE area_promotions
            SET {', '.join(update_fields)}
            WHERE id = ${param_idx}
            RETURNING *
        """
        params.append(promo_id)

        logger.info(f"Update query: {query}")
        logger.info(f"Update params: {params}")

        await conn.fetchrow(query, *params)
        logger.info(f"Updated area promotion: {promo_id}")

        # Get updated data
        updated_row = await conn.fetchrow("""
            SELECT
                ap.*,
                a.area_name,
                a.cluster_id,
                (ap.start_time <= NOW()
                 AND (ap.end_time IS NULL OR ap.end_time > NOW())
                 AND (ap.quantity_available IS NULL OR ap.quantity_available > 0)
                 AND ap.is_active = true) as is_currently_valid
            FROM area_promotions ap
            JOIN areas a ON ap.area_id = a.id
            WHERE ap.id = $1
        """, promo_id)

        if not updated_row:
            return None

        promo_dict = dict(updated_row)
        promo_dict['id'] = str(updated_row['id'])
        return AreaPromotion(**promo_dict)


async def delete_promotion(
    promo_id: str,
    cluster_id: int,
    profile_id: str
) -> bool:
    """Delete a promotion"""
    async with get_db_connection() as conn:
        # Verify cluster ownership
        if not await verify_cluster_ownership(conn, cluster_id, profile_id):
            return False

        # Verify promotion exists in cluster
        existing = await conn.fetchrow("""
            SELECT ap.id FROM area_promotions ap
            JOIN areas a ON ap.area_id = a.id
            WHERE ap.id = $1 AND a.cluster_id = $2
        """, promo_id, cluster_id)

        if not existing:
            return False

        result = await conn.execute(
            "DELETE FROM area_promotions WHERE id = $1",
            promo_id
        )

        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"Deleted area promotion: {promo_id}")
        return deleted


async def get_active_promotion_for_area(area_id: int) -> Optional[dict]:
    """Get the currently active promotion for an area (used by pricing)"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT
                id,
                promotion_name,
                promotion_code,
                discount_type,
                discount_value,
                max_discount_amount,
                quantity_available,
                end_time
            FROM area_promotions
            WHERE area_id = $1
              AND is_active = true
              AND start_time <= NOW()
              AND (end_time IS NULL OR end_time > NOW())
              AND (quantity_available IS NULL OR quantity_available > 0)
            ORDER BY priority_order ASC
            LIMIT 1
        """, area_id)

        if not row:
            return None

        return dict(row)


async def validate_promotion_code(
    code: str,
    area_id: int,
    quantity: int = 1
) -> PromotionValidation:
    """Validate a promotion code for a specific area"""
    async with get_db_connection(use_transaction=False) as conn:
        # Get promotion by code
        promo = await conn.fetchrow("""
            SELECT
                ap.*,
                a.cluster_id
            FROM area_promotions ap
            JOIN areas a ON ap.area_id = a.id
            WHERE ap.promotion_code = $1
        """, code.upper().strip())

        if not promo:
            return PromotionValidation(
                is_valid=False,
                error_message="Codigo promocional no encontrado"
            )

        # Check if active
        if not promo['is_active']:
            return PromotionValidation(
                is_valid=False,
                error_message="Este codigo ya no esta activo"
            )

        # Check dates
        now = datetime.now(promo['start_time'].tzinfo)
        if promo['start_time'] > now:
            return PromotionValidation(
                is_valid=False,
                error_message="Este codigo aun no esta vigente"
            )

        if promo['end_time'] and promo['end_time'] <= now:
            return PromotionValidation(
                is_valid=False,
                error_message="Este codigo ha expirado"
            )

        # Check minimum quantity
        if quantity < promo['min_quantity']:
            return PromotionValidation(
                is_valid=False,
                error_message=f"Se requieren minimo {promo['min_quantity']} tickets"
            )

        # Check available uses
        if promo['quantity_available'] is not None and promo['quantity_available'] < quantity:
            return PromotionValidation(
                is_valid=False,
                error_message="No hay suficientes usos disponibles para este codigo"
            )

        # Check area match
        if promo['area_id'] != area_id:
            return PromotionValidation(
                is_valid=False,
                error_message="Este codigo no aplica para esta localidad"
            )

        return PromotionValidation(
            is_valid=True,
            promotion_id=str(promo['id']),
            promotion_name=promo['promotion_name'],
            discount_type=promo['discount_type'],
            discount_value=promo['discount_value'],
            max_discount_amount=promo['max_discount_amount']
        )


async def decrement_promotion_quantity(promo_id: str, quantity: int = 1) -> bool:
    """Decrement the available quantity of a promotion after use"""
    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE area_promotions
            SET quantity_available = quantity_available - $2,
                updated_at = NOW()
            WHERE id = $1
              AND quantity_available IS NOT NULL
              AND quantity_available >= $2
        """, promo_id, quantity)

        return result == "UPDATE 1"
