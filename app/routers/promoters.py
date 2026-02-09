"""
Promoters Router
Endpoints for promoters to manage their codes and view sales/commissions.
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.core.promoter_dependencies import require_promoter_access
from app.core.dependencies import get_environment
from app.services import promoter_codes_service, commissions_service
from app.database import get_db_connection
import logging
import os

router = APIRouter(tags=["promoters"])
logger = logging.getLogger(__name__)


class PromoterCodeResponse(BaseModel):
    code: str
    commission_percentage: Optional[float]
    role: str
    example_urls: List[str]


class SaleRecord(BaseModel):
    id: str
    reservation_id: str
    cluster_name: Optional[str]
    customer_email: Optional[str]
    customer_name: Optional[str]
    tickets_count: int
    total_base_price: float
    commission_percentage: float
    commission_amount: float
    status: str
    created_at: str


class SalesResponse(BaseModel):
    success: bool = True
    sales: List[dict]
    total: Optional[int] = None


class StatsResponse(BaseModel):
    success: bool = True
    stats: dict


@router.get("/me/code", response_model=PromoterCodeResponse)
async def get_my_code(
    request: Request,
    access: dict = Depends(require_promoter_access)
):
    """
    Obtiene o genera código del promotor.
    Accesible por: superuser, admin, promotor
    """
    tenant_member_id = access['tenant_member_id']
    tenant_id = access['tenant_id']

    # Obtener o crear código
    code = await promoter_codes_service.get_or_create_promoter_code(
        tenant_member_id=tenant_member_id,
        tenant_id=tenant_id
    )

    # Get frontend URL from environment
    frontend_url = os.getenv('FRONTEND_URL', 'https://warotickets.com')

    return PromoterCodeResponse(
        code=code['code'],
        commission_percentage=code.get('commission_percentage'),
        role=access['role'],
        example_urls=[
            f"{frontend_url}/eventos/cualquier-evento?WRPROM={code['code']}"
        ]
    )


@router.get("/me/sales", response_model=SalesResponse)
async def get_my_sales(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    cluster_id: Optional[int] = None,
    status: Optional[str] = None,
    access: dict = Depends(require_promoter_access)
):
    """
    Historial de ventas del promotor.
    Accesible por: superuser, admin, promotor
    Filtros opcionales: cluster_id (evento), status
    """
    tenant_member_id = access['tenant_member_id']

    # Validar status si se proporciona
    if status and status not in ['pending', 'approved', 'paid']:
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Must be one of: pending, approved, paid"
        )

    # Obtener ventas
    sales = await commissions_service.get_promoter_commissions(
        tenant_member_id=tenant_member_id,
        cluster_id=cluster_id,
        limit=limit,
        offset=offset,
        status=status
    )

    return SalesResponse(
        success=True,
        sales=sales,
        total=len(sales)
    )


@router.get("/me/stats", response_model=StatsResponse)
async def get_my_stats(
    request: Request,
    cluster_id: Optional[int] = None,
    access: dict = Depends(require_promoter_access)
):
    """
    Estadísticas agregadas del promotor.
    Accesible por: superuser, admin, promotor
    Filtros opcionales: cluster_id (evento)
    """
    tenant_member_id = access['tenant_member_id']

    # Obtener estadísticas
    stats = await commissions_service.get_promoter_stats(
        tenant_member_id=tenant_member_id,
        cluster_id=cluster_id
    )

    return StatsResponse(
        success=True,
        stats=stats
    )


@router.get("/me/commission/{commission_id}")
async def get_commission_detail(
    commission_id: str,
    request: Request,
    access: dict = Depends(require_promoter_access)
):
    """
    Obtiene el detalle de una comisión específica.
    Solo si pertenece al promotor autenticado.
    """
    tenant_member_id = access['tenant_member_id']

    async with get_db_connection(use_transaction=False) as conn:
        commission = await conn.fetchrow("""
            SELECT
                oc.*,
                c.cluster_name,
                c.event_name,
                c.event_date,
                p.customer_data->>'email' as customer_email,
                p.customer_data->>'full_name' as customer_name,
                p.amount as payment_amount
            FROM order_commissions oc
            LEFT JOIN clusters c ON c.id = oc.cluster_id
            LEFT JOIN payments p ON p.id = oc.payment_id
            WHERE oc.id = $1 AND oc.tenant_member_id = $2
        """, commission_id, tenant_member_id)

        if not commission:
            raise HTTPException(
                status_code=404,
                detail="Commission not found or access denied"
            )

        return {"success": True, "commission": dict(commission)}


@router.get("/me/events")
async def get_my_events(
    request: Request,
    access: dict = Depends(require_promoter_access),
    environment: str = Depends(get_environment)
):
    """
    Eventos asignados al promotor (desde promoter_event_configs).
    Retorna datos del evento + slug para generar enlaces.
    Filtrado por environment (dev/prod).
    """
    tenant_member_id = access['tenant_member_id']
    tenant_id = access['tenant_id']

    async with get_db_connection(use_transaction=False) as conn:
        # Obtener promoter_code del promotor
        promoter_code = await conn.fetchrow("""
            SELECT id FROM promoter_codes
            WHERE tenant_member_id = $1 AND tenant_id = $2 AND is_active = true
        """, tenant_member_id, tenant_id)

        if not promoter_code:
            return {"success": True, "events": []}

        # Obtener eventos asignados con datos del cluster
        events = await conn.fetch("""
            SELECT
                c.id as cluster_id,
                c.cluster_name,
                c.slug_cluster,
                c.start_date,
                c.is_active,
                pec.commission_percentage,
                pec.is_active as config_active
            FROM promoter_event_configs pec
            JOIN clusters c ON c.id = pec.cluster_id
            WHERE pec.promoter_code_id = $1
              AND pec.is_active = true
              AND c.environment = $2
            ORDER BY c.start_date DESC
        """, promoter_code['id'], environment)

        return {
            "success": True,
            "events": [dict(e) for e in events]
        }
