import logging
from typing import Optional, List
from datetime import datetime, timedelta, date
from app.database import get_db_connection
from app.models.dashboard import (
    EventSalesSummary, AreaSalesBreakdown, SalesTimeSeries, SalesTimePoint,
    RevenueReport, PaymentMethodBreakdown, CheckInAnalytics, DashboardOverview,
    DateRange
)

logger = logging.getLogger(__name__)


def get_date_range(range_type: DateRange) -> tuple[date, date]:
    """Convierte un DateRange a fechas inicio/fin"""
    today = date.today()

    if range_type == DateRange.TODAY:
        return today, today
    elif range_type == DateRange.YESTERDAY:
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif range_type == DateRange.LAST_7_DAYS:
        return today - timedelta(days=7), today
    elif range_type == DateRange.LAST_30_DAYS:
        return today - timedelta(days=30), today
    elif range_type == DateRange.THIS_MONTH:
        first_day = today.replace(day=1)
        return first_day, today
    elif range_type == DateRange.LAST_MONTH:
        first_day_this_month = today.replace(day=1)
        last_day_last_month = first_day_this_month - timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        return first_day_last_month, last_day_last_month
    else:  # ALL_TIME
        return date(2020, 1, 1), today


async def get_dashboard_overview(profile_id: str, tenant_id: str) -> DashboardOverview:
    """Obtiene vista general del dashboard del organizador"""
    async with get_db_connection(use_transaction=False) as conn:
        # Conteo de eventos
        event_counts = await conn.fetchrow("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'active') as active,
                COUNT(*) FILTER (WHERE start_date > NOW()) as upcoming,
                COUNT(*) FILTER (WHERE end_date < NOW()) as past
            FROM clusters
            WHERE profile_id = $1 AND tenant_id = $2
        """, profile_id, tenant_id)

        # Totales de ventas
        sales_totals = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT ru.id) as total_sold,
                COALESCE(SUM(p.amount), 0) as total_revenue
            FROM clusters c
            JOIN areas a ON a.cluster_id = c.id
            JOIN units u ON u.area_id = a.id
            JOIN reservation_units ru ON ru.unit_id = u.id
            LEFT JOIN reservations r ON ru.reservation_id = r.id
            LEFT JOIN payments p ON p.reservation_id = r.id AND p.status = 'approved'
            WHERE c.profile_id = $1 AND c.tenant_id = $2 AND ru.status IN ('confirmed', 'used')
        """, profile_id, tenant_id)

        # Eventos recientes con ventas
        recent_rows = await conn.fetch("""
            SELECT
                c.id as event_id,
                c.cluster_name as event_name,
                c.start_date as event_date,
                c.status as event_status,
                COUNT(DISTINCT u.id) as total_capacity,
                COUNT(DISTINCT u.id) FILTER (WHERE ru.id IS NULL OR ru.status = 'cancelled') as available_units,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status IN ('confirmed', 'used')) as sold_units,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status = 'reserved') as reserved_units,
                COALESCE(SUM(p.amount) FILTER (WHERE p.status = 'approved'), 0) as total_revenue,
                COALESCE(SUM(r.total_price) FILTER (WHERE r.status = 'pending'), 0) as pending_revenue
            FROM clusters c
            LEFT JOIN areas a ON a.cluster_id = c.id
            LEFT JOIN units u ON u.area_id = a.id
            LEFT JOIN reservation_units ru ON ru.unit_id = u.id
            LEFT JOIN reservations r ON ru.reservation_id = r.id
            LEFT JOIN payments p ON p.reservation_id = r.id
            WHERE c.profile_id = $1 AND c.tenant_id = $2
            GROUP BY c.id
            ORDER BY c.start_date DESC
            LIMIT 5
        """, profile_id, tenant_id)

        recent_events = []
        for row in recent_rows:
            total = row['total_capacity'] or 1
            sold = row['sold_units'] or 0
            recent_events.append(EventSalesSummary(
                event_id=row['event_id'],
                event_name=row['event_name'],
                event_date=row['event_date'],
                event_status=row['event_status'] or 'draft',
                total_capacity=row['total_capacity'] or 0,
                available_units=row['available_units'] or 0,
                sold_units=sold,
                reserved_units=row['reserved_units'] or 0,
                total_revenue=float(row['total_revenue'] or 0),
                pending_revenue=float(row['pending_revenue'] or 0),
                occupancy_percentage=round((sold / total * 100) if total > 0 else 0, 2)
            ))

        # Actividad últimas 24 horas
        recent_activity = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT ru.id) as sales_count,
                COALESCE(SUM(p.amount), 0) as revenue
            FROM clusters c
            JOIN areas a ON a.cluster_id = c.id
            JOIN units u ON u.area_id = a.id
            JOIN reservation_units ru ON ru.unit_id = u.id
            JOIN reservations r ON ru.reservation_id = r.id
            LEFT JOIN payments p ON p.reservation_id = r.id AND p.status = 'approved'
            WHERE c.profile_id = $1 AND c.tenant_id = $2
              AND ru.status IN ('confirmed', 'used')
              AND ru.created_at >= NOW() - INTERVAL '24 hours'
        """, profile_id, tenant_id)

        return DashboardOverview(
            profile_id=profile_id,
            total_events=event_counts['total'] or 0,
            active_events=event_counts['active'] or 0,
            upcoming_events=event_counts['upcoming'] or 0,
            past_events=event_counts['past'] or 0,
            total_tickets_sold=sales_totals['total_sold'] or 0,
            total_revenue=float(sales_totals['total_revenue'] or 0),
            recent_events=recent_events,
            recent_sales_count=recent_activity['sales_count'] or 0,
            recent_revenue=float(recent_activity['revenue'] or 0)
        )


async def get_event_sales_summary(
    profile_id: str,
    tenant_id: str,
    event_id: int
) -> Optional[EventSalesSummary]:
    """Obtiene resumen de ventas de un evento"""
    async with get_db_connection(use_transaction=False) as conn:
        row = await conn.fetchrow("""
            SELECT
                c.id as event_id,
                c.cluster_name as event_name,
                c.start_date as event_date,
                c.status as event_status,
                c.created_at,
                COUNT(DISTINCT u.id) as total_capacity,
                COUNT(DISTINCT u.id) FILTER (WHERE ru.id IS NULL OR ru.status = 'cancelled') as available_units,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status IN ('confirmed', 'used')) as sold_units,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status = 'reserved') as reserved_units,
                COALESCE(SUM(p.amount) FILTER (WHERE p.status = 'approved'), 0) as total_revenue,
                COALESCE(SUM(r.total_price) FILTER (WHERE r.status = 'pending'), 0) as pending_revenue
            FROM clusters c
            LEFT JOIN areas a ON a.cluster_id = c.id
            LEFT JOIN units u ON u.area_id = a.id
            LEFT JOIN reservation_units ru ON ru.unit_id = u.id
            LEFT JOIN reservations r ON ru.reservation_id = r.id
            LEFT JOIN payments p ON p.reservation_id = r.id
            WHERE c.id = $1 AND c.profile_id = $2 AND c.tenant_id = $3
            GROUP BY c.id
        """, event_id, profile_id, tenant_id)

        if not row:
            return None

        total = row['total_capacity'] or 1
        sold = row['sold_units'] or 0

        # Calcular velocidad de ventas (ventas por día desde creación)
        days_since_creation = (datetime.now() - row['created_at']).days or 1
        sales_velocity = round(sold / days_since_creation, 2)

        return EventSalesSummary(
            event_id=row['event_id'],
            event_name=row['event_name'],
            event_date=row['event_date'],
            event_status=row['event_status'] or 'draft',
            total_capacity=row['total_capacity'] or 0,
            available_units=row['available_units'] or 0,
            sold_units=sold,
            reserved_units=row['reserved_units'] or 0,
            total_revenue=float(row['total_revenue'] or 0),
            pending_revenue=float(row['pending_revenue'] or 0),
            occupancy_percentage=round((sold / total * 100) if total > 0 else 0, 2),
            sales_velocity=sales_velocity
        )


async def get_area_sales_breakdown(
    profile_id: str,
    tenant_id: str,
    event_id: int
) -> List[AreaSalesBreakdown]:
    """Obtiene desglose de ventas por área"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify ownership
        event = await conn.fetchrow(
            "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            event_id, profile_id, tenant_id
        )
        if not event:
            return []

        rows = await conn.fetch("""
            SELECT
                a.id as area_id,
                a.area_name,
                a.base_price,
                COUNT(DISTINCT u.id) as total_units,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status IN ('confirmed', 'used')) as sold_units,
                COUNT(DISTINCT u.id) FILTER (WHERE ru.id IS NULL OR ru.status = 'cancelled') as available_units,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status = 'reserved') as reserved_units,
                COALESCE(SUM(p.amount) FILTER (WHERE p.status = 'approved'), 0) as revenue
            FROM areas a
            LEFT JOIN units u ON u.area_id = a.id
            LEFT JOIN reservation_units ru ON ru.unit_id = u.id
            LEFT JOIN reservations r ON ru.reservation_id = r.id
            LEFT JOIN payments p ON p.reservation_id = r.id
            WHERE a.cluster_id = $1
            GROUP BY a.id
            ORDER BY a.area_name
        """, event_id)

        result = []
        for row in rows:
            total = row['total_units'] or 1
            sold = row['sold_units'] or 0
            result.append(AreaSalesBreakdown(
                area_id=row['area_id'],
                area_name=row['area_name'],
                base_price=float(row['base_price'] or 0),
                current_price=float(row['base_price'] or 0),  # TODO: Apply sale stage
                total_units=row['total_units'] or 0,
                sold_units=sold,
                available_units=row['available_units'] or 0,
                reserved_units=row['reserved_units'] or 0,
                revenue=float(row['revenue'] or 0),
                occupancy_percentage=round((sold / total * 100) if total > 0 else 0, 2)
            ))

        return result


