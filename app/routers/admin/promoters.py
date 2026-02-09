"""
Admin Promoters Router
Endpoints for admins to manage promoter roles and codes.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional, List
from app.database import get_db_connection
from app.core.promoter_dependencies import require_promoter_access
from app.core.dependencies import get_environment
import logging

router = APIRouter(prefix="/admin/promoters", tags=["admin-promoters"])
logger = logging.getLogger(__name__)


class AssignPromoterRoleRequest(BaseModel):
    tenant_member_id: str
    site: str = "warotickets.com"
    commission_percentage: Optional[float] = 10.0


class PromoterRoleResponse(BaseModel):
    success: bool = True
    member_role: Optional[dict] = None
    message: str


class PromotersListResponse(BaseModel):
    success: bool = True
    promoters: list[dict]


@router.post("/assign-role", response_model=PromoterRoleResponse)
async def assign_promoter_role(
    data: AssignPromoterRoleRequest,
    request: Request,
    current_role: dict = Depends(require_promoter_access)
):
    """
    Asigna rol 'promotor' a un tenant_member usando tenant_member_roles.
    Solo accesible por admin o superuser.
    """
    # Verificar que el usuario actual es admin o superuser
    if current_role['role'] not in ['admin', 'superuser']:
        raise HTTPException(
            status_code=403,
            detail="Only admins can assign promoter roles"
        )

    tenant_id = current_role['tenant_id']

    async with get_db_connection() as conn:
        # Verificar que tenant_member existe
        member = await conn.fetchrow("""
            SELECT id FROM tenant_members
            WHERE id = $1 AND tenant_id = $2
        """, data.tenant_member_id, tenant_id)

        if not member:
            raise HTTPException(
                status_code=404,
                detail="Tenant member not found"
            )

        # Crear o actualizar tenant_member_role con site_role_name = 'promotor'
        member_role = await conn.fetchrow("""
            INSERT INTO tenant_member_roles (
                tenant_member_id, site, site_role_name, is_active
            )
            VALUES ($1, $2, 'promotor', true)
            ON CONFLICT (tenant_member_id, site)
            DO UPDATE SET
                site_role_name = 'promotor',
                is_active = true,
                updated_at = now()
            RETURNING *
        """, data.tenant_member_id, data.site)

        logger.info(
            f"Promoter role assigned to {data.tenant_member_id} "
            f"by {current_role['user_id']}"
        )

        return PromoterRoleResponse(
            success=True,
            member_role=dict(member_role),
            message="Promoter role assigned successfully"
        )


@router.delete("/revoke-role/{tenant_member_id}", response_model=PromoterRoleResponse)
async def revoke_promoter_role(
    tenant_member_id: str,
    request: Request,
    current_role: dict = Depends(require_promoter_access)
):
    """Revoca rol de promotor (desactiva promoter_code)"""
    if current_role['role'] not in ['admin', 'superuser']:
        raise HTTPException(
            status_code=403,
            detail="Only admins can revoke roles"
        )

    tenant_id = current_role['tenant_id']

    async with get_db_connection() as conn:
        result = await conn.execute("""
            UPDATE promoter_codes
            SET is_active = false, updated_at = now()
            WHERE tenant_member_id = $1 AND tenant_id = $2
        """, tenant_member_id, tenant_id)

        logger.info(
            f"Promoter role revoked for {tenant_member_id} "
            f"by {current_role['user_id']}"
        )

        return PromoterRoleResponse(
            success=True,
            message="Promoter role revoked"
        )


@router.get("/list", response_model=PromotersListResponse)
async def list_promoters(
    request: Request,
    current_role: dict = Depends(require_promoter_access)
):
    """Lista todos los promotores del tenant (con promoter_codes)"""
    tenant_id = current_role['tenant_id']

    async with get_db_connection(use_transaction=False) as conn:
        rows = await conn.fetch("""
            SELECT
                pc.id,
                pc.code as promoter_code,
                pc.commission_percentage,
                pc.is_active,
                pc.tenant_member_id,
                tm.user_id,
                tm.role as member_role,
                p.email,
                p.name,
                COALESCE(stats.total_sales, 0) as total_sales,
                COALESCE(ev.events_count, 0) as events_count
            FROM promoter_codes pc
            JOIN tenant_members tm ON tm.id = pc.tenant_member_id
            JOIN profile p ON p.id = tm.user_id
            LEFT JOIN LATERAL (
                SELECT SUM(oc.commission_amount) as total_sales
                FROM order_commissions oc
                WHERE oc.promoter_code_id = pc.id
            ) stats ON true
            LEFT JOIN LATERAL (
                SELECT COUNT(*) as events_count
                FROM promoter_event_configs pec
                WHERE pec.promoter_code_id = pc.id AND pec.is_active = true
            ) ev ON true
            WHERE pc.tenant_id = $1
            ORDER BY pc.created_at DESC
        """, tenant_id)

        return PromotersListResponse(
            success=True,
            promoters=[dict(row) for row in rows]
        )


@router.get("/detail/{promoter_code_id}")
async def get_promoter_detail(
    promoter_code_id: str,
    request: Request,
    current_role: dict = Depends(require_promoter_access),
    environment: str = Depends(get_environment)
):
    """Detalle completo de un promotor: info, eventos con ventas, ventas recientes"""
    tenant_id = current_role['tenant_id']

    async with get_db_connection(use_transaction=False) as conn:
        # 1. Info del promotor
        promoter = await conn.fetchrow("""
            SELECT
                pc.id, pc.code as promoter_code,
                pc.commission_percentage, pc.is_active,
                pc.tenant_member_id,
                tm.user_id, tm.role as member_role,
                p.email, p.name
            FROM promoter_codes pc
            JOIN tenant_members tm ON tm.id = pc.tenant_member_id
            JOIN profile p ON p.id = tm.user_id
            WHERE pc.id = $1 AND pc.tenant_id = $2
        """, promoter_code_id, tenant_id)

        if not promoter:
            raise HTTPException(status_code=404, detail="Promoter not found")

        # 2. Eventos asignados (desde promoter_event_configs + stats de order_commissions)
        events = await conn.fetch("""
            SELECT
                pec.cluster_id,
                c.cluster_name,
                c.start_date,
                pec.commission_percentage,
                COALESCE(stats.sales_count, 0) as sales_count,
                COALESCE(stats.revenue, 0) as revenue,
                COALESCE(stats.commission_earned, 0) as commission_earned
            FROM promoter_event_configs pec
            JOIN clusters c ON c.id = pec.cluster_id
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(oc.id) as sales_count,
                    SUM(oc.total_base_price) as revenue,
                    SUM(oc.commission_amount) as commission_earned
                FROM order_commissions oc
                WHERE oc.promoter_code_id = $1 AND oc.cluster_id = pec.cluster_id
            ) stats ON true
            WHERE pec.promoter_code_id = $1 AND pec.is_active = true
              AND c.environment = $2
            ORDER BY c.start_date DESC
        """, promoter_code_id, environment)

        # 3. Totales
        totals = await conn.fetchrow("""
            SELECT
                COALESCE(SUM(total_base_price), 0) as total_sales,
                COALESCE(SUM(commission_amount), 0) as total_commissions,
                COUNT(*) as total_orders
            FROM order_commissions
            WHERE promoter_code_id = $1
        """, promoter_code_id)

        # 4. Ventas recientes
        sales = await conn.fetch("""
            SELECT
                oc.id, oc.created_at, oc.tickets_count,
                oc.total_base_price as revenue,
                oc.commission_percentage, oc.commission_amount,
                oc.status,
                c.cluster_name as event_name
            FROM order_commissions oc
            LEFT JOIN clusters c ON c.id = oc.cluster_id
            WHERE oc.promoter_code_id = $1
            ORDER BY oc.created_at DESC
            LIMIT 20
        """, promoter_code_id)

        # 5. Eventos disponibles del tenant (excluir ya asignados, filtrar por environment)
        available_events = await conn.fetch("""
            SELECT id, cluster_name as name, start_date
            FROM clusters
            WHERE tenant_id = $1 AND environment = $3
              AND id NOT IN (
                  SELECT cluster_id FROM promoter_event_configs
                  WHERE promoter_code_id = $2 AND is_active = true
              )
            ORDER BY start_date DESC
        """, tenant_id, promoter_code_id, environment)

        return {
            "success": True,
            "promoter": {
                **dict(promoter),
                "total_sales": float(totals['total_sales']),
                "total_commissions": float(totals['total_commissions']),
                "total_orders": totals['total_orders']
            },
            "events": [dict(e) for e in events],
            "sales": [dict(s) for s in sales],
            "available_events": [dict(e) for e in available_events]
        }


@router.patch("/update-commission/{tenant_member_id}")
async def update_promoter_commission(
    tenant_member_id: str,
    commission_percentage: float,
    request: Request,
    current_role: dict = Depends(require_promoter_access)
):
    """
    Actualiza el porcentaje de comisión de un promotor.
    Solo accesible por admin o superuser.
    """
    if current_role['role'] not in ['admin', 'superuser']:
        raise HTTPException(
            status_code=403,
            detail="Only admins can update commission percentages"
        )

    tenant_id = current_role['tenant_id']

    async with get_db_connection() as conn:
        # Verificar que el promoter_code existe
        code = await conn.fetchrow("""
            SELECT id FROM promoter_codes
            WHERE tenant_member_id = $1 AND tenant_id = $2
        """, tenant_member_id, tenant_id)

        if not code:
            raise HTTPException(
                status_code=404,
                detail="Promoter code not found for this member"
            )

        # Actualizar porcentaje
        from app.services import promoter_codes_service
        updated = await promoter_codes_service.update_commission_percentage(
            promoter_code_id=code['id'],
            commission_percentage=commission_percentage
        )

        logger.info(
            f"Commission percentage updated to {commission_percentage}% "
            f"for {tenant_member_id} by {current_role['user_id']}"
        )

        return {
            "success": True,
            "promoter_code": updated,
            "message": "Commission percentage updated successfully"
        }


class EventConfigItem(BaseModel):
    cluster_id: int
    commission_percentage: float


class SaveEventConfigsRequest(BaseModel):
    events: List[EventConfigItem]


@router.put("/detail/{promoter_code_id}/events")
async def save_event_configs(
    promoter_code_id: str,
    data: SaveEventConfigsRequest,
    request: Request,
    current_role: dict = Depends(require_promoter_access)
):
    """
    Guarda la configuración de eventos del promotor (bulk upsert + delete).
    Reemplaza TODAS las configuraciones existentes con las nuevas.
    """
    if current_role['role'] not in ['admin', 'superuser']:
        raise HTTPException(
            status_code=403,
            detail="Only admins can manage event configurations"
        )

    tenant_id = current_role['tenant_id']

    async with get_db_connection() as conn:
        # Verificar que el promoter_code existe y pertenece al tenant
        promoter = await conn.fetchrow("""
            SELECT id FROM promoter_codes
            WHERE id = $1 AND tenant_id = $2
        """, promoter_code_id, tenant_id)

        if not promoter:
            raise HTTPException(status_code=404, detail="Promoter not found")

        # Desactivar todas las configuraciones existentes
        await conn.execute("""
            UPDATE promoter_event_configs
            SET is_active = false, updated_at = now()
            WHERE promoter_code_id = $1
        """, promoter_code_id)

        # Insertar/reactivar las nuevas configuraciones
        saved = []
        for event in data.events:
            row = await conn.fetchrow("""
                INSERT INTO promoter_event_configs (
                    promoter_code_id, cluster_id, tenant_id, commission_percentage, is_active
                )
                VALUES ($1, $2, $3, $4, true)
                ON CONFLICT (promoter_code_id, cluster_id)
                DO UPDATE SET
                    commission_percentage = $4,
                    is_active = true,
                    updated_at = now()
                RETURNING *
            """, promoter_code_id, event.cluster_id, tenant_id, event.commission_percentage)
            saved.append(dict(row))

        logger.info(
            f"Event configs saved for promoter {promoter_code_id}: "
            f"{len(saved)} events by {current_role['user_id']}"
        )

        return {
            "success": True,
            "events": saved,
            "message": f"{len(saved)} event configurations saved"
        }
