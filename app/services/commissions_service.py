"""
Commissions Service
Handles registration and management of promoter commissions.
"""

import logging
from typing import Optional
from decimal import Decimal
from app.database import get_db_connection

logger = logging.getLogger(__name__)


async def record_commission(
    payment_id: int,
    reservation_id: str
) -> Optional[dict]:
    """
    Registra una comisión para una reserva con promotor.
    Se llama desde el webhook de Wompi cuando el pago es aprobado.

    Args:
        payment_id: ID del pago (payments table)
        reservation_id: ID de la reserva

    Returns:
        dict | None: Registro de order_commission creado, o None si no hay promotor

    Raises:
        Exception: Si hay error en el cálculo o registro
    """
    async with get_db_connection() as conn:
        # Obtener reservation con datos del promoter y cluster_id via units
        data = await conn.fetchrow("""
            SELECT
                r.id,
                r.promoter_code_id,
                a.cluster_id,
                pc.tenant_member_id,
                pc.tenant_id,
                pc.commission_percentage
            FROM reservations r
            LEFT JOIN promoter_codes pc ON pc.id = r.promoter_code_id
            LEFT JOIN reservation_units ru ON ru.reservation_id = r.id
            LEFT JOIN units u ON u.id = ru.unit_id
            LEFT JOIN areas a ON a.id = u.area_id
            WHERE r.id = $1
            LIMIT 1
        """, reservation_id)

        if not data or not data['promoter_code_id']:
            logger.debug(f"No promoter code for reservation {reservation_id}")
            return None

        # Check if commission already exists (idempotency)
        existing = await conn.fetchrow("""
            SELECT * FROM order_commissions WHERE reservation_id = $1
        """, reservation_id)
        if existing:
            logger.info(f"Commission already exists for reservation {reservation_id}: {existing['id']}")
            return dict(existing)

        # Obtener precios REALES pagados (unit_price_paid considera etapas de venta y promociones)
        units_data = await conn.fetch("""
            SELECT ru.unit_price_paid
            FROM reservation_units ru
            WHERE ru.reservation_id = $1
        """, reservation_id)

        if not units_data:
            logger.error(f"No units found for reservation {reservation_id}")
            raise ValueError(f"No units found for reservation {reservation_id}")

        # Calcular total sobre precio real pagado (sin service fee)
        total_base_price = Decimal('0')
        total_tickets = 0

        for row in units_data:
            total_base_price += Decimal(str(row['unit_price_paid']))
            total_tickets += 1

        # Obtener % de comisión: override en promoter_event_configs > default del cluster
        # Un único query COALESCE resuelve la prioridad sin dos roundtrips
        commission_row = await conn.fetchrow("""
            SELECT COALESCE(
                (SELECT pec.commission_percentage
                 FROM promoter_event_configs pec
                 WHERE pec.promoter_code_id = $1 AND pec.cluster_id = $2 AND pec.is_active = true),
                c.commission_percentage
            ) AS commission_percentage,
            EXISTS(
                SELECT 1 FROM promoter_event_configs pec
                WHERE pec.promoter_code_id = $1 AND pec.cluster_id = $2 AND pec.is_active = true
            ) AS has_override
            FROM clusters c
            WHERE c.id = $2
        """, data['promoter_code_id'], data['cluster_id'])

        if not commission_row:
            logger.error(
                f"Cluster {data['cluster_id']} not found for reservation {reservation_id}"
            )
            return None

        commission_pct = Decimal(str(commission_row['commission_percentage']))
        source = "promoter_event_configs override" if commission_row['has_override'] else "cluster default"
        logger.info(
            f"Commission percentage {commission_pct}% resolved from {source} "
            f"(promoter: {data['promoter_code_id']}, cluster: {data['cluster_id']})"
        )

        # Calcular comisión
        commission_amount = (
            total_base_price * commission_pct / Decimal('100')
        ).quantize(Decimal('0.01'))

        # Insertar registro de comisión
        commission = await conn.fetchrow("""
            INSERT INTO order_commissions (
                reservation_id,
                payment_id,
                promoter_code_id,
                tenant_member_id,
                tenant_id,
                cluster_id,
                total_base_price,
                tickets_count,
                commission_percentage,
                commission_amount,
                status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'approved')
            RETURNING *
        """,
            reservation_id,
            payment_id,
            data['promoter_code_id'],
            data['tenant_member_id'],
            data['tenant_id'],
            data['cluster_id'],
            total_base_price,
            total_tickets,
            commission_pct,
            commission_amount
        )

        logger.info(
            f"Commission recorded: {commission['id']} - "
            f"${commission_amount} ({commission_pct}%) "
            f"for reservation {reservation_id}"
        )

        return dict(commission)


async def approve_commission(
    commission_id: str,
    approved_by: str,
    notes: Optional[str] = None
) -> dict:
    """
    Aprueba una comisión pendiente.

    Args:
        commission_id: ID de la comisión
        approved_by: ID del usuario que aprueba (profile.id)
        notes: Notas opcionales

    Returns:
        dict: Registro actualizado

    Raises:
        ValueError: Si la comisión no existe o ya fue aprobada
    """
    async with get_db_connection() as conn:
        # Verificar estado actual
        current = await conn.fetchrow("""
            SELECT id, status FROM order_commissions WHERE id = $1
        """, commission_id)

        if not current:
            raise ValueError(f"Commission {commission_id} not found")

        if current['status'] != 'pending':
            raise ValueError(
                f"Commission {commission_id} is not pending "
                f"(current status: {current['status']})"
            )

        # Actualizar a aprobada
        updated = await conn.fetchrow("""
            UPDATE order_commissions
            SET status = 'approved',
                approved_at = now(),
                approved_by = $1,
                notes = COALESCE($2, notes),
                updated_at = now()
            WHERE id = $3
            RETURNING *
        """, approved_by, notes, commission_id)

        logger.info(
            f"Commission approved: {commission_id} by user {approved_by}"
        )

        return dict(updated)


