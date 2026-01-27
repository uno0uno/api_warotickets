from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.core.dependencies import get_authenticated_user, AuthenticatedUser
from app.models.dashboard import (
    EventSalesSummary, AreaSalesBreakdown, SalesTimeSeries,
    RevenueReport, CheckInAnalytics, DashboardOverview, DateRange
)
from app.services import dashboard_service

router = APIRouter()


@router.get("/overview", response_model=DashboardOverview)
async def get_dashboard_overview(
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get dashboard overview for the event organizer.

    Shows:
    - Total events count (active, upcoming, past)
    - Total tickets sold and revenue
    - Recent events with sales summary
    - Recent activity (last 24 hours)
    """
    overview = await dashboard_service.get_dashboard_overview(user.user_id, user.tenant_id)
    return overview


@router.get("/events/{event_id}/summary", response_model=EventSalesSummary)
async def get_event_sales_summary(
    event_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get sales summary for a specific event.

    Includes capacity, sold/available units, revenue, and occupancy percentage.
    """
    summary = await dashboard_service.get_event_sales_summary(user.user_id, user.tenant_id, event_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Event not found")
    return summary


@router.get("/events/{event_id}/areas", response_model=List[AreaSalesBreakdown])
async def get_area_sales_breakdown(
    event_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get sales breakdown by area for an event.

    Shows units sold, available, reserved, and revenue per area.
    """
    breakdown = await dashboard_service.get_area_sales_breakdown(user.user_id, user.tenant_id, event_id)
    if not breakdown:
        raise HTTPException(status_code=404, detail="Event not found or no areas")
    return breakdown


@router.get("/events/{event_id}/sales-chart", response_model=SalesTimeSeries)
async def get_sales_time_series(
    event_id: int,
    date_range: DateRange = Query(DateRange.LAST_30_DAYS, description="Date range for the chart"),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get time series data for sales chart.

    Returns daily sales data including tickets sold, revenue,
    and reservation statistics.
    """
    series = await dashboard_service.get_sales_time_series(
        user.user_id, user.tenant_id, event_id, date_range
    )
    if not series:
        raise HTTPException(status_code=404, detail="Event not found")
    return series


@router.get("/events/{event_id}/revenue", response_model=RevenueReport)
async def get_revenue_report(
    event_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get detailed revenue report for an event.

    Includes gross/net revenue, refunds, breakdown by payment method
    and by area, average ticket price, etc.
    """
    report = await dashboard_service.get_revenue_report(user.user_id, user.tenant_id, event_id)
    if not report:
        raise HTTPException(status_code=404, detail="Event not found")
    return report


@router.get("/events/{event_id}/checkins", response_model=CheckInAnalytics)
async def get_check_in_analytics(
    event_id: int,
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get check-in analytics for an event.

    Shows total tickets, checked in count, pending, by area breakdown,
    first/last check-in times.
    """
    analytics = await dashboard_service.get_check_in_analytics(user.user_id, user.tenant_id, event_id)
    if not analytics:
        raise HTTPException(status_code=404, detail="Event not found")
    return analytics


@router.get("/events/{event_id}/attendees", response_model=List[dict])
async def get_attendee_list(
    event_id: int,
    status: Optional[str] = Query(None, description="Filter by status: confirmed, used, transferred"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_authenticated_user)
):
    """
    Get list of attendees for an event.

    Returns ticket holders with their status, area, and contact info.
    Supports pagination.
    """
    attendees = await dashboard_service.get_attendee_list(
        user.user_id, user.tenant_id, event_id, status, limit, offset
    )
    return attendees