async def get_sales_time_series(
    profile_id: str,
    tenant_id: str,
    event_id: int,
    date_range: DateRange = DateRange.LAST_30_DAYS
) -> Optional[SalesTimeSeries]:
    """Obtiene serie temporal de ventas"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify ownership
        event = await conn.fetchrow(
            "SELECT id, cluster_name FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            event_id, profile_id, tenant_id
        )
        if not event:
            return None

        date_from, date_to = get_date_range(date_range)

        rows = await conn.fetch("""
            SELECT
                DATE(ru.created_at) as sale_date,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status IN ('confirmed', 'used')) as tickets_sold,
                COALESCE(SUM(p.amount) FILTER (WHERE p.status = 'approved'), 0) as revenue,
                COUNT(DISTINCT r.id) FILTER (WHERE r.status != 'cancelled') as reservations_created,
                COUNT(DISTINCT r.id) FILTER (WHERE r.status = 'expired') as reservations_expired
            FROM areas a
            JOIN units u ON u.area_id = a.id
            LEFT JOIN reservation_units ru ON ru.unit_id = u.id
            LEFT JOIN reservations r ON ru.reservation_id = r.id
            LEFT JOIN payments p ON p.reservation_id = r.id
            WHERE a.cluster_id = $1
              AND DATE(ru.created_at) BETWEEN $2 AND $3
            GROUP BY DATE(ru.created_at)
            ORDER BY sale_date
        """, event_id, date_from, date_to)

        data_points = []
        total_tickets = 0
        total_revenue = 0.0

        for row in rows:
            tickets = row['tickets_sold'] or 0
            revenue = float(row['revenue'] or 0)
            total_tickets += tickets
            total_revenue += revenue

            data_points.append(SalesTimePoint(
                date=row['sale_date'],
                tickets_sold=tickets,
                revenue=revenue,
                reservations_created=row['reservations_created'] or 0,
                reservations_expired=row['reservations_expired'] or 0
            ))

        return SalesTimeSeries(
            event_id=event_id,
            event_name=event['cluster_name'],
            date_range=date_range.value,
            data_points=data_points,
            total_tickets=total_tickets,
            total_revenue=total_revenue
        )


async def get_revenue_report(
    profile_id: str,
    tenant_id: str,
    event_id: int
) -> Optional[RevenueReport]:
    """Obtiene reporte de ingresos"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify ownership and get event name
        event = await conn.fetchrow(
            "SELECT id, cluster_name FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            event_id, profile_id, tenant_id
        )
        if not event:
            return None

        # Totals
        totals = await conn.fetchrow("""
            SELECT
                COALESCE(SUM(p.amount) FILTER (WHERE p.status = 'approved'), 0) as gross_revenue,
                COALESCE(SUM(p.amount) FILTER (WHERE p.status = 'refunded'), 0) as refunds,
                COUNT(DISTINCT p.id) FILTER (WHERE p.status = 'approved') as transaction_count,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status IN ('confirmed', 'used')) as tickets_sold
            FROM areas a
            JOIN units u ON u.area_id = a.id
            LEFT JOIN reservation_units ru ON ru.unit_id = u.id
            LEFT JOIN reservations r ON ru.reservation_id = r.id
            LEFT JOIN payments p ON p.reservation_id = r.id
            WHERE a.cluster_id = $1
        """, event_id)

        gross = float(totals['gross_revenue'] or 0)
        refunds = float(totals['refunds'] or 0)
        tx_count = totals['transaction_count'] or 1
        tickets = totals['tickets_sold'] or 1

        # By payment method
        method_rows = await conn.fetch("""
            SELECT
                COALESCE(p.payment_method, 'unknown') as method,
                COUNT(*) as transaction_count,
                COALESCE(SUM(p.amount), 0) as total_amount
            FROM areas a
            JOIN units u ON u.area_id = a.id
            JOIN reservation_units ru ON ru.unit_id = u.id
            JOIN reservations r ON ru.reservation_id = r.id
            JOIN payments p ON p.reservation_id = r.id
            WHERE a.cluster_id = $1 AND p.status = 'approved'
            GROUP BY p.payment_method
        """, event_id)

        by_method = []
        for row in method_rows:
            amount = float(row['total_amount'] or 0)
            by_method.append(PaymentMethodBreakdown(
                method=row['method'],
                transaction_count=row['transaction_count'],
                total_amount=amount,
                percentage=round((amount / gross * 100) if gross > 0 else 0, 2)
            ))

        # By area (reuse area breakdown)
        by_area = await get_area_sales_breakdown(profile_id, tenant_id, event_id)

        return RevenueReport(
            event_id=event_id,
            event_name=event['cluster_name'],
            period="all_time",
            gross_revenue=gross,
            refunds=refunds,
            net_revenue=gross - refunds,
            by_payment_method=by_method,
            by_area=by_area,
            average_ticket_price=round(gross / tickets, 2) if tickets > 0 else 0,
            average_transaction_value=round(gross / tx_count, 2) if tx_count > 0 else 0
        )