async def mark_commission_paid(
    commission_id: str,
    payment_reference: str,
    notes: Optional[str] = None
) -> dict:
    """
    Marca una comisión como pagada.

    Args:
        commission_id: ID de la comisión
        payment_reference: Referencia del pago realizado
        notes: Notas opcionales

    Returns:
        dict: Registro actualizado

    Raises:
        ValueError: Si la comisión no existe o no está aprobada
    """
    async with get_db_connection() as conn:
        # Verificar estado actual
        current = await conn.fetchrow("""
            SELECT id, status FROM order_commissions WHERE id = $1
        """, commission_id)

        if not current:
            raise ValueError(f"Commission {commission_id} not found")

        if current['status'] not in ['approved', 'pending']:
            raise ValueError(
                f"Commission {commission_id} cannot be marked as paid "
                f"(current status: {current['status']})"
            )

        # Actualizar a pagada
        updated = await conn.fetchrow("""
            UPDATE order_commissions
            SET status = 'paid',
                paid_at = now(),
                payment_reference = $1,
                notes = COALESCE($2, notes),
                updated_at = now()
            WHERE id = $3
            RETURNING *
        """, payment_reference, notes, commission_id)

        logger.info(
            f"Commission marked as paid: {commission_id} "
            f"(reference: {payment_reference})"
        )

        return dict(updated)


async def get_promoter_commissions(
    tenant_member_id: str,
    cluster_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None
) -> list[dict]:
    """
    Obtiene las comisiones de un promotor.

    Args:
        tenant_member_id: ID del tenant_member
        cluster_id: Filtrar por evento (opcional)
        limit: Límite de registros
        offset: Offset para paginación
        status: Filtrar por estado (opcional)

    Returns:
        list[dict]: Lista de comisiones
    """
    async with get_db_connection(use_transaction=False) as conn:
        # Build WHERE clause dynamically
        where_clauses = ["oc.tenant_member_id = $1"]
        params = [tenant_member_id]
        param_idx = 2

        if cluster_id is not None:
            where_clauses.append(f"oc.cluster_id = ${param_idx}")
            params.append(cluster_id)
            param_idx += 1

        if status:
            where_clauses.append(f"oc.status = ${param_idx}")
            params.append(status)
            param_idx += 1

        where_clause = " AND ".join(where_clauses)

        # Add limit and offset
        params.append(limit)
        params.append(offset)

        query = f"""
            SELECT
                oc.*,
                c.cluster_name,
                p.customer_data->>'email' as customer_email,
                p.customer_data->>'full_name' as customer_name
            FROM order_commissions oc
            LEFT JOIN clusters c ON c.id = oc.cluster_id
            LEFT JOIN payments p ON p.id = oc.payment_id
            WHERE {where_clause}
            ORDER BY oc.created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        rows = await conn.fetch(query, *params)
        return [dict(row) for row in rows]


async def get_promoter_stats(
    tenant_member_id: str,
    cluster_id: Optional[int] = None
) -> dict:
    """
    Obtiene estadísticas agregadas de un promotor.

    Args:
        tenant_member_id: ID del tenant_member
        cluster_id: Filtrar por evento (opcional)

    Returns:
        dict: {
            total_sales, total_tickets, total_revenue,
            pending, approved, paid
        }
    """
    async with get_db_connection(use_transaction=False) as conn:
        # Build WHERE clause dynamically
        where_clauses = ["oc.tenant_member_id = $1"]
        params = [tenant_member_id]

        if cluster_id is not None:
            where_clauses.append("oc.cluster_id = $2")
            params.append(cluster_id)

        where_clause = " AND ".join(where_clauses)

        # Include cluster_commission_percentage when filtering by a specific cluster
        cluster_pct_select = (
            ", c.commission_percentage as cluster_commission_percentage"
            if cluster_id is not None else ""
        )
        cluster_join = (
            "LEFT JOIN clusters c ON c.id = oc.cluster_id"
            if cluster_id is not None else ""
        )

        query = f"""
            SELECT
                COUNT(*) as total_sales,
                SUM(oc.tickets_count) as total_tickets,
                SUM(oc.total_base_price) as total_revenue,
                SUM(oc.commission_amount) as total_commissions,
                SUM(CASE WHEN oc.status = 'pending' THEN oc.commission_amount ELSE 0 END) as pending,
                SUM(CASE WHEN oc.status = 'approved' THEN oc.commission_amount ELSE 0 END) as approved,
                SUM(CASE WHEN oc.status = 'paid' THEN oc.commission_amount ELSE 0 END) as paid
                {cluster_pct_select}
            FROM order_commissions oc
            {cluster_join}
            WHERE {where_clause}
        """

        stats = await conn.fetchrow(query, *params)

        result = dict(stats) if stats else {}

        # Convert None to 0 for numeric fields
        for key in ['total_sales', 'total_tickets', 'total_revenue', 'total_commissions', 'pending', 'approved', 'paid']:
            if result.get(key) is None:
                result[key] = 0

        # cluster_commission_percentage is None when no cluster filter — leave as-is
        if cluster_id is None:
            result['cluster_commission_percentage'] = None

        return result
