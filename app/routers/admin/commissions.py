"""
Admin Commissions Router
Endpoints for admins to manage commission approvals and payments.
"""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional
from app.database import get_db_connection
from app.core.promoter_dependencies import require_admin_role
from app.services import commissions_service
import logging

router = APIRouter(prefix="/admin/commissions", tags=["admin-commissions"])
logger = logging.getLogger(__name__)


class ApproveCommissionRequest(BaseModel):
    notes: Optional[str] = None


class MarkPaidRequest(BaseModel):
    payment_reference: str
    notes: Optional[str] = None


class CommissionResponse(BaseModel):
    success: bool = True
    commission: dict
    message: str


class CommissionsListResponse(BaseModel):
    success: bool = True
    commissions: list[dict]
    total: Optional[int] = None


@router.patch("/{commission_id}/approve", response_model=CommissionResponse)
async def approve_commission(
    commission_id: str,
    data: ApproveCommissionRequest,
    request: Request,
    admin: dict = Depends(require_admin_role)
):
    """
    Aprueba una comisión pendiente.
    Solo accesible por admin o superuser.
    """
    user_id = admin['user_id']

    try:
        updated = await commissions_service.approve_commission(
            commission_id=commission_id,
            approved_by=user_id,
            notes=data.notes
        )

        return CommissionResponse(
            success=True,
            commission=updated,
            message="Commission approved successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{commission_id}/mark-paid", response_model=CommissionResponse)
async def mark_commission_paid(
    commission_id: str,
    data: MarkPaidRequest,
    request: Request,
    admin: dict = Depends(require_admin_role)
):
    """
    Marca una comisión como pagada.
    Solo accesible por admin o superuser.
    """
    try:
        updated = await commissions_service.mark_commission_paid(
            commission_id=commission_id,
            payment_reference=data.payment_reference,
            notes=data.notes
        )

        return CommissionResponse(
            success=True,
            commission=updated,
            message="Commission marked as paid successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/list", response_model=CommissionsListResponse)
async def list_all_commissions(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    tenant_member_id: Optional[str] = None,
    admin: dict = Depends(require_admin_role)
):
    """
    Lista todas las comisiones del tenant.
    Opcionalmente filtra por status y/o tenant_member_id.
    Solo accesible por admin o superuser.
    """
    tenant_id = admin['tenant_id']

    # Validar status si se proporciona
    if status and status not in ['pending', 'approved', 'paid']:
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Must be one of: pending, approved, paid"
        )

    async with get_db_connection(use_transaction=False) as conn:
        # Build query dynamically based on filters
        conditions = ["oc.tenant_id = $1"]
        params = [tenant_id]
        param_idx = 2

        if status:
            conditions.append(f"oc.status = ${param_idx}")
            params.append(status)
            param_idx += 1

        if tenant_member_id:
            conditions.append(f"oc.tenant_member_id = ${param_idx}")
            params.append(tenant_member_id)
            param_idx += 1

        where_clause = " AND ".join(conditions)

        # Add limit and offset
        params.extend([limit, offset])

        query = f"""
            SELECT
                oc.*,
                c.cluster_name,
                c.event_name,
                p.customer_email,
                p.customer_name,
                tm.user_id,
                prof.email as promoter_email,
                prof.full_name as promoter_name
            FROM order_commissions oc
            LEFT JOIN clusters c ON c.id = oc.cluster_id
            LEFT JOIN payments p ON p.id = oc.payment_id
            LEFT JOIN tenant_members tm ON tm.id = oc.tenant_member_id
            LEFT JOIN profile prof ON prof.id = tm.user_id
            WHERE {where_clause}
            ORDER BY oc.created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        rows = await conn.fetch(query, *params)

        return CommissionsListResponse(
            success=True,
            commissions=[dict(row) for row in rows],
            total=len(rows)
        )


@router.get("/summary")
async def get_commissions_summary(
    request: Request,
    admin: dict = Depends(require_admin_role)
):
    """
    Obtiene resumen de comisiones por estado para el tenant.
    Solo accesible por admin o superuser.
    """
    tenant_id = admin['tenant_id']

    async with get_db_connection(use_transaction=False) as conn:
        summary = await conn.fetchrow("""
            SELECT
                COUNT(*) as total_commissions,
                SUM(tickets_count) as total_tickets,
                SUM(commission_amount) as total_amount,
                SUM(CASE WHEN status = 'pending' THEN commission_amount ELSE 0 END) as pending_amount,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_count,
                SUM(CASE WHEN status = 'approved' THEN commission_amount ELSE 0 END) as approved_amount,
                COUNT(CASE WHEN status = 'approved' THEN 1 END) as approved_count,
                SUM(CASE WHEN status = 'paid' THEN commission_amount ELSE 0 END) as paid_amount,
                COUNT(CASE WHEN status = 'paid' THEN 1 END) as paid_count
            FROM order_commissions
            WHERE tenant_id = $1
        """, tenant_id)

        result = dict(summary) if summary else {}

        # Convert None to 0 for numeric fields
        for key in result.keys():
            if result[key] is None:
                result[key] = 0

        return {
            "success": True,
            "summary": result
        }


@router.get("/{commission_id}", response_model=CommissionResponse)
async def get_commission_detail(
    commission_id: str,
    request: Request,
    admin: dict = Depends(require_admin_role)
):
    """
    Obtiene el detalle completo de una comisión.
    Solo accesible por admin o superuser.
    """
    tenant_id = admin['tenant_id']

    async with get_db_connection(use_transaction=False) as conn:
        commission = await conn.fetchrow("""
            SELECT
                oc.*,
                c.cluster_name,
                c.event_name,
                c.event_date,
                p.customer_email,
                p.customer_name,
                p.amount as payment_amount,
                p.status as payment_status,
                tm.user_id,
                prof.email as promoter_email,
                prof.full_name as promoter_name,
                approver.email as approved_by_email,
                approver.full_name as approved_by_name
            FROM order_commissions oc
            LEFT JOIN clusters c ON c.id = oc.cluster_id
            LEFT JOIN payments p ON p.id = oc.payment_id
            LEFT JOIN tenant_members tm ON tm.id = oc.tenant_member_id
            LEFT JOIN profile prof ON prof.id = tm.user_id
            LEFT JOIN profile approver ON approver.id = oc.approved_by
            WHERE oc.id = $1 AND oc.tenant_id = $2
        """, commission_id, tenant_id)

        if not commission:
            raise HTTPException(
                status_code=404,
                detail="Commission not found"
            )

        return CommissionResponse(
            success=True,
            commission=dict(commission),
            message="Commission retrieved successfully"
        )