async def get_check_in_analytics(
    profile_id: str,
    tenant_id: str,
    event_id: int
) -> Optional[CheckInAnalytics]:
    """Obtiene analíticas de check-in"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify ownership
        event = await conn.fetchrow(
            "SELECT id, cluster_name, start_date FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            event_id, profile_id, tenant_id
        )
        if not event:
            return None

        # Overall stats
        stats = await conn.fetchrow("""
            SELECT
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status IN ('confirmed', 'used')) as total_tickets,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status = 'used') as checked_in,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status = 'confirmed') as pending,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status = 'transferred') as transferred,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status = 'cancelled') as cancelled,
                MIN(ru.updated_at) FILTER (WHERE ru.status = 'used') as first_check_in,
                MAX(ru.updated_at) FILTER (WHERE ru.status = 'used') as last_check_in
            FROM areas a
            JOIN units u ON u.area_id = a.id
            LEFT JOIN reservation_units ru ON ru.unit_id = u.id
            WHERE a.cluster_id = $1
        """, event_id)

        total = stats['total_tickets'] or 0
        checked_in = stats['checked_in'] or 0

        # By area
        area_rows = await conn.fetch("""
            SELECT
                a.area_name,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status = 'used') as checked_in,
                COUNT(DISTINCT ru.id) FILTER (WHERE ru.status = 'confirmed') as pending
            FROM areas a
            LEFT JOIN units u ON u.area_id = a.id
            LEFT JOIN reservation_units ru ON ru.unit_id = u.id
            WHERE a.cluster_id = $1
            GROUP BY a.id
        """, event_id)

        by_area = []
        for row in area_rows:
            area_total = (row['checked_in'] or 0) + (row['pending'] or 0)
            by_area.append({
                "area_name": row['area_name'],
                "checked_in": row['checked_in'] or 0,
                "pending": row['pending'] or 0,
                "percentage": round((row['checked_in'] or 0) / area_total * 100 if area_total > 0 else 0, 2)
            })

        return CheckInAnalytics(
            event_id=event_id,
            event_name=event['cluster_name'],
            event_date=event['start_date'],
            total_tickets=total,
            checked_in=checked_in,
            pending=stats['pending'] or 0,
            transferred=stats['transferred'] or 0,
            cancelled=stats['cancelled'] or 0,
            check_in_percentage=round((checked_in / total * 100) if total > 0 else 0, 2),
            first_check_in=stats['first_check_in'],
            last_check_in=stats['last_check_in'],
            by_area=by_area
        )


async def get_attendee_list(
    profile_id: str,
    tenant_id: str,
    event_id: int,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[dict]:
    """Obtiene lista de asistentes"""
    async with get_db_connection(use_transaction=False) as conn:
        # Verify ownership
        event = await conn.fetchrow(
            "SELECT id FROM clusters WHERE id = $1 AND profile_id = $2 AND tenant_id = $3",
            event_id, profile_id, tenant_id
        )
        if not event:
            return []

        status_filter = ""
        if status:
            status_filter = f"AND ru.status = '{status}'"

        rows = await conn.fetch(f"""
            SELECT
                ru.id as ticket_id,
                ru.status,
                a.area_name,
                u.nomenclature_letter_area,
                u.nomenclature_number_unit,
                p.name as owner_name,
                p.email as owner_email,
                r.created_at as purchase_date,
                ru.updated_at as last_update
            FROM areas a
            JOIN units u ON u.area_id = a.id
            JOIN reservation_units ru ON ru.unit_id = u.id
            JOIN reservations r ON ru.reservation_id = r.id
            JOIN profile p ON r.user_id = p.id
            WHERE a.cluster_id = $1
              AND ru.status IN ('confirmed', 'used', 'transferred')
              {status_filter}
            ORDER BY ru.created_at DESC
            LIMIT $2 OFFSET $3
        """, event_id, limit, offset)

        return [
            {
                "ticket_id": row['ticket_id'],
                "status": row['status'],
                "area_name": row['area_name'],
                "unit_display_name": f"{row['nomenclature_letter_area'] or ''}-{row['nomenclature_number_unit'] or row['ticket_id']}".strip('-'),
                "owner_name": row['owner_name'],
                "owner_email": row['owner_email'],
                "purchase_date": row['purchase_date'],
                "last_update": row['last_update']
            }
            for row in rows
        ]
